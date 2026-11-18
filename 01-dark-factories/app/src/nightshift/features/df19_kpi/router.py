from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from nightshift.core.deps import get_plant, get_rt
from nightshift.features.df19_kpi.engine import KpiEngine
from nightshift.plant.runtime import PlantRuntime

router = APIRouter(prefix="/api/kpi", tags=["DF-19 kpi"])


def _clean(o: Any) -> Any:
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_clean(v) for v in o]
    if isinstance(o, float) and o != o:
        return None
    return o


@router.get("")
async def kpis(window_hours: float = 8, pr: PlantRuntime = Depends(get_plant)) -> dict[str, Any]:
    if not 0.25 <= window_hours <= 168:
        raise HTTPException(422, "window_hours must be between 0.25 and 168")
    return _clean(KpiEngine.compute(pr.plant, int(window_hours * 60)))


@router.get("/trend")
async def trend(points: int = 24, pr: PlantRuntime = Depends(get_plant)) -> list[dict[str, Any]]:
    return _clean(KpiEngine.trend(pr.plant, max(2, min(points, 96))))


@router.get("/snapshots")
async def snapshots(limit: int = 24, pr: PlantRuntime = Depends(get_plant), rt=Depends(get_rt)) -> dict[str, Any]:
    """Hourly KPI snapshots persisted to Cosmos DB (container 'kpi')."""
    rows = await rt.repo.query("kpi", pk=pr.plant_id, order_by="t", desc=True, limit=max(1, min(limit, 200)))
    return {
        "persisted": len(rows),
        "backend": rt.repo.name,
        "items": [
            {
                "t": r["t"],
                "sim_time": r["sim_time"],
                "oee": r["plant_kpi"].get("oee"),
                "throughput_uph": r["plant_kpi"].get("throughput_uph"),
                "impact_eur": r["impact_eur"],
            }
            for r in rows
        ],
    }
