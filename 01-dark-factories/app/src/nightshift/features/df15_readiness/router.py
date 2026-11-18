from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from nightshift.core.deps import get_plant
from nightshift.features.df15_readiness import assess as A
from nightshift.features.df23_rbac.rbac import Identity, require
from nightshift.plant.runtime import PlantRuntime

router = APIRouter(prefix="/api/readiness", tags=["DF-15 readiness"])


class AssessBody(BaseModel):
    answers: dict[str, float] = Field(default_factory=dict, max_length=60)
    target: float = Field(default=75.0, ge=10, le=100)


@router.get("/questions")
async def questions(pr: PlantRuntime = Depends(get_plant)) -> dict[str, Any]:
    return {
        "scale": A.SCALE,
        "dimensions": {k: {"label": v[0], "weight": v[1]} for k, v in A.DIMENSIONS.items()},
        "questions": A.QUESTIONS,
        "measured": A.measure(pr),
        "levels": [{"min": m, "name": n, "description": d} for m, n, d in A.LEVELS],
    }


@router.post("/assess")
async def run(
    body: AssessBody,
    pr: PlantRuntime = Depends(get_plant),
    ident: Identity = Depends(require("assess", "readiness.assess")),
) -> dict[str, Any]:
    bad = [k for k, v in body.answers.items() if k not in {q["id"] for q in A.QUESTIONS} or not 0 <= v <= 4]
    if bad:
        raise HTTPException(422, f"invalid answers: {bad[:5]}")
    res = A.assess(pr, body.answers, body.target)
    pr.extras["readiness"] = res
    pr.rt.writer.enqueue(
        "jobs",
        {
            "id": f"readiness-{pr.plant_id}-{pr.plant.t}",
            "pk": "readiness",
            "overall": res["overall"],
            "level": res["level"],
            "dimensions": {k: v["score"] for k, v in res["dimensions"].items()},
            "plant": pr.plant_id,
        },
    )
    return res


@router.get("/latest")
async def latest(pr: PlantRuntime = Depends(get_plant)) -> dict[str, Any]:
    return pr.extras.get("readiness") or A.assess(pr, {})


@router.get("/export")
async def export(format: str = "md", pr: PlantRuntime = Depends(get_plant)):
    res = pr.extras.get("readiness") or A.assess(pr, {})
    if format == "md":
        return PlainTextResponse(A.to_markdown(res), media_type="text/markdown")
    if format == "csv":
        return PlainTextResponse(A.to_csv(res), media_type="text/csv")
    if format == "json":
        return res
    raise HTTPException(422, "format must be md|csv|json")
