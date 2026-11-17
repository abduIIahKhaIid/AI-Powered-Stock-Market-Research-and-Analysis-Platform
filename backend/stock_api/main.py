"""FastAPI entry point."""

from typing import Annotated, Literal

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from starlette.types import ASGIApp, Receive, Scope, Send

from stock_api import health
from stock_api.approvals_api import router as approvals_router
from stock_api.auth import rate_limited
from stock_api.auth.api import router as auth_router
from stock_api.charts import router as charts_router
from stock_api.chat import router as chat_router
from stock_api.config import Settings, get_settings
from stock_api.job_events_api import router as job_events_router
from stock_api.jobs_api import router as jobs_router

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Conversational research assistant for NASDAQ-listed stocks.",
    docs_url="/docs" if settings.api_docs_enabled else None,
    redoc_url=None,
    openapi_url="/openapi.json" if settings.api_docs_enabled else None,
)


class ForwardedPrefix:
    """Nginx serves the API under /api and strips the prefix; X-Forwarded-Prefix tells the
    docs page where the OpenAPI schema is. Routing is unaffected."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            for name, value in scope.get("headers", []):
                if name == b"x-forwarded-prefix":
                    prefix = value.decode("latin-1").rstrip("/")
                    if prefix.startswith("/") and prefix.replace("/", "").isalnum():
                        scope = {**scope, "root_path": prefix}
                    break
        await self.app(scope, receive, send)


app.add_middleware(ForwardedPrefix)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Everything except /health and /auth needs a signed-in user and counts against their
# rate limit (SCRUM-40).
signed_in = [Depends(rate_limited("api"))]
app.include_router(auth_router)
app.include_router(chat_router, dependencies=[Depends(rate_limited("chat"))])
app.include_router(charts_router, dependencies=signed_in)
app.include_router(approvals_router, dependencies=signed_in)
app.include_router(jobs_router, dependencies=signed_in)
app.include_router(job_events_router, dependencies=signed_in)


class LiveResponse(BaseModel):
    status: Literal["ok"]


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    environment: str
    services: dict[str, str]


@app.get("/health/live", response_model=LiveResponse, tags=["health"])
async def live() -> LiveResponse:
    """Liveness probe: the API process is up. Does not touch dependencies."""
    return LiveResponse(status="ok")


@app.get("/health", response_model=HealthResponse, tags=["health"])
async def health_check(settings: Annotated[Settings, Depends(get_settings)]) -> HealthResponse:
    """Readiness: reports each dependency. Always 200 while the API itself is running."""
    services = await health.collect_service_status(settings)
    status: Literal["ok", "degraded"] = (
        "ok" if all(value == "ok" for value in services.values()) else "degraded"
    )
    return HealthResponse(
        status=status,
        version=settings.app_version,
        environment=settings.app_env,
        services=services,
    )
