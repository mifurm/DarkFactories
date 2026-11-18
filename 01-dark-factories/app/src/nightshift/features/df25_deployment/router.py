import os
import time
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from nightshift.core.deps import get_rt
from nightshift.features.df23_rbac.rbac import Identity, require

router = APIRouter(prefix="/api/deployment", tags=["DF-25 deployment"])
_cache: dict[str, tuple[float, Any]] = {}


class SmokeBody(BaseModel):
    results: list[dict[str, Any]] = Field(max_length=80)
    base_url: str = ""
    duration_s: float = 0.0


async def _arm(rt, path: str) -> Any:  # pragma: no cover - needs Azure
    cred = rt.credential
    tok = await cred.get_token("https://management.azure.com/.default")
    async with httpx.AsyncClient(timeout=10.0) as c:
        r = await c.get(f"https://management.azure.com{path}", headers={"Authorization": f"Bearer {tok.token}"})
        r.raise_for_status()
        return r.json()


@router.get("/info")
async def info(rt=Depends(get_rt)) -> dict[str, Any]:
    s = rt.settings
    return {
        "mode": s.mode,
        "region": s.region,
        "subscription": s.subscription_id[:8] + "..." if s.subscription_id else "",
        "resource_group": s.resource_group,
        "container_app": os.getenv("CONTAINER_APP_NAME", ""),
        "revision": os.getenv("CONTAINER_APP_REVISION", ""),
        "endpoints": {"cosmos": s.cosmos_endpoint, "storage": s.storage_account_url, "openai": s.openai_endpoint},
        "deployments": {"chat": s.chat_deployment, "reasoning": s.reasoning_deployment},
        "iac": {
            "tool": "Bicep + azd",
            "scope": "subscription",
            "modules": ["monitoring", "identity", "data", "ai", "app"],
            "remote_build": "ACR Tasks (azd docker.remoteBuild)",
            "commands": {
                "provision": "azd provision --no-prompt",
                "deploy": "azd deploy --no-prompt",
                "all": "azd up --no-prompt",
                "teardown": "azd down --purge --force",
            },
        },
        "security": {
            "identity": "user-assigned managed identity; no keys or connection strings",
            "cosmos_local_auth": "disabled",
            "ai_local_auth": "disabled",
            "storage_shared_key": "disabled",
            "scale": "1 replica (in-process simulation state)",
        },
    }


@router.get("/resources")
async def resources(rt=Depends(get_rt)) -> dict[str, Any]:
    s = rt.settings
    if not (s.is_azure and s.subscription_id and s.resource_group and rt.credential is not None):
        return {"available": False, "reason": "not running in Azure mode", "resources": []}
    hit = _cache.get("res")
    if hit and time.time() - hit[0] < 60:
        return hit[1]
    try:
        base = f"/subscriptions/{s.subscription_id}/resourceGroups/{s.resource_group}"
        rg = await _arm(rt, f"{base}?api-version=2021-04-01")
        res = await _arm(rt, f"{base}/resources?api-version=2021-04-01")
    except Exception as exc:
        return {
            "available": False,
            "reason": f"ARM read failed ({type(exc).__name__}); grant Reader to the app identity",
            "resources": [],
        }
    out = {
        "available": True,
        "resource_group": rg.get("name"),
        "location": rg.get("location"),
        "tags": rg.get("tags", {}),
        "resources": [
            {
                "name": r["name"],
                "type": r["type"].split("/", 1)[-1] if r["type"].startswith("Microsoft.") else r["type"],
                "provider": r["type"].split("/")[0],
                "location": r.get("location"),
                "sku": (r.get("sku") or {}).get("name"),
                "tags": {k: v for k, v in (r.get("tags") or {}).items() if k.startswith("Security")},
            }
            for r in res.get("value", [])
        ],
    }
    _cache["res"] = (time.time(), out)
    return out


@router.get("/smoke")
async def smoke(rt=Depends(get_rt)) -> dict[str, Any]:
    return rt.extras.get("smoke") or {
        "results": [],
        "note": "no smoke test has reported yet (run scripts/smoke_test.py --base-url <url> --report)",
    }


@router.post("/smoke")
async def post_smoke(
    body: SmokeBody, rt=Depends(get_rt), ident: Identity = Depends(require("ingest", "deployment.smoke"))
) -> dict[str, Any]:
    if not body.results:
        raise HTTPException(422, "no results")
    passed = sum(1 for r in body.results if r.get("status") == "PASS")
    rt.extras["smoke"] = {
        "results": body.results,
        "passed": passed,
        "failed": len(body.results) - passed,
        "base_url": body.base_url[:200],
        "duration_s": body.duration_s,
        "reported_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    return {"stored": len(body.results), "passed": passed}
