from typing import Any

from fastapi import APIRouter, Depends

from nightshift.core.deps import get_plant
from nightshift.features.df19_kpi.engine import KpiEngine
from nightshift.plant.runtime import PlantRuntime

router = APIRouter(prefix="/api/energy", tags=["DF-09 energy"])


@router.get("/summary")
async def summary(pr: PlantRuntime = Depends(get_plant)) -> dict[str, Any]:
    out = pr.energy.summary(pr.world())
    k = KpiEngine.compute(pr.plant, 480)["plant_kpi"]
    out["kpi"] = {
        m: k[m] for m in ("energy_kwh", "kwh_per_unit", "co2_kg", "co2_per_unit_kg", "energy_cost_eur", "peak_kw")
    }
    return out


@router.get("/trend")
async def trend(pr: PlantRuntime = Depends(get_plant)) -> list[dict[str, Any]]:
    s = pr.plant.store
    kw = s.series("plant", "power_kw", 360)
    pr_ = s.series("plant", "tariff_eur_kwh", 360)
    co = s.series("plant", "carbon_g_kwh", 360)
    t0 = pr.plant.t - len(kw)
    return [
        {"t": t0 + i, "kw": round(float(kw[i]), 1), "price": round(float(pr_[i]), 4), "carbon": round(float(co[i]))}
        for i in range(0, len(kw), 5)
    ]
