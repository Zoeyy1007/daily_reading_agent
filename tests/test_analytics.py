from types import SimpleNamespace
from uuid import UUID

from fastapi.testclient import TestClient

import app.api.analytics as analytics_api
from app.api.dependencies import get_current_user
from app.db.session import get_db
from app.main import app
from app.schemas.analytics import UsageEventCreate, UsageSummaryRead
from app.services.analytics_service import hash_visitor_id


VISITOR_ID = UUID("12345678-1234-5678-1234-567812345678")


def test_usage_event_schema_accepts_only_normalized_routes() -> None:
    event = UsageEventCreate(
        visitor_id=VISITOR_ID,
        event_type="page_view",
        path="/article",
    )

    assert event.path == "/article"
    assert hash_visitor_id(VISITOR_ID) != str(VISITOR_ID)
    assert len(hash_visitor_id(VISITOR_ID)) == 64


def test_usage_summary_is_restricted_to_configured_admin() -> None:
    app.dependency_overrides[get_db] = lambda: object()
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        login_id="friend"
    )
    try:
        with TestClient(app) as client:
            response = client.get("/analytics/summary")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403


def test_usage_summary_returns_aggregate_to_admin(monkeypatch) -> None:
    summary = UsageSummaryRead(
        days=30,
        total_page_views=12,
        unique_visitors=4,
        signed_in_users=2,
        daily=[],
    )
    monkeypatch.setattr(analytics_api, "usage_summary", lambda *_args, **_kwargs: summary)
    app.dependency_overrides[get_db] = lambda: object()
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(login_id="18")
    try:
        with TestClient(app) as client:
            response = client.get("/analytics/summary?days=30")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["unique_visitors"] == 4
    assert response.json()["signed_in_users"] == 2
