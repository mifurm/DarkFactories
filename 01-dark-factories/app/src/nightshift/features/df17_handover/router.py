from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel, Field

from nightshift.core.deps import get_plant, get_rt
from nightshift.features.df17_handover import report as R
from nightshift.features.df23_rbac.rbac import Identity, require
from nightshift.plant.runtime import PlantRuntime

router = APIRouter(prefix="/api/handover", tags=["DF-17 handover"])


class GenBody(BaseModel):
    window_hours: float = Field(default=8, ge=1, le=24)
    use_llm: bool = True


@router.post("/generate")
async def generate(
    body: GenBody,
    pr: PlantRuntime = Depends(get_plant),
    rt=Depends(get_rt),
    ident: Identity = Depends(require("report", "handover.generate")),
) -> dict[str, Any]:
    rep = await R.generate(rt, pr, int(body.window_hours * 60), body.use_llm)
    return {k: v for k, v in rep.items() if k != "html"}


@router.get("/reports")
async def reports(pr: PlantRuntime = Depends(get_plant)) -> list[dict[str, Any]]:
    return [
        {
            "id": r["id"],
            "shift": r["shift"],
            "sim_time": r["sim_time"],
            "source": r["source"],
            "summary": r["summary"][:240],
        }
        for r in pr.reports[::-1]
    ]


@router.get("/reports/{report_id}")
async def get_report(report_id: str, format: str = "json", pr: PlantRuntime = Depends(get_plant)):
    r = next((x for x in pr.reports if x["id"] == report_id), None)
    if r is None:
        raise HTTPException(404, "unknown report")
    if format == "md":
        return PlainTextResponse(r["markdown"], media_type="text/markdown")
    if format == "html":
        return HTMLResponse(r["html"])
    return {k: v for k, v in r.items() if k != "html"}


@router.get("/schedule")
async def schedule(pr: PlantRuntime = Depends(get_plant)) -> dict[str, Any]:
    p = pr.plant
    nxt = min((s - p.minute_of_day()) % 1440 for s in (6 * 60, 14 * 60, 22 * 60))
    return {
        "boundaries": ["06:00", "14:00", "22:00"],
        "next_in_sim_min": nxt,
        "pending_auto_reports": pr.pending_reports,
        "generated": len(pr.reports),
    }
