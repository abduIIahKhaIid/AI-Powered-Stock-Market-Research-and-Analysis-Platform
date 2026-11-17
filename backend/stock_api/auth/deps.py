"""FastAPI dependencies: the signed-in user and per-user rate limits (SCRUM-40)."""

from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ..config import Settings, get_settings
from .ratelimit import RateLimiter, RedisRateLimiter
from .tokens import AuthConfigError, Identity, TokenError, read_token
from .users import PostgresUserStore, UserStore

# Who is asking when sign-in is turned off (AUTH_ENABLED=false): one shared local user.
LOCAL_USER = Identity(user_id="", username="local")

_bearer = HTTPBearer(auto_error=False)


@lru_cache
def get_user_store() -> UserStore:
    return PostgresUserStore(get_settings().database_url)


@lru_cache
def get_rate_limiter() -> RateLimiter:
    return RedisRateLimiter(get_settings().redis_url)


def _unauthorized(message: str) -> HTTPException:
    return HTTPException(
        status_code=401, detail=message, headers={"WWW-Authenticate": 'Bearer realm="api"'}
    )


def current_user(
    settings: Annotated[Settings, Depends(get_settings)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> Identity:
    if not settings.auth_enabled:
        return LOCAL_USER
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _unauthorized("Sign in to use the assistant.")
    try:
        return read_token(settings, credentials.credentials)
    except TokenError as exc:
        raise _unauthorized(str(exc)) from None
    except AuthConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None


CurrentUser = Annotated[Identity, Depends(current_user)]


def owner_of(user: Identity) -> str | None:
    """The owner id stored on jobs and approvals; None when sign-in is off."""
    return user.user_id or None


def client_address(request: Request) -> str:
    # Uvicorn runs with --proxy-headers behind Nginx, so this is the browser's address.
    return request.client.host if request.client else "unknown"


def _limit_for(settings: Settings, bucket: str) -> int:
    return {
        "chat": settings.rate_limit_chat_per_minute,
        "jobs": settings.rate_limit_jobs_per_minute,
        "auth": settings.rate_limit_auth_per_minute,
    }.get(bucket, settings.rate_limit_api_per_minute)


def enforce_limit(
    settings: Settings, limiter: RateLimiter, bucket: str, subject: str, response: Response
) -> None:
    if not settings.rate_limit_enabled:
        return
    decision = limiter.hit(bucket, subject, _limit_for(settings, bucket))
    if not decision.allowed:
        raise HTTPException(
            status_code=429,
            detail=f"Too many requests. Try again in {decision.retry_after} seconds.",
            headers={"Retry-After": str(decision.retry_after)},
        )
    response.headers["X-RateLimit-Limit"] = str(decision.limit)
    response.headers["X-RateLimit-Remaining"] = str(decision.remaining)


def rate_limited(bucket: str) -> Callable[..., Identity]:
    """Requires a signed-in user and counts the request against their limit for `bucket`."""

    def dependency(
        request: Request,
        response: Response,
        user: CurrentUser,
        settings: Annotated[Settings, Depends(get_settings)],
        limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
    ) -> Identity:
        subject = f"user:{user.user_id}" if user.user_id else f"ip:{client_address(request)}"
        enforce_limit(settings, limiter, bucket, subject, response)
        return user

    dependency.__name__ = f"rate_limited_{bucket}"
    return dependency
