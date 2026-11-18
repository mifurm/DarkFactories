import io
from typing import Any

import numpy as np
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from nightshift.core.deps import get_plant, get_rt
from nightshift.features.df06_quality.vision import LABELS, ReviewItem, classify_with_model, generate_part_image
from nightshift.features.df23_rbac.rbac import Identity, require
from nightshift.plant.runtime import PlantRuntime

router = APIRouter(prefix="/api/quality", tags=["DF-06 quality"])
REVIEW_THRESHOLD = 0.8


class BatchBody(BaseModel):
    n: int = Field(default=8, ge=1, le=16)
    seed: int = Field(default=11, ge=0, le=10**6)


class ReviewBody(BaseModel):
    label: str


@router.get("/summary")
async def summary(pr: PlantRuntime = Depends(get_plant)) -> dict[str, Any]:
    w = pr.world()
    return {"assets": pr.quality.summary(w), "interventions": pr.quality.interventions[-20:], "t": pr.plant.t}


@router.get("/spc/{asset}")
async def spc(asset: str, pr: PlantRuntime = Depends(get_plant)) -> dict[str, Any]:
    if asset.upper() not in pr.plant.assets:
        raise HTTPException(404, "unknown asset")
    return pr.quality.chart(pr.world(), asset.upper())


def _stats(pr: PlantRuntime) -> dict[str, Any]:
    log = pr.quality.vision_log
    scored = [r for r in log if r.get("truth")]
    agree = sum(1 for r in scored if r["truth"] == r["predicted"])
    return {
        "inspected": len(log),
        "agreement": (agree / len(scored)) if scored else None,
        "pending_review": sum(1 for r in pr.quality.review_queue if r.status == "pending"),
        "sources": sorted({r["source"] for r in log}),
    }


@router.post("/vision/batch")
async def vision_batch(body: BatchBody, pr: PlantRuntime = Depends(get_plant), rt=Depends(get_rt)) -> dict[str, Any]:
    """Generate synthetic part images (PIL) with known defects, classify them (Azure OpenAI multimodal; classical CV offline), queue low-confidence calls."""
    rng = np.random.default_rng(body.seed)
    out = []
    for i in range(body.n):
        truth = str(rng.choice(LABELS, p=[0.4, 0.2, 0.2, 0.2]))
        png = generate_part_image(int(rng.integers(0, 10**6)), None if truth == "ok" else truth)
        res = await classify_with_model(rt.llm, png)
        key = f"vision/{pr.plant_id}/{pr.plant.t}-{i}.png"
        try:
            await rt.blobs.put("vision", key.split("/", 1)[1], png, "image/png")
        except Exception:
            pass
        item = ReviewItem(
            id=f"IMG-{pr.plant.t}-{i}",
            truth=truth,
            predicted=res["label"],
            confidence=float(res["confidence"]),
            source=res["source"],
            image_key=key,
            created_t=pr.plant.t,
            findings=[f for f in res.get("findings", []) if f][:3],
        )
        pr.extras.setdefault("vision_png", {})[item.id] = png
        if res["confidence"] < REVIEW_THRESHOLD:
            pr.quality.review_queue.append(item)
        pr.quality.vision_log.append(
            {
                "id": item.id,
                "truth": truth,
                "predicted": res["label"],
                "confidence": res["confidence"],
                "source": res["source"],
            }
        )
        out.append(
            {
                **item.public(),
                "truth": truth,
                "agree": truth == res["label"],
                "needs_review": res["confidence"] < REVIEW_THRESHOLD,
            }
        )
    del pr.quality.vision_log[:-200]
    cache = pr.extras.get("vision_png", {})
    while len(cache) > 60:
        cache.pop(next(iter(cache)))
    return {"results": out, "stats": _stats(pr), "threshold": REVIEW_THRESHOLD}


@router.get("/vision/queue")
async def queue(pr: PlantRuntime = Depends(get_plant)) -> dict[str, Any]:
    return {"items": [i.public() for i in pr.quality.review_queue[-30:][::-1]], "stats": _stats(pr)}


@router.get("/vision/image/{item_id}")
async def image(item_id: str, pr: PlantRuntime = Depends(get_plant)) -> Response:
    png = pr.extras.get("vision_png", {}).get(item_id)
    if png is None:
        raise HTTPException(404, "image not available")
    return Response(content=png, media_type="image/png", headers={"Cache-Control": "private, max-age=300"})


@router.post("/vision/review/{item_id}")
async def review(
    item_id: str,
    body: ReviewBody,
    pr: PlantRuntime = Depends(get_plant),
    ident: Identity = Depends(require("approve", "quality.vision_review")),
) -> dict[str, Any]:
    if body.label not in LABELS:
        raise HTTPException(422, f"label must be one of {LABELS}")
    item = next((i for i in pr.quality.review_queue if i.id == item_id), None)
    if item is None:
        raise HTTPException(404, "unknown review item")
    item.human_label = body.label
    item.status = "confirmed" if body.label == item.predicted else "corrected"
    pr.ledger.append(
        "override",
        f"{ident.role} reviewed {item.id}: model said {item.predicted} ({item.confidence:.2f}), human says {body.label}",
        agent=ident.subject,
        outcome=item.status,
        sim_t=pr.plant.t,
        payload={"truth": item.truth},
    )
    return item.public()


@router.get("/vision/stats")
async def vision_stats(pr: PlantRuntime = Depends(get_plant)) -> dict[str, Any]:
    return _stats(pr)


def _unused() -> None:  # keeps io import for future uploads
    io.BytesIO()
