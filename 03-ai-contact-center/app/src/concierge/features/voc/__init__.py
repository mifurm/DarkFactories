"""CC-12 Voice-of-customer analytics: topic discovery by embedding clustering, sentiment trends, contact-driver Pareto, repeat/churn signals,
emerging-issue alerts (anomaly detection with carrier attribution). Dashboards read stored aggregates (collection `voc`)."""

from __future__ import annotations

import json
import time
from typing import Any

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Request

from ...core import i18n
from ...core.rbac import Actor, require
from ...core.registry import EPIC_C, FeatureInfo
from ...engine import localize, synth, voc
from ...engine.history_seed import load_history, seed_history

FEATURES = [
    FeatureInfo(
        "CC-12", "Voice-of-customer analytics", EPIC_C, "P1", "/voc", "/api/voc",
        "Embedding clustering of conversation summaries into contact drivers, sentiment trends, Pareto by volume and cost, repeat-contact and churn-risk signals, and anomaly detection that surfaces emerging issues (e.g. damaged-on-delivery for one carrier) with evidence.",
    ),
]  # fmt: skip
SEED_ORDER = 60
VOC_VERSION = "v4"  # v4: reviewed Polish wording of the summaries / topic labels (pl2 slice); v3 also carried `summary_pl` in examples / alerts. A stored aggregate of an older version is recomputed once on start-up

router = APIRouter(prefix="/api/voc", tags=["voc (CC-12)"])


def _strip(d: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if k not in ("pk", "_ts", "ttl")}


async def label_clusters(svc: Any, result: dict[str, Any]) -> bool:
    """LLM-generated topic labels (falls back to c-TF-IDF terms when the model is unavailable or offline)."""
    if getattr(svc.llm, "deterministic", True):
        return False
    payload = [{"id": c["id"], "top_terms": c["terms"], "examples": [e["summary"][:140] for e in c["examples"][:3]]} for c in result["clusters"]]
    try:
        res = await svc.llm.chat(
            [
                {"role": "system", "content": 'You name customer-contact topic clusters for a home-retail contact center. Reply with JSON {"labels": {"<id>": "<2-5 word label>"}} covering every id. Labels must describe why customers contact us, in plain English.'},
                {"role": "user", "content": json.dumps(payload)},
            ],
            role="nano", max_tokens=700, reasoning_effort=None, json_mode=True, feature="voc_label",
        )  # fmt: skip
        labels = json.loads(res.text)["labels"]
    except Exception:
        return False
    for c in result["clusters"]:
        if str(c["id"]) in labels:
            c["label_terms"] = c["label"]
            c["label"] = str(labels[str(c["id"])])[:60]
    names = {c["id"]: c["label"] for c in result["clusters"]}
    for table in (result["pareto_volume"], result["pareto_cost"]):
        for row in table:
            row["label"] = names[row["id"]]
    for a in result["alerts"]:
        a["label"] = names.get(a["cluster"], a["label"])
    return True


async def compute(svc: Any, *, k: int | None = None) -> dict[str, Any]:
    t0 = time.perf_counter()
    records = await load_history(svc)
    if not records:
        raise HTTPException(409, "history not seeded yet")
    meta = await svc.repo.get("seed_meta", "history") or {}
    vecs = await svc.llm.embed([r["summary"] for r in records], feature="voc_embed")
    result = voc.build_voc(records, np.array(vecs, dtype=np.float64), k=k, as_of_ts=meta.get("anchor"))
    result["labelled_by"] = "llm" if await label_clusters(svc, result) else "c-tf-idf"
    result["embedder"] = getattr(svc.kb, "embedder_id", "n/a")
    result["computed_ms"] = round((time.perf_counter() - t0) * 1000)
    result["version"] = VOC_VERSION
    result["synthetic"] = True
    result["sample_factor"] = synth.SAMPLE_FACTOR
    doc = {"id": "summary", **result}
    await svc.repo.put("voc", doc)
    return result


async def seed(svc: Any, force: bool) -> dict[str, Any]:
    h = await seed_history(svc, force)
    existing = await svc.repo.get("voc", "summary")
    if existing and existing.get("version") == VOC_VERSION and not force and h.get("skipped") is not False:
        return {"history": h, "voc": "cached"}
    res = await compute(svc)
    return {"history": h, "voc": {"k": res["k"], "purity": res["purity"], "alerts": len(res["alerts"]), "labelled_by": res["labelled_by"]}}


