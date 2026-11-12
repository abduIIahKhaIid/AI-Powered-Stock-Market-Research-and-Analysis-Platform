"""The message posted in the chat when a job finishes (SCRUM-33)."""

from __future__ import annotations

from typing import Any

from ..agent.context import DISCLAIMER
from .registry import JobKind
from .results import ResultStore, load_result
from .store import Job


def report_text(job: Job, kind: JobKind | None, results: ResultStore | None) -> str:
    title = kind.title if kind else job.kind
    if job.status == "cancelled":
        return f"The {title.lower()} was cancelled before it finished."
    if job.status == "failed":
        return f"The {title.lower()} did not finish: {job.error or 'unknown error'}"
    if kind is None or kind.report is None:
        return f"The {title.lower()} finished. {job.summary or ''}".strip()
    result: Any = job.result
    if job.result_path and results is not None:
        result = load_result(job.id, job.result, job.result_path, results)
    return kind.report(job.params, result)


def done_payload(job: Job, kind: JobKind | None, results: ResultStore | None) -> dict[str, Any]:
    return {
        "id": job.id,
        "kind": job.kind,
        "title": kind.title if kind else job.kind,
        "status": job.status,
        "summary": job.summary,
        "report": report_text(job, kind, results),
        "error": job.error,
        "files": job.files,
        "conversation_id": job.conversation_id,
        "disclaimer": DISCLAIMER,
    }
