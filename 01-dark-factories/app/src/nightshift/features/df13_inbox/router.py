from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from nightshift.core.deps import get_plant
from nightshift.features.df13_inbox.inbox import adaptive_card
from nightshift.features.df23_rbac.rbac import Identity, require
from nightshift.plant.runtime import PlantRuntime
from nightshift.sim.plant import ActionRejected

router = APIRouter(prefix="/api/inbox", tags=["DF-13 inbox"])


class ResolveBody(BaseModel):
    option: str = Field(pattern="^(approve|reject|defer)$")
    comment: str = Field(default="", max_length=300)


@router.get("")
async def list_items(status: str | None = None, pr: PlantRuntime = Depends(get_plant)) -> dict[str, Any]:
    t = pr.human_t()
    return {
        "items": [i.public(t) for i in pr.inbox.list(status)],
        "stats": pr.inbox.stats(t),
        "t": t,
        "teams": {"configured": pr.teams.configured, "sent": pr.teams.sent},
    }


@router.get("/{item_id}")
async def get_item(item_id: str, pr: PlantRuntime = Depends(get_plant)) -> dict[str, Any]:
    i = pr.inbox.get(item_id)
    if i is None:
        raise HTTPException(404, "unknown inbox item")
    return i.public(pr.human_t())


@router.post("/{item_id}/resolve")
async def resolve(
    item_id: str,
    body: ResolveBody,
    pr: PlantRuntime = Depends(get_plant),
    ident: Identity = Depends(require("approve", "inbox.resolve")),
) -> dict[str, Any]:
    try:
        out = pr.supervisor.resolve(item_id, body.option, f"{ident.role}:{ident.subject}", body.comment)
    except KeyError:
        raise HTTPException(404, "unknown inbox item") from None
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    except ActionRejected as exc:
        raise HTTPException(422, str(exc)) from exc
    i = pr.inbox.get(item_id)
    if i is not None:
        pr.rt.writer.enqueue("approvals", {"id": i.id, "pk": pr.plant_id, **i.public()})
    pr.hub.publish(f"{pr.plant_id}/agent", {"event": "inbox_resolved", "item": item_id, "option": body.option})
    return out


@router.get("/{item_id}/teams-card")
async def teams_card(item_id: str, pr: PlantRuntime = Depends(get_plant)) -> dict[str, Any]:
    i = pr.inbox.get(item_id)
    if i is None:
        raise HTTPException(404, "unknown inbox item")
    return adaptive_card(i)


@router.post("/{item_id}/notify")
async def notify(
    item_id: str, pr: PlantRuntime = Depends(get_plant), ident: Identity = Depends(require("approve", "inbox.notify"))
) -> dict[str, Any]:
    i = pr.inbox.get(item_id)
    if i is None:
        raise HTTPException(404, "unknown inbox item")
    res = await pr.teams.notify(i)
    return {k: v for k, v in res.items() if k != "card"} | {"configured": pr.teams.configured}
