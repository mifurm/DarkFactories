from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from nightshift.core.deps import get_plant, get_rt
from nightshift.core.llm import narrate
from nightshift.features.df18_rca import rca as R
from nightshift.plant.runtime import PlantRuntime

router = APIRouter(prefix="/api/rca", tags=["DF-18 rca"])


class NarrateBody(BaseModel):
    asset: str | None = None


@router.get("/analyze")
async def analyze(
    asset: str | None = None, window_min: int = 720, pr: PlantRuntime = Depends(get_plant)
) -> dict[str, Any]:
    return R.analyze(pr, asset.upper() if asset else None, max(60, min(window_min, 1440)))


@router.get("/pareto")
async def pareto(pr: PlantRuntime = Depends(get_plant)) -> list[dict[str, Any]]:
    return R.pareto(pr)


@router.get("/graph")
async def graph(window_min: int = 720, pr: PlantRuntime = Depends(get_plant)) -> dict[str, Any]:
    return R.causal_graph(pr, max(60, min(window_min, 1440)))


@router.post("/narrate")
async def narrate_rca(body: NarrateBody, pr: PlantRuntime = Depends(get_plant), rt=Depends(get_rt)) -> dict[str, Any]:
    res = R.analyze(pr, body.asset.upper() if body.asset else None)
    facts = {
        "asset": res["asset"],
        "symptom": res["symptom"],
        "hypotheses": [
            {k: h[k] for k in ("rank", "cause", "confidence", "explanation")} for h in res["hypotheses"][:4]
        ],
        "pareto": res["pareto"][:5],
    }
    nar = await narrate(
        rt.llm,
        "rca",
        facts,
        "Narrate the root-cause analysis for a plant manager in 4 sentences: the loss, the most likely cause with its evidence, and what to check next.",
        lambda f: (
            f"Most likely cause for {f['asset']}: {f['hypotheses'][0]['cause']} ({f['hypotheses'][0]['explanation']})"
            if f["hypotheses"]
            else f"No correlated upstream events found for {f['asset']}; the largest loss is {f['pareto'][0]['cause'] if f['pareto'] else 'n/a'}."
        ),
        max_tokens=450,
    )
    return {**nar.public(), "asset": res["asset"], "top": res["hypotheses"][:1]}
