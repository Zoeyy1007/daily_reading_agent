import base64
import hashlib
import hmac
import secrets
import unicodedata
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.db.models import AuthSession, User


SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 32


class AccountExistsError(ValueError):
    pass


class InvalidCurrentPasswordError(ValueError):
    pass


DUPLICATE_LOGIN_MESSAGE = (
    "That user ID is already in use. Please choose another user ID."
)


def normalize_login_id(login_id: str) -> str:
    return unicodedata.normalize("NFKC", login_id.strip()).casefold()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    derived = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=SCRYPT_DKLEN,
        maxmem=64 * 1024 * 1024,
    )
    return "scrypt${}${}${}${}${}".format(
        SCRYPT_N,
        SCRYPT_R,
        SCRYPT_P,
        base64.urlsafe_b64encode(salt).decode("ascii"),
        base64.urlsafe_b64encode(derived).decode("ascii"),
    )


_DUMMY_PASSWORD_HASH = hash_password("not-a-real-account-password")


def verify_password(password: str, encoded_hash: str | None) -> bool:
    if not encoded_hash:
        return False
    try:
        algorithm, n, r, p, encoded_salt, encoded_derived = encoded_hash.split("$", 5)
        if algorithm != "scrypt":
            return False
        if (int(n), int(r), int(p)) != (SCRYPT_N, SCRYPT_R, SCRYPT_P):
            return False
        salt = base64.urlsafe_b64decode(encoded_salt.encode("ascii"))
        expected = base64.urlsafe_b64decode(encoded_derived.encode("ascii"))
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=SCRYPT_N,
            r=SCRYPT_R,
            p=SCRYPT_P,
            dklen=len(expected),
            maxmem=64 * 1024 * 1024,
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def create_account(
    session: Session,
    *,
    login_id: str,
    password: str,
    legacy_user_id: int | None = None,
    daily_list_length: int = 5,
    expected_reading_minutes_per_article: int = 6,
) -> User:
    normalized = normalize_login_id(login_id)
    if session.scalar(select(User.id).where(User.login_id == normalized)) is not None:
        raise AccountExistsError(DUPLICATE_LOGIN_MESSAGE)
    if legacy_user_id is not None:
        legacy_user = session.scalar(
            select(User).where(User.id == legacy_user_id).with_for_update()
        )
        if (
            legacy_user is not None
            and legacy_user.login_id is None
            and legacy_user.password_hash is None
        ):
            legacy_user.login_id = normalized
            legacy_user.display_name = login_id.strip()
            legacy_user.password_hash = hash_password(password)
            legacy_user.is_active = True
            legacy_user.daily_list_length = daily_list_length
            legacy_user.expected_reading_minutes_per_article = (
                expected_reading_minutes_per_article
            )
            try:
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                raise AccountExistsError(DUPLICATE_LOGIN_MESSAGE) from exc
            session.refresh(legacy_user)
            return legacy_user
    user = User(
        login_id=normalized,
        display_name=login_id.strip(),
        password_hash=hash_password(password),
        is_active=True,
        daily_list_length=daily_list_length,
        expected_reading_minutes_per_article=(
            expected_reading_minutes_per_article
        ),
    )
    session.add(user)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise AccountExistsError(DUPLICATE_LOGIN_MESSAGE) from exc
    session.refresh(user)
    return user


def authenticate_account(
    session: Session, *, login_id: str, password: str
) -> User | None:
    normalized = normalize_login_id(login_id)
    user = session.scalar(select(User).where(User.login_id == normalized))
    if user is None:
        verify_password(password, _DUMMY_PASSWORD_HASH)
        return None
    if not user.is_active:
        return None
    return user if verify_password(password, user.password_hash) else None


def change_account_password(
    session: Session,
    *,
    user: User,
    current_password: str,
    new_password: str,
) -> None:
    if not verify_password(current_password, user.password_hash):
        raise InvalidCurrentPasswordError("The current password is incorrect")
    user.password_hash = hash_password(new_password)
    session.commit()


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_login_session(
    session: Session, *, user_id: int, lifetime_days: int
) -> str:
    now = datetime.now(UTC)
    session.execute(delete(AuthSession).where(AuthSession.expires_at <= now))
    token = secrets.token_urlsafe(32)
    session.add(
        AuthSession(
            user_id=user_id,
            token_hash=_token_hash(token),
            expires_at=now + timedelta(days=lifetime_days),
        )
    )
    session.commit()
    return token


def user_for_session_token(session: Session, token: str | None) -> User | None:
    if not token:
        return None
    auth_session = session.scalar(
        select(AuthSession)
        .where(AuthSession.token_hash == _token_hash(token))
        .options(selectinload(AuthSession.user))
    )
    if auth_session is None:
        return None
    if auth_session.expires_at <= datetime.now(UTC) or not auth_session.user.is_active:
        session.delete(auth_session)
        session.commit()
        return None
    return auth_session.user


def revoke_login_session(session: Session, token: str | None) -> None:
    if token:
        session.execute(
            delete(AuthSession).where(AuthSession.token_hash == _token_hash(token))
        )
        session.commit()
