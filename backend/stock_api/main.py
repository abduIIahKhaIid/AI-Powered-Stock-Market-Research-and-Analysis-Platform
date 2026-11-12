"""FastAPI entry point."""

from typing import Annotated, Literal

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from stock_api import health
from stock_api.approvals_api import router as approvals_router
from stock_api.charts import router as charts_router
from stock_api.chat import router as chat_router
from stock_api.config import Settings, get_settings
from stock_api.jobs_api import router as jobs_router

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Conversational research assistant for NASDAQ-listed stocks.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(chat_router)
app.include_router(charts_router)
app.include_router(approvals_router)
app.include_router(jobs_router)


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
