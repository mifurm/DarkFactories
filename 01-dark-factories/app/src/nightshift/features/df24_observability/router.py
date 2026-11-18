from typing import Any

from fastapi import APIRouter, Depends

from nightshift.core.deps import get_rt

router = APIRouter(prefix="/api/observability", tags=["DF-24 observability"])


@router.get("/metrics")
async def metrics(rt=Depends(get_rt)) -> dict[str, Any]:
    snap = rt.metrics.snapshot()
    agents = {}
    for pr in rt.fleet.plants.values():
        for a in pr.agents:
            row = agents.setdefault(
                a.name,
                {"cycles": 0, "proposals": 0, "executed": 0, "vetoed": 0, "errors": 0, "p50_ms": 0.0, "p95_ms": 0.0},
            )
            info = a.info()
            for k in ("cycles", "proposals", "executed", "vetoed", "errors"):
                row[k] += info["stats"].get(k, 0)
            row["p50_ms"] = max(row["p50_ms"], info["p50_ms"])
            row["p95_ms"] = max(row["p95_ms"], info["p95_ms"])
    return {
        **snap,
        "agent_decisions": agents,
        "sse_subscribers": rt.hub.subscribers,
        "events_published": rt.hub.published,
        "otel": {
            "app_insights": bool(rt.settings.appinsights_connection_string),
            "auth": "managed identity (Entra)",
            "mode": rt.settings.mode,
        },
    }


@router.get("/finops")
async def finops(rt=Depends(get_rt)) -> dict[str, Any]:
    u = rt.usage.snapshot()
    return {
        "usage": u,
        "guard": {
            "daily_budget_usd": u["daily_budget_usd"],
            "remaining_usd": u["remaining_usd"],
            "blocked": u["budget_blocked"],
            "fails_closed": True,
            "behaviour": "AI features fall back to deterministic output (no spend) when the cap is reached",
        },
        "hint": "Estimated from token counts x planning-assumption prices; compare with Azure Cost Management.",
    }


@router.get("/health")
async def health(rt=Depends(get_rt)) -> dict[str, Any]:
    ready = await rt.readiness()
    return {
        "ready": ready,
        "write_behind": rt.writer.stats(),
        "plants": {
            pid: {
                "t": p.plant.t,
                "paused": p.paused,
                "speed": p.speed,
                "ledger": len(p.ledger),
                "ledger_ok": p.ledger.verify()["ok"],
                "agents_enabled": sum(a.enabled for a in p.agents),
            }
            for pid, p in rt.fleet.plants.items()
        },
    }