async def stored(svc: Any) -> dict[str, Any]:
    doc = await svc.repo.get("voc", "summary")
    if doc is None:
        await seed_history(svc)
        await compute(svc)
        doc = await svc.repo.get("voc", "summary")
    return _strip(doc)  # type: ignore[arg-type]


@router.get("/summary")
async def summary(request: Request, _: Actor = Depends(require("voc.read"))) -> dict[str, Any]:
    """Stored aggregates (no recomputation): topics, Pareto, trends, alerts - labels and alert texts in the request locale."""
    doc = localize.localize_voc(await stored(request.app.state.services))
    return {k: v for k, v in doc.items() if k != "assignments"}


@router.get("/topics/{cluster_id}")
async def topic(cluster_id: int, request: Request, _: Actor = Depends(require("voc.read"))) -> dict[str, Any]:
    svc = request.app.state.services
    doc = localize.localize_voc(await stored(svc))
    cluster = next((c for c in doc["clusters"] if c["id"] == cluster_id), None)
    if cluster is None:
        raise HTTPException(404, "topic not found")
    ids = [h for h, c in doc["assignments"].items() if c == cluster_id]
    rows = localize.localize_history_rows(await svc.repo.query("history", {"id": {"$in": ids[:400]}}, order_by="sentiment_start", limit=400))
    return {**cluster, "conversations": [{k: r[k] for k in ("id", "date", "market", "language", "channel", "summary", "text", "sentiment_start", "sentiment_end", "carrier", "handled_by", "resolved")} for r in rows[:25]]}


@router.get("/alerts")
async def alerts(request: Request, _: Actor = Depends(require("voc.read"))) -> dict[str, Any]:
    doc = localize.localize_voc(await stored(request.app.state.services))
    return {"alerts": doc["alerts"], "as_of": doc["as_of"], "method": i18n.msg("voc.method")}


@router.get("/evidence")
async def evidence(request: Request, ids: str, _: Actor = Depends(require("voc.read"))) -> list[dict[str, Any]]:
    svc = request.app.state.services
    wanted = [i for i in ids.split(",") if i][:20]
    rows = localize.localize_history_rows(await svc.repo.query("history", {"id": {"$in": wanted}}))
    return [{k: r[k] for k in ("id", "date", "market", "language", "channel", "carrier", "product", "summary", "text", "sentiment_start", "handled_by", "resolved")} for r in rows]


@router.post("/refresh")
async def refresh(request: Request, k: int | None = None, _: Actor = Depends(require("voc.write"))) -> dict[str, Any]:
    res = await compute(request.app.state.services, k=k if k and 4 <= k <= 30 else None)
    return {"k": res["k"], "purity": res["purity"], "alerts": len(res["alerts"]), "labelled_by": res["labelled_by"], "computed_ms": res["computed_ms"]}


@router.get("/control")
async def control(request: Request, _: Actor = Depends(require("voc.read"))) -> dict[str, Any]:
    """Anomaly detector on a no-spike control dataset (same seed and generator, planted issue disabled) - must raise no alert."""
    svc = request.app.state.services
    meta = await svc.repo.get("seed_meta", "history") or {}
    records = synth.generate_history(meta.get("anchor") or synth.anchor_midnight(time.time()), spike=False)
    vecs = await svc.llm.embed([r["summary"] for r in records], feature="voc_embed")
    res = voc.build_voc(records, np.array(vecs, dtype=np.float64), as_of_ts=meta.get("anchor"))
    return {"records": len(records), "alerts": res["alerts"], "purity": res["purity"], "passed": len(res["alerts"]) == 0}


@router.get("/repeat-churn")
async def repeat_churn(request: Request, _: Actor = Depends(require("voc.read"))) -> dict[str, Any]:
    doc = localize.localize_voc(await stored(request.app.state.services))
    return {"totals": doc["totals"], "topics": [{"id": c["id"], "label": c["label"], "volume": c["volume"], "repeat_rate": c["repeat_rate"], "churn_risk_avg": c["churn_risk_avg"], "churn_high_pct": c["churn_high_pct"]} for c in doc["clusters"]], "definition": {"repeat": i18n.msg("voc.def.repeat"), "churn_risk": i18n.msg("voc.def.churn")}}
