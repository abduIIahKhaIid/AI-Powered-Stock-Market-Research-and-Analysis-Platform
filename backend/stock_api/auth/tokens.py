"""Signed access tokens (JWT, HS256) for signed-in users (SCRUM-40)."""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache

import jwt

from ..config import Settings

logger = logging.getLogger("stock_api.auth")

ALGORITHM = "HS256"
ISSUER = "stock-research-api"
MIN_SECRET_LENGTH = 32


class TokenError(ValueError):
    pass


class AuthConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class Identity:
    user_id: str
    username: str


@lru_cache
def _random_secret() -> str:
    logger.warning(
        "JWT_SECRET is not set: using a random secret, so sign-ins end when the API restarts. "
        'Set JWT_SECRET in .env (python -c "import secrets; print(secrets.token_urlsafe(48))").'
    )
    return secrets.token_urlsafe(48)


def signing_secret(settings: Settings) -> str:
    secret = settings.jwt_secret.strip()
    if secret:
        if len(secret) < MIN_SECRET_LENGTH:
            raise AuthConfigError(f"JWT_SECRET must be at least {MIN_SECRET_LENGTH} characters.")
        return secret
    if settings.app_env == "production":
        raise AuthConfigError("JWT_SECRET must be set in production.")
    return _random_secret()


def issue_token(settings: Settings, user_id: str, username: str) -> tuple[str, int]:
    """A token for the user and its lifetime in seconds."""
    now = datetime.now(UTC)
    lifetime = int(settings.jwt_ttl_minutes * 60)
    claims = {
        "sub": user_id,
        "name": username,
        "iss": ISSUER,
        "iat": now,
        "exp": now + timedelta(seconds=lifetime),
    }
    return jwt.encode(claims, signing_secret(settings), algorithm=ALGORITHM), lifetime


def read_token(settings: Settings, token: str) -> Identity:
    try:
        claims = jwt.decode(
            token,
            signing_secret(settings),
            algorithms=[ALGORITHM],
            issuer=ISSUER,
            options={"require": ["sub", "exp", "iat", "iss"]},
        )
    except jwt.ExpiredSignatureError:
        raise TokenError("Your session has expired. Sign in again.") from None
    except jwt.InvalidTokenError:
        raise TokenError("Invalid sign-in token. Sign in again.") from None
    return Identity(str(claims["sub"]), str(claims.get("name", "")))
