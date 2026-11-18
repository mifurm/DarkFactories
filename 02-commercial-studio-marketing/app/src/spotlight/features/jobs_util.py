"""Pipeline orchestration helpers shared by features: background jobs with optional wait."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import Request

from ..core.jobs import JobContext
from ..deps import svc
from ..errors import AppError


async def submit_job(
    request: Request,
    kind: str,
    fn: Callable[[JobContext], Awaitable[dict[str, Any] | None]],
    campaign_id: str | None,
    title: str,
    feature: str,
    wait: bool = False,
    timeout: float = 170.0,  # noqa: ASYNC109 - upper bound for wait=true (scripts/tests); jobs themselves are not cancelled
) -> dict[str, Any]:
    """Run long work as a persisted job. ``wait=true`` blocks until it finishes (scripts/tests); the UI streams progress."""
    s = svc(request)
    job = await s.jobs.submit(kind, fn, campaign_id=campaign_id, title=title, feature=feature)
    if not wait:
        return job
    try:
        job = await s.jobs.wait(job["id"], timeout)
    except TimeoutError:
        return await s.jobs.require(job["id"])
    if job["status"] == "failed":
        code = job.get("error_code") or "job_failed"
        status = 402 if "budget" in code or code == "premium_requires_approval" else (422 if code in {"guardian_blocked", "validation_failed", "prompt_injection"} else 500)
        raise AppError(job.get("error") or "job failed", code=code, status=status, hint=job.get("error_hint"), details={"job_id": job["id"]})
    return job
