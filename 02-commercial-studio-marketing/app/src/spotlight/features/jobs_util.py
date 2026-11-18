"""Pipeline orchestration helpers shared by features: background jobs with optional wait."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import Request

from ..core.jobs import JobContext, render_job
from ..deps import svc
from ..errors import AppError
from ..i18n import DEFAULT, has


async def submit_job(
    request: Request,
    kind: str,
    fn: Callable[[JobContext], Awaitable[dict[str, Any] | None]],
    campaign_id: str | None,
    title: str,
    feature: str,
    wait: bool = False,
    timeout: float = 170.0,  # noqa: ASYNC109 - upper bound for wait=true (scripts/tests); jobs themselves are not cancelled
    title_params: dict[str, Any] | None = None,
    lane: str | None = None,
) -> dict[str, Any]:
    """Run long work as a persisted job. ``wait=true`` blocks until it finishes (scripts/tests); the UI streams progress.

    ``title`` is a ``job.title.*`` catalog key (rendered in the viewer's language, with ``title_params``) or, for ad-hoc jobs, plain text.
    The job itself has no time limit (a cinematic render takes ~25 minutes while the GPU worker wakes up); only the ``wait=true`` caller stops waiting after ``timeout``.
    ``lane="motion"`` runs it in the GPU lane, so it does not occupy the general job slots."""
    s = svc(request)
    if has(title, DEFAULT):
        job = await s.jobs.submit(kind, fn, campaign_id=campaign_id, feature=feature, title_key=title, title_params=title_params, lane=lane)
    else:
        job = await s.jobs.submit(kind, fn, campaign_id=campaign_id, title=title, feature=feature, lane=lane)
    if not wait:
        return render_job(job)
    try:
        job = await s.jobs.wait(job["id"], timeout)
    except TimeoutError:
        return render_job(await s.jobs.require(job["id"]))
    if job["status"] == "failed":
        code = job.get("error_code") or "job_failed"
        status = 402 if "budget" in code or code == "premium_requires_approval" else (422 if code in {"guardian_blocked", "validation_failed", "prompt_injection"} else 500)
        raise AppError(job.get("error") or "job failed", code=code, status=status, hint=job.get("error_hint"), details={"job_id": job["id"]}, params=job.get("error_params"), key=job.get("error_key") or None)
    return render_job(job)
