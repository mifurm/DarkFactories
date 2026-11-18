from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from nightshift.core.deps import get_plant, get_rt
from nightshift.core.llm import narrate
from nightshift.features.df23_rbac.rbac import Identity, require
from nightshift.plant.runtime import PlantRuntime

router = APIRouter(prefix="/api/ledger", tags=["DF-14 ledger"])


class ExplainBody(BaseModel):
    seq: int


@router.get("")
async def query(
    asset: str | None = None,
    agent: str | None = None,
    kind: str | None = None,
    outcome: str | None = None,
    corr: str | None = None,
    q: str | None = None,
    decision_class: str | None = None,
    since_t: int | None = None,
    until_t: int | None = None,
    limit: int = 100,
    offset: int = 0,
    desc: bool = True,
    pr: PlantRuntime = Depends(get_plant),
) -> dict[str, Any]:
    return pr.ledger.query(
        asset=asset,
        agent=agent,
        kind=kind,
        outcome=outcome,
        corr=corr,
        q=q,
        decision_class=decision_class,
        since_t=since_t,
        until_t=until_t,
        limit=max(1, min(limit, 500)),
        offset=max(0, offset),
        desc=desc,
    )


@router.get("/verify")
async def verify_chain(pr: PlantRuntime = Depends(get_plant)) -> dict[str, Any]:
    return pr.ledger.verify()


@router.get("/stats")
async def stats(pr: PlantRuntime = Depends(get_plant)) -> dict[str, Any]:
    return pr.ledger.stats()


@router.get("/export")
async def export(
    asset: str | None = None,
    agent: str | None = None,
    kind: str | None = None,
    pr: PlantRuntime = Depends(get_plant),
    ident: Identity = Depends(require("ledger_export", "ledger.export")),
) -> PlainTextResponse:
    filters = {k: v for k, v in {"asset": asset, "agent": agent, "kind": kind}.items() if v}
    return PlainTextResponse(
        pr.ledger.export_jsonl(**filters),
        media_type="application/x-ndjson",
        headers={"Content-Disposition": f'attachment; filename="ledger-{pr.plant_id}.jsonl"'},
    )


@router.get("/{seq}")
async def get_entry(seq: int, pr: PlantRuntime = Depends(get_plant)) -> dict[str, Any]:
    e = pr.ledger.get(seq)
    if e is None:
        raise HTTPException(404, "entry not in memory window")
    chain = pr.ledger.query(corr=e["corr"], limit=60, desc=False)["items"] if e["corr"] else [e]
    return {"entry": e, "chain": chain}


@router.post("/explain")
async def explain(body: ExplainBody, pr: PlantRuntime = Depends(get_plant), rt=Depends(get_rt)) -> dict[str, Any]:
    e = pr.ledger.get(body.seq)
    if e is None:
        raise HTTPException(404, "entry not found")
    chain = pr.ledger.query(corr=e["corr"], limit=30, desc=False)["items"] if e["corr"] else [e]
    facts = {
        "entry": {k: e[k] for k in ("seq", "kind", "agent", "summary", "rationale", "outcome", "counterfactual")},
        "chain": [{k: c[k] for k in ("seq", "kind", "agent", "summary", "outcome")} for c in chain],
    }
    nar = await narrate(
        rt.llm,
        "ledger.explain",
        facts,
        "Explain this decision to an auditor in 3 sentences: what triggered it, what alternatives were considered, who decided and what happened.",
        lambda f: f"{f['entry']['summary']}. {f['entry']['rationale']}"[:500],
        max_tokens=400,
    )
    return {"seq": body.seq, **nar.public()}
