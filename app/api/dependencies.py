from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import User
from app.db.session import get_db
from app.services.auth_service import user_for_session_token


DBSession = Annotated[Session, Depends(get_db)]


def get_current_user(request: Request, session: DBSession) -> User:
    token = request.cookies.get(get_settings().auth_cookie_name)
    user = user_for_session_token(session, token)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    return user


def get_optional_current_user(request: Request, session: DBSession) -> User | None:
    token = request.cookies.get(get_settings().auth_cookie_name)
    return user_for_session_token(session, token)


def get_current_user_id(user: Annotated[User, Depends(get_current_user)]) -> int:
    return user.id
