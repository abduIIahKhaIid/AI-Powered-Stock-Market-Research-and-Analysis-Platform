"""Celery application for background analysis jobs.

Start a worker:  celery -A stock_api.worker worker -Q analysis,sandbox,ingest --loglevel=info
Start Beat:      celery -A stock_api.worker beat --loglevel=info
"""

from celery import Celery

from stock_api.config import get_settings

settings = get_settings()

celery_app = Celery("stock_platform", broker=settings.redis_url, backend=settings.redis_url)

celery_app.conf.update(
    task_default_queue="analysis",
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_track_started=True,
    result_expires=60 * 60 * 24,
    timezone="UTC",
    # Scheduled jobs (daily data refresh, etc.) are added in later stories.
    beat_schedule={},
)


@celery_app.task(name="system.ping")
def ping() -> str:
    """Smoke-test task used to confirm the worker is consuming jobs."""
    return "pong"
