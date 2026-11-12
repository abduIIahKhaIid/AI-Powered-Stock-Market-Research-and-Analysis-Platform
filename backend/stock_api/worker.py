"""Celery application for background analysis jobs (SCRUM-32).

Start a worker:  celery -A stock_api.worker worker -Q analysis,sandbox,ingest --loglevel=info
Start Beat:      celery -A stock_api.worker beat --loglevel=info
"""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from stock_api.config import get_settings
from stock_api.jobs import Job, JobKind, get_job_store, get_registry
from stock_api.jobs.runner import execute

settings = get_settings()

QUEUES = ("analysis", "sandbox", "ingest")

celery_app = Celery("stock_platform", broker=settings.redis_url, backend=settings.redis_url)

celery_app.conf.update(
    task_default_queue="analysis",
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_track_started=True,
    result_expires=60 * 60 * 24,
    timezone="UTC",
    beat_schedule={
        # Keep the NASDAQ symbol directory fresh every morning (UTC), before US market open.
        "refresh-symbol-directory": {
            "task": "jobs.scheduled",
            "schedule": crontab(hour=6, minute=7),
            "args": ("refresh_directory",),
            "options": {"queue": "ingest"},
        },
    },
)


@celery_app.task(name="system.ping")
def ping() -> str:
    """Smoke-test task used to confirm the worker is consuming jobs."""
    return "pong"


@celery_app.task(name="jobs.run")
def run_job(job_id: str) -> str:
    return execute(job_id, get_job_store(), get_registry()).status


@celery_app.task(name="jobs.scheduled")
def run_scheduled(kind: str) -> str:
    job = get_job_store().create(kind, {})
    return execute(job.id, get_job_store(), get_registry()).status


def enqueue(job: Job, kind: JobKind) -> None:
    """Send a job to its queue; the job id is also the Celery task id."""
    celery_app.send_task(
        "jobs.run",
        args=[job.id],
        task_id=job.id,
        queue=kind.queue,
        soft_time_limit=kind.soft_limit,
        time_limit=kind.hard_limit,
    )


def revoke(job_id: str) -> None:
    celery_app.control.revoke(job_id)
