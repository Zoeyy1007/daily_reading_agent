from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.config import Settings, get_settings
from app.db.models import User
from app.db.session import get_db
from app.schemas.auth import (
    AuthCredentials,
    AuthUserRead,
    PasswordChange,
    ReadingSettingsRead,
    ReadingSettingsUpdate,
)
from app.services.auth_service import (
    AccountExistsError,
    InvalidCurrentPasswordError,
    authenticate_account,
    change_account_password,
    create_account,
    create_login_session,
    revoke_login_session,
)

router = APIRouter(prefix="/auth", tags=["authentication"])
DBSession = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]


def _set_session_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=token,
        max_age=settings.auth_session_days * 24 * 60 * 60,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite="lax",
        path="/",
    )


@router.post("/register", response_model=AuthUserRead, status_code=status.HTTP_201_CREATED)
def register(
    payload: AuthCredentials,
    response: Response,
    session: DBSession,
) -> User:
    settings = get_settings()
    try:
        user = create_account(
            session,
            login_id=payload.login_id,
            password=payload.password.get_secret_value(),
            legacy_user_id=settings.default_user_id,
            daily_list_length=settings.daily_article_target,
            expected_reading_minutes_per_article=(
                settings.expected_reading_minutes_per_article
            ),
        )
    except AccountExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    token = create_login_session(
        session, user_id=user.id, lifetime_days=settings.auth_session_days
    )
    _set_session_cookie(response, token, settings)
    return user


@router.post("/login", response_model=AuthUserRead)
def login(
    payload: AuthCredentials,
    response: Response,
    session: DBSession,
) -> User:
    settings = get_settings()
    user = authenticate_account(
        session,
        login_id=payload.login_id,
        password=payload.password.get_secret_value(),
    )
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid user ID or password")
    token = create_login_session(
        session, user_id=user.id, lifetime_days=settings.auth_session_days
    )
    _set_session_cookie(response, token, settings)
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response, session: DBSession) -> None:
    settings = get_settings()
    revoke_login_session(session, request.cookies.get(settings.auth_cookie_name))
    response.delete_cookie(
        key=settings.auth_cookie_name,
        path="/",
        secure=settings.auth_cookie_secure,
        httponly=True,
        samesite="lax",
    )


@router.get("/me", response_model=AuthUserRead)
def me(user: CurrentUser) -> User:
    return user


@router.patch("/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    payload: PasswordChange,
    session: DBSession,
    user: CurrentUser,
) -> None:
    try:
        change_account_password(
            session,
            user=user,
            current_password=payload.current_password.get_secret_value(),
            new_password=payload.new_password.get_secret_value(),
        )
    except InvalidCurrentPasswordError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _reading_settings(user: User) -> ReadingSettingsRead:
    return ReadingSettingsRead(
        daily_list_length=user.daily_list_length,
        expected_reading_minutes_per_article=(
            user.expected_reading_minutes_per_article
        ),
        total_daily_reading_minutes=(
            user.daily_list_length * user.expected_reading_minutes_per_article
        ),
    )


@router.get("/reading-settings", response_model=ReadingSettingsRead)
def get_reading_settings(user: CurrentUser) -> ReadingSettingsRead:
    return _reading_settings(user)


@router.patch("/reading-settings", response_model=ReadingSettingsRead)
def update_reading_settings(
    payload: ReadingSettingsUpdate,
    session: DBSession,
    user: CurrentUser,
) -> ReadingSettingsRead:
    user.daily_list_length = payload.daily_list_length
    user.expected_reading_minutes_per_article = (
        payload.expected_reading_minutes_per_article
    )
    session.commit()
    session.refresh(user)
    return _reading_settings(user)
