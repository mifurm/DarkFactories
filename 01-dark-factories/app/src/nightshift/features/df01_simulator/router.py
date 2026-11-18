from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from nightshift.core.deps import get_plant, get_rt
from nightshift.features.df23_rbac.rbac import Identity, require
from nightshift.plant.runtime import PlantRuntime
from nightshift.sim.config import load_assumptions
from nightshift.sim.faults import SCENARIO_INFO
from nightshift.sim.plant import CONTROL_ACTIONS, ActionRejected

router = APIRouter(prefix="/api/sim", tags=["DF-01 simulator"])
admin = APIRouter(prefix="/api/admin", tags=["platform"])


class ControlBody(BaseModel):
    command: str = Field(pattern="^(pause|resume|speed|step)$")
    value: float = 0.0


class FaultBody(BaseModel):
    kind: str
    asset: str | None = None
    material: str | None = None
    zone: str | None = None
    sku: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)


class ActionBody(BaseModel):
    action: dict[str, Any]


@router.get("/state")
async def state(pr: PlantRuntime = Depends(get_plant)) -> dict[str, Any]:
    return pr.snapshot(full=True)


@router.get("/assets")
async def assets(pr: PlantRuntime = Depends(get_plant)) -> list[dict[str, Any]]:
    return [pr.plant.asset_public(s.id) for s in pr.cfg.assets]


@router.get("/assets/{asset_id}")
async def asset(asset_id: str, pr: PlantRuntime = Depends(get_plant)) -> dict[str, Any]:
    if asset_id.upper() not in pr.plant.assets:
        raise HTTPException(404, "unknown asset")
    out = pr.plant.asset_public(asset_id.upper())
    out["series"] = {
        m: [None if v != v else round(float(v), 3) for v in pr.plant.store.series(asset_id.upper(), m, 120)]
        for m in pr.cfg.asset(asset_id.upper()).sensors
    }
    out["queue_ops"] = [{"order": o, "op": i} for o, i in pr.plant.assets[asset_id.upper()].queue[:10]]
    return out


@router.get("/orders")
async def orders(pr: PlantRuntime = Depends(get_plant)) -> list[dict[str, Any]]:
    p = pr.plant
    return [
        {
            "id": o.id,
            "sku": o.sku,
            "qty": o.qty,
            "priority": o.priority,
            "rush": o.rush,
            "deferrable": o.deferrable,
            "due_in_min": o.due - p.t,
            "ops": [
                {
                    "stage": op.stage,
                    "done": round(op.done),
                    "assigned": op.assigned,
                    "finished": op.finished_t is not None,
                }
                for op in o.ops
            ],
        }
        for o in p.open_orders()
    ]


@router.get("/config")
async def config() -> dict[str, Any]:
    return {
        "assumptions": load_assumptions(),
        "note": "Every number is an assumption of the simulator; validate with customer data.",
    }


@router.get("/catalog")
async def catalog(pr: PlantRuntime = Depends(get_plant)) -> dict[str, Any]:
    return pr.catalog()


@router.post("/control")
async def control(
    body: ControlBody,
    pr: PlantRuntime = Depends(get_plant),
    ident: Identity = Depends(require("sim_control", "sim.control")),
) -> dict[str, Any]:
    if body.command == "pause":
        pr.paused = True
    elif body.command == "resume":
        pr.paused = False
    elif body.command == "speed":
        pr.set_speed(body.value)
    else:
        pr.step_minutes(int(body.value or 1))
    return {
        "paused": pr.paused,
        "speed": pr.speed,
        "t": pr.plant.t,
        "sim_time": pr.plant.now.isoformat(timespec="minutes"),
    }


@router.post("/faults")
async def faults(
    body: FaultBody,
    pr: PlantRuntime = Depends(get_plant),
    ident: Identity = Depends(require("sim_control", "sim.inject_fault")),
) -> dict[str, Any]:
    kw = {
        k: v
        for k, v in {"asset": body.asset, "material": body.material, "zone": body.zone, "sku": body.sku}.items()
        if v
    }
    try:
        return pr.inject(body.kind, **kw, **body.params)
    except ActionRejected as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/scenario/{name}")
async def scenario(
    name: str, pr: PlantRuntime = Depends(get_plant), ident: Identity = Depends(require("sim_control", "sim.scenario"))
) -> dict[str, Any]:
    if name not in SCENARIO_INFO:
        raise HTTPException(404, f"unknown scenario; choose from {sorted(SCENARIO_INFO)}")
    return pr.run_scenario(name)


@router.post("/action")
async def action(
    body: ActionBody,
    pr: PlantRuntime = Depends(get_plant),
    ident: Identity = Depends(require("sim_control", "sim.manual_action")),
) -> dict[str, Any]:
    if body.action.get("kind") not in CONTROL_ACTIONS:
        raise HTTPException(422, f"unknown action; allowed: {list(CONTROL_ACTIONS)}")
    try:
        return pr.direct_action(body.action, ident.subject)
    except ActionRejected as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/snapshot")
async def snapshot(
    pr: PlantRuntime = Depends(get_plant), ident: Identity = Depends(require("sim_control", "sim.snapshot"))
) -> dict[str, Any]:
    snaps = pr.extras.setdefault("snapshots", {})
    sid = f"snap-{pr.plant.t}"
    snaps[sid] = pr.plant.snapshot()
    while len(snaps) > 5:
        snaps.pop(next(iter(snaps)))
    return {"id": sid, "t": pr.plant.t, "available": list(snaps)}


@router.post("/restore/{snap_id}")
async def restore(
    snap_id: str,
    pr: PlantRuntime = Depends(get_plant),
    ident: Identity = Depends(require("sim_control", "sim.restore")),
) -> dict[str, Any]:
    snap = pr.extras.get("snapshots", {}).get(snap_id)
    if snap is None:
        raise HTTPException(404, "unknown snapshot")
    pr.plant.restore(snap)
    pr.twin.plant = pr.plant
    pr.supervisor.plant = pr.plant
    pr.supervisor.executor.plant = pr.plant
    return {"restored": snap_id, "t": pr.plant.t}


@router.get("/events")
async def events(limit: int = 100, pr: PlantRuntime = Depends(get_plant)) -> list[dict[str, Any]]:
    return pr.event_log[-max(1, min(limit, 500)) :]


@admin.post("/reseed")
async def reseed(
    request: Request, plant: str | None = None, ident: Identity = Depends(require("reseed", "admin.reseed"))
) -> dict[str, Any]:
    rt = get_rt(request)
    targets = [rt.fleet.get(plant)] if plant else list(rt.fleet.plants.values())
    for pr in targets:
        await pr.reset()
        pr.ledger.append(
            "system", f"Demo state reset requested by {ident.role}", agent=ident.subject, outcome="reseed", sim_t=0
        )
    return {"reseeded": [p.plant_id for p in targets]}


extra_routers = [admin]
