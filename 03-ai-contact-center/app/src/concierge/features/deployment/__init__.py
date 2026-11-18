"""CC-23 IaC & deployment - deployment facts for the Deployment page (Bicep/azd, remote build, smoke results, teardown)."""

from __future__ import annotations

import os
import time
from typing import Any

from fastapi import APIRouter, Request

from ...core.registry import EPIC_E, FeatureInfo

FEATURES = [
    FeatureInfo(
        "CC-23", "IaC & deployment", EPIC_E, "P0", "/deployment", "/api/deployment",
        "Bicep + azd (remote ACR build), keyless managed identity, governance tags on RG and every resource, smoke tests and documented teardown.",
    ),
]  # fmt: skip

router = APIRouter(prefix="/api/deployment", tags=["deployment (CC-23)"])

_smoke: dict[str, Any] = {}


@router.get("/info")
async def info(request: Request) -> dict[str, Any]:
    svc = request.app.state.services
    s = svc.settings
    env = os.environ
    return {
        "mode": s.mode,
        "build_id": s.build_id,
        "region": s.region,
        "resource_group": s.resource_group or None,
        "tags": {
            "SecurityControl": "Ignore",
            "SecurityExemption": "StorageAccountKeyAccess",
            "project": "SwarmAI",
            "concept": "contactcenter",
            "owner": "michalfu",
            "environment": "demo",
        },
        "resources": [
            {"type": "Container App (WebSocket-capable ingress)", "role": "FastAPI + realtime relay + SPA", "name": env.get("CONTAINER_APP_NAME", "ca-concierge-*")},
            {"type": "Container Registry (Basic)", "role": "remote image build (az acr build / azd)", "name": env.get("ACR_NAME", "acrcc*")},
            {"type": "Cosmos DB for NoSQL (serverless)", "role": "conversations, KB index, analytics, audit", "name": "cosmos-cc-* (Entra RBAC, local auth disabled)"},
            {"type": "AI Services (Foundry)", "role": "chat, realtime, embeddings, Speech, Language, Content Safety", "name": "ais-cc-* (local auth disabled)"},
            {"type": "Storage (LRS)", "role": "KB sources, transcript exports", "name": "stcc* (Entra only, shared key disabled)"},
            {"type": "Application Insights + Log Analytics", "role": "traces, metrics, logs (1 GB/day cap)", "name": "appi-cc-* / law-cc-*"},
            {"type": "User-assigned managed identity", "role": "AcrPull, Cosmos data role, Blob, OpenAI/Cognitive Services User, Metrics Publisher", "name": "id-cc-*"},
        ],
        "commands": {
            "provision": "azd provision --no-prompt",
            "deploy": "azd deploy --no-prompt",
            "all_in_one": "azd up --no-prompt",
            "smoke": "python scripts/smoke_test.py --base-url <url>",
            "teardown": "azd down --purge --force  (or: az group delete -n rg-swarmai-contactcenter --yes)",
        },
        "smoke_results": _smoke or None,
        "uptime_s": round(time.time() - __import__("concierge.core.config", fromlist=["x"]).STARTED_AT, 1),
    }
