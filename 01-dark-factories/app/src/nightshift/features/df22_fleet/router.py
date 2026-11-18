from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from nightshift.core.deps import get_rt
from nightshift.features.df23_rbac.rbac import Identity, require

router = APIRouter(prefix="/api/fleet", tags=["DF-22 fleet"])


class LearnBody(BaseModel):
    plant: str
    asset: str
    note: str = ""


class AdoptBody(BaseModel):
    plant: str


@router.get("/plants")
async def plants(rt=Depends(get_rt)) -> dict[str, Any]:
    return {"plants": [p.summary() for p in rt.fleet.plants.values()], "totals": rt.fleet.fleet_totals()}


@router.get("/compare")
async def compare(rt=Depends(get_rt)) -> dict[str, Any]:
    return rt.fleet.compare()


@router.get("/playbooks")
async def playbooks(rt=Depends(get_rt)) -> dict[str, Any]:
    return {
        "playbooks": rt.fleet.playbooks,
        "libraries": {pid: p.library.public() for pid, p in rt.fleet.plants.items()},
    }


@router.post("/playbooks/learn")
async def learn(
    body: LearnBody, rt=Depends(get_rt), ident: Identity = Depends(require("fleet_share", "fleet.learn"))
) -> dict[str, Any]:
    try:
        return rt.fleet.learn_signature(body.plant, body.asset.upper(), body.note)
    except KeyError:
        raise HTTPException(404, "unknown plant") from None
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/playbooks/{playbook_id}/adopt")
async def adopt(
    playbook_id: str,
    body: AdoptBody,
    rt=Depends(get_rt),
    ident: Identity = Depends(require("fleet_share", "fleet.adopt")),
) -> dict[str, Any]:
    try:
        return rt.fleet.adopt(playbook_id, body.plant)
    except KeyError:
        raise HTTPException(404, "unknown playbook or plant") from None
