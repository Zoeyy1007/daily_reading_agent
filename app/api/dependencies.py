from typing import Annotated

from fastapi import Header

from app.config import get_settings


def get_current_user_id(
    x_user_id: Annotated[int | None, Header(ge=1)] = None,
) -> int:
    # This header is a temporary development identity, not authentication.
    # A deployed version can replace this dependency with an auth provider
    # without changing the service layer's user-scoped interfaces.
    return x_user_id if x_user_id is not None else get_settings().default_user_id
