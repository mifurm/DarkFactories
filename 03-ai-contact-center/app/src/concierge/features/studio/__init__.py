"""CC-24 Agent Studio UI - platform shell: settings, demo data, role switcher support, UI configuration."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from ...core.registry import EPIC_E, FeatureInfo

FEATURES = [
    FeatureInfo(
        "CC-24", "Agent Studio UI", EPIC_E, "P0", "/", "/api/studio",
        "Customer widget (chat + Call us), human-agent console, supervisor console, QA workbench, KB admin, eval harness, analytics, WFM and settings - one accessible, responsive React SPA.",
    ),
]  # fmt: skip

router = APIRouter(prefix="/api/studio", tags=["studio (CC-24)"])


@router.get("/settings")
async def settings(request: Request) -> dict[str, Any]:
    svc = request.app.state.services
    s = svc.settings
    cfg = await svc.configs.active() if svc.configs else None
    return {
        "meta": {
            "mode": s.mode,
            "region": s.region,
            "build_id": s.build_id,
            "repository": svc.repo.kind,
            "llm": svc.llm.name,
            "auth_mode": s.auth_mode,
            "deployments": {k: v for k, v in s.deployments.items() if v},
            "daily_budget_usd": s.daily_budget_usd,
        },
        "seed": {"status": svc.seed_state.get("status"), "steps": svc.seed_state.get("steps", {})},
        "policy": cfg.policy if cfg else {},
        "retention": {"transcripts_days": 365, "transcripts_without_recording_consent_days": 30, "audit_days": 400},
    }
