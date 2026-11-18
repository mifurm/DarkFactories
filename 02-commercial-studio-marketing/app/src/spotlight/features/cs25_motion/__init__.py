"""CS-25 Cinematic motion (generative video) — the GPU worker's status and warm-up.

The approved storyboard keyframe becomes the first frame of an AI-generated clip with real subject and camera motion (an open image-to-video model, Wan 2.2
TI2V-5B, self-hosted on Azure Container Apps serverless GPU in the customer's own tenant; see ``spotlight.motion``). The compositor then edits the clips exactly
like stills. Where the capability shows up in the spot API: ``POST /api/campaigns/{id}/spot/render`` takes ``quality: preview | cinematic`` and
``GET /api/campaigns/{id}/spot/estimate`` prices a cinematic render before it runs (both live in CS-08 — the estimate has to be registered ahead of
``/spot/{spot_id}``); this module owns the worker-level endpoints below."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from ...deps import mutate_limit, spend_limit, svc
from ...motion.orchestrator import motion_status, request_warmup
from ...registry import Feature
from ...roles import Actor, require

router = APIRouter(prefix="/api/motion", tags=["CS-25 Cinematic motion"])


@router.get("/status")
async def status(request: Request) -> dict[str, Any]:
    """``{mode, available, model, license, worker: {state: cold|warming|ready, age_s, queue_depth}, price_per_gpu_second, est_cold_start_s, max_clip_s}`` (+ revision, host, steps, high, reason)."""
    return await motion_status(svc(request))


@router.post("/warmup", status_code=202, dependencies=[Depends(mutate_limit), Depends(spend_limit)])
async def warmup(request: Request, actor: Actor = Depends(require("generate"))) -> dict[str, Any]:
    """Wake the GPU worker (a no-op when it is ready or already warming). The cold start is accounted against the daily budget and refused (402) when it would not fit."""
    s = svc(request)
    res = await request_warmup(s)
    body = await motion_status(s)
    body["warmup"] = {"requested": res["requested"], "est_cost_usd": round(res["cost_usd"], 5), "est_seconds": res["seconds"]}
    return body


FEATURE = Feature(
    id="CS-25",
    summary="Cinematic motion: the approved keyframe becomes the first frame of a real AI-generated clip (open image-to-video model self-hosted on serverless GPU, scale-to-zero, keyless, tenant-local); worker status + warm-up, priced estimate, per-shot cache / budget guard / content-safety check / still fallback, provenance of the model.",
    router=router,
)
