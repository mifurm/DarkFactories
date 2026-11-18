from typing import Any

from fastapi import APIRouter, Depends

from nightshift.core.deps import get_plant
from nightshift.plant.runtime import PlantRuntime

router = APIRouter(prefix="/api/materials", tags=["DF-08 materials"])


@router.get("/summary")
async def summary(pr: PlantRuntime = Depends(get_plant)) -> dict[str, Any]:
    return pr.materials.summary(pr.world())


@router.get("/requests")
async def requests(pr: PlantRuntime = Depends(get_plant)) -> dict[str, Any]:
    p = pr.plant
    return {
        "amr_requests": [{"since_min": p.t - r[0], "cell": r[1]} for r in p.amr_requests],
        "priority": p.amr_priority,
    }
