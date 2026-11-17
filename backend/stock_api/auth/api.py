"""POST /auth/register, POST /auth/login, GET /auth/me and GET /auth/config (SCRUM-40)."""

from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from ..config import Settings, get_settings
from .deps import CurrentUser, client_address, enforce_limit, get_rate_limiter, get_user_store
from .ratelimit import RateLimiter
from .tokens import AuthConfigError, issue_token
from .users import InvalidCredentials, UserExists, UserStore, validate_new_account

router = APIRouter(prefix="/auth", tags=["auth"])

SettingsDep = Annotated[Settings, Depends(get_settings)]
Users = Annotated[UserStore, Depends(get_user_store)]
Limiter = Annotated[RateLimiter, Depends(get_rate_limiter)]


class Credentials(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class Registration(Credentials):
    invite_code: str | None = Field(default=None, max_length=256)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    username: str


class AuthConfig(BaseModel):
    enabled: bool
    signup: bool
    invite_required: bool


class Me(BaseModel):
    username: str
    auth_enabled: bool


def _token(settings: Settings, user_id: str, username: str) -> TokenResponse:
    try:
        token, lifetime = issue_token(settings, user_id, username)
    except AuthConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    return TokenResponse(access_token=token, expires_in=lifetime, username=username)


def _require_enabled(settings: Settings) -> None:
    if not settings.auth_enabled:
        raise HTTPException(status_code=404, detail="Sign-in is turned off on this server.")


@router.get("/config", response_model=AuthConfig)
def auth_config(settings: SettingsDep) -> AuthConfig:
    return AuthConfig(
        enabled=settings.auth_enabled,
        signup=settings.auth_allow_signup,
        invite_required=bool(settings.auth_signup_code),
    )


@router.post("/register", response_model=TokenResponse, status_code=201)
def register(
    body: Registration,
    request: Request,
    response: Response,
    settings: SettingsDep,
    users: Users,
    limiter: Limiter,
) -> TokenResponse:
    _require_enabled(settings)
    enforce_limit(settings, limiter, "auth", f"ip:{client_address(request)}", response)
    if not settings.auth_allow_signup:
        raise HTTPException(status_code=403, detail="New accounts are not being accepted.")
    code = settings.auth_signup_code
    if code and not hmac.compare_digest((body.invite_code or "").encode(), code.encode()):
        raise HTTPException(status_code=403, detail="The invite code is not valid.")
    username = body.username.strip()
    problem = validate_new_account(username, body.password)
    if problem:
        raise HTTPException(status_code=422, detail=problem)
    try:
        user = users.create(username, body.password)
    except UserExists:
        raise HTTPException(status_code=409, detail="That username is taken.") from None
    return _token(settings, user.id, user.username)


@router.post("/login", response_model=TokenResponse)
def login(
    body: Credentials,
    request: Request,
    response: Response,
    settings: SettingsDep,
    users: Users,
    limiter: Limiter,
) -> TokenResponse:
    _require_enabled(settings)
    enforce_limit(settings, limiter, "auth", f"ip:{client_address(request)}", response)
    try:
        user = users.authenticate(body.username.strip(), body.password)
    except InvalidCredentials:
        raise HTTPException(status_code=401, detail="Wrong username or password.") from None
    return _token(settings, user.id, user.username)


@router.get("/me", response_model=Me)
def me(user: CurrentUser, settings: SettingsDep) -> Me:
    return Me(username=user.username, auth_enabled=settings.auth_enabled)
