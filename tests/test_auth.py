from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import app.api.auth as auth_api
from app.db.models import User
from app.db.session import get_db
from app.main import app
from app.schemas.auth import AuthCredentials
from app.services.auth_service import (
    DUPLICATE_LOGIN_MESSAGE,
    InvalidCurrentPasswordError,
    change_account_password,
    hash_password,
    normalize_login_id,
    verify_password,
)


def test_passwords_are_salted_and_verified() -> None:
    first = hash_password("secret-password")
    second = hash_password("secret-password")

    assert first != second
    assert "secret-password" not in first
    assert verify_password("secret-password", first)
    assert not verify_password("wrong-password", first)
    assert not verify_password("secret-password", "malformed")


def test_login_id_is_normalized_and_minimum_lengths_are_enforced() -> None:
    assert normalize_login_id("  ZoEy  ") == "zoey"
    assert normalize_login_id("ZOËY") == normalize_login_id("zoëy")
    with pytest.raises(ValidationError):
        AuthCredentials(login_id="z", password="123456")
    with pytest.raises(ValidationError):
        AuthCredentials(login_id="zoey", password="12345")
    with pytest.raises(ValidationError):
        AuthCredentials(login_id="zo ey", password="123456")


def test_login_id_has_database_unique_indexes() -> None:
    assert User.__table__.c.login_id.unique
    normalized_index = next(
        index
        for index in User.__table__.indexes
        if index.name == "uq_users_login_id_normalized"
    )
    assert normalized_index.unique
    assert "choose another user ID" in DUPLICATE_LOGIN_MESSAGE


def test_register_sets_http_only_session_cookie(monkeypatch) -> None:
    user = SimpleNamespace(
        id=2,
        login_id="zoey",
        display_name="Zoey",
        created_at=datetime.now(UTC),
    )
    monkeypatch.setattr(auth_api, "create_account", lambda *_args, **_kwargs: user)
    monkeypatch.setattr(
        auth_api, "create_login_session", lambda *_args, **_kwargs: "session-token"
    )
    app.dependency_overrides[get_db] = lambda: object()
    try:
        with TestClient(app) as client:
            response = client.post(
                "/auth/register",
                json={"login_id": "Zoey", "password": "secret-password"},
            )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 201
    assert response.json()["login_id"] == "zoey"
    cookie = response.headers["set-cookie"].casefold()
    assert "daily_reading_session=session-token" in cookie
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    assert "password" not in response.text.casefold()


def test_password_change_verifies_current_password_and_rehashes() -> None:
    class Session:
        commits = 0

        def commit(self) -> None:
            self.commits += 1

    session = Session()
    user = SimpleNamespace(password_hash=hash_password("old-password"))

    change_account_password(
        session,  # type: ignore[arg-type]
        user=user,  # type: ignore[arg-type]
        current_password="old-password",
        new_password="new-password",
    )

    assert session.commits == 1
    assert verify_password("new-password", user.password_hash)
    assert not verify_password("old-password", user.password_hash)


def test_password_change_rejects_wrong_current_password() -> None:
    user = SimpleNamespace(password_hash=hash_password("old-password"))

    with pytest.raises(InvalidCurrentPasswordError):
        change_account_password(
            SimpleNamespace(commit=lambda: None),  # type: ignore[arg-type]
            user=user,  # type: ignore[arg-type]
            current_password="wrong-password",
            new_password="new-password",
        )
