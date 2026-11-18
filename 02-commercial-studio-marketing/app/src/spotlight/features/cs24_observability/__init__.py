"""CS-24 Observability, security & IaC — runtime status, route latency, guardrail counters."""

from __future__ import annotations

from fastapi import APIRouter, Request

from ...deps import svc
from ...i18n import t
from ...registry import Feature

router = APIRouter(prefix="/api/ops", tags=["CS-24 Observability"])


@router.get("/status")
async def status(request: Request) -> dict:
    s = svc(request)
    st = s.settings
    jobs = await s.repo.query("jobs", limit=500)
    counts = {k: sum(1 for j in jobs if j["status"] == k) for k in ("queued", "running", "succeeded", "failed", "cancelled")}
    return {
        "mode": st.mode,
        "version": st.version,
        "build_id": st.build_id,
        "region": st.azure_region,
        "instance": st.instance_id,
        "uptime_s": round(__import__("time").time() - s.started_at, 1),
        "backends": {
            "repository": s.repo.mode,
            "blob_storage": s.blobs.mode,
            "llm": s.llm.mode,
            "image": s.image.mode,
            "speech": s.speech.mode,
            "content_safety": s.safety.mode,
        },
        "telemetry_enabled": bool(getattr(request.app.state, "telemetry_enabled", False)),
        "budget": await s.guard.caps(),
        "guard_refusals": s.guard.refusals,
        "limits": {
            "rate_per_ip_mutate_per_min": st.rate_per_ip_mutate_per_min,
            "rate_per_ip_spend_per_min": st.rate_per_ip_spend_per_min,
            "rate_global_spend_per_min": st.rate_global_spend_per_min,
            "max_body_bytes": st.max_body_bytes,
            "max_concurrent_jobs": st.max_concurrent_jobs,
        },
        "rate_limit_rejections": dict(s.limiter.rejections),
        "cache": s.cache.stats(),
        "jobs": counts,
        "security": {
            "auth": t("ops.auth"),
            "headers": ["CSP", "HSTS", "X-Content-Type-Options", "X-Frame-Options", "Referrer-Policy"],
            "cors": t("ops.cors"),
            "container_user": t("ops.container_user"),
        },
    }


@router.get("/metrics")
async def metrics(request: Request) -> dict:
    s = svc(request)
    routes = [
        {"route": k, "count": int(v["count"]), "errors": int(v["errors"]), "avg_ms": round(v["total_ms"] / max(v["count"], 1), 1), "max_ms": round(v["max_ms"], 1)}
        for k, v in s.route_stats.items()
    ]
    routes.sort(key=lambda r: -r["count"])
    return {"routes": routes, "ai_calls_by_kind": dict(s.meter.calls_by_kind), "refusals": s.guard.refusals}


FEATURE = Feature(
    id="CS-24",
    summary="Health/ready probes, OpenTelemetry -> App Insights, AI usage meter, rate limits, budget caps, Bicep/azd, smoke tests.",
    router=router,
)
