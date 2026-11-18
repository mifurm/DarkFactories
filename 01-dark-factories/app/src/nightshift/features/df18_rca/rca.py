"""Root-cause analysis assistant (DF-18): loss Pareto, temporal causal graph over the plant topology, ranked hypotheses with evidence."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from nightshift.sim.config import PRODUCTION_TYPES

LAG_MIN = 90


def pareto(core: Any, top: int = 12) -> list[dict[str, Any]]:
    """Minutes lost by cause (state:reason) across production assets, with the worst asset per cause."""
    by_cause: dict[str, float] = defaultdict(float)
    by_asset: dict[str, dict[str, float]] = defaultdict(dict)
    for s in core.cfg.assets:
        if s.type not in PRODUCTION_TYPES and s.type not in ("COMP", "CHILL"):
            continue
        for key, mins in core.plant.assets[s.id].loss.items():
            if key.startswith(("IDLE", "MAINT:")) and key != "MAINT:maintenance":
                continue
            by_cause[key] += mins
            by_asset[key][s.id] = mins
    total = sum(by_cause.values()) or 1.0
    rows, cum = [], 0.0
    for key, mins in sorted(by_cause.items(), key=lambda kv: -kv[1])[:top]:
        cum += mins
        worst = max(by_asset[key].items(), key=lambda kv: kv[1])
        rows.append(
            {
                "cause": key,
                "minutes": round(mins),
                "share": round(mins / total, 3),
                "cumulative": round(cum / total, 3),
                "worst_asset": worst[0],
                "worst_minutes": round(worst[1]),
            }
        )
    return rows


def _topology(core: Any) -> dict[str, set[str]]:
    """Directed influence prior: upstream stage -> downstream stage, utility -> consumers, asset -> itself."""
    cfg = core.cfg
    order = ["MACH", "MOLD", "ASM", "TEST", "PACK"]
    infl: dict[str, set[str]] = defaultdict(set)
    stages = [s for s in order if s in cfg.pools]
    for a, b in zip(stages, stages[1:], strict=False):
        if a == "MACH" and b == "MOLD":
            continue
        for x in cfg.pools[a]:
            infl[x].update(cfg.pools[b])
    for s in cfg.assets:
        if s.type in PRODUCTION_TYPES:
            u = [x.id for x in cfg.assets if x.type == s.params.get("util")]
            for uid in u:
                infl[uid].add(s.id)
    return infl


def causal_graph(core: Any, window_min: int = 720) -> dict[str, Any]:
    """Temporal causal graph: edge A->B when B-type events follow A-type events within LAG_MIN more often than chance, boosted by topology."""
    t_end = core.plant.t
    ev = [
        e
        for e in core.event_log
        if e["t"] >= t_end - window_min and e["kind"] in ("failure", "state", "maintenance_start", "tool_change")
    ]
    nodes: dict[str, dict[str, Any]] = {}
    seq: list[tuple[int, str, dict[str, Any]]] = []
    for e in ev:
        if e["kind"] == "state":
            if e["to"] not in ("DOWN", "STARVED", "BLOCKED", "MAINT") or not e.get("asset"):
                continue
            label = f"{e['asset']}:{e['to']}:{e.get('reason') or ''}".rstrip(":")
        elif e["kind"] == "failure":
            label = f"{e['asset']}:FAILURE:{e.get('cause')}"
        else:
            label = f"{e['asset']}:{e['kind'].upper()}"
        seq.append((e["t"], label, e))
        nodes.setdefault(label, {"id": label, "asset": e.get("asset"), "count": 0, "first_t": e["t"]})["count"] += 1
    infl = _topology(core)
    edges: dict[tuple[str, str], dict[str, Any]] = {}
    for i, (ta, la, ea) in enumerate(seq):
        for tb, lb, eb in seq[i + 1 :]:
            if tb - ta > LAG_MIN:
                break
            if la == lb or ea.get("asset") == eb.get("asset") and ea["kind"] == "state" and eb["kind"] == "state":
                continue
            linked = eb.get("asset") in infl.get(ea.get("asset"), set())
            same = ea.get("asset") == eb.get("asset")
            if not (linked or same):
                continue
            ed = edges.setdefault(
                (la, lb),
                {"from": la, "to": lb, "co": 0, "lag": [], "topology": "downstream" if linked else "same-asset"},
            )
            ed["co"] += 1
            ed["lag"].append(tb - ta)
    out_edges = []
    for (la, lb), ed in edges.items():
        strength = ed["co"] / max(1, nodes[la]["count"]) * (1.6 if ed["topology"] == "downstream" else 1.0)
        out_edges.append(
            {
                "from": la,
                "to": lb,
                "co_occurrences": ed["co"],
                "median_lag_min": sorted(ed["lag"])[len(ed["lag"]) // 2],
                "topology": ed["topology"],
                "strength": round(min(1.0, strength), 3),
            }
        )
    out_edges.sort(key=lambda e: -e["strength"])
    return {"nodes": list(nodes.values())[:80], "edges": out_edges[:120], "window_min": window_min}


def analyze(core: Any, asset: str | None = None, window_min: int = 720) -> dict[str, Any]:
    """Ranked hypotheses for the largest loss (or a chosen asset): which upstream events preceded it, with evidence."""
    p = core.plant
    par = pareto(core)
    graph = causal_graph(core, window_min)
    infl = _topology(core)
    cfg = core.cfg
    if asset is None and par:
        asset = par[0]["worst_asset"]
    symptoms = [
        e
        for e in core.event_log
        if e["t"] >= p.t - window_min
        and e["kind"] == "state"
        and e.get("asset") == asset
        and e["to"] in ("DOWN", "STARVED", "BLOCKED")
    ]
    symptom = symptoms[-1] if symptoms else None
    hyps: list[dict[str, Any]] = []
    if asset:
        t0 = symptom["t"] if symptom else p.t
        cands = [
            e
            for e in core.event_log
            if t0 - 120 <= e["t"] <= t0
            and e["kind"] in ("failure", "maintenance_start", "tool_change", "state")
            and e.get("asset")
        ]
        scored: dict[str, dict[str, Any]] = {}
        for e in cands:
            a = e["asset"]
            if e["kind"] == "state" and e["to"] not in ("DOWN", "STARVED", "BLOCKED"):
                continue
            related = a == asset or asset in infl.get(a, set())
            if not related:
                continue
            kind = e["kind"] if e["kind"] != "state" else f"state:{e['to']}"
            label = f"{a} {('failure (' + str(e.get('cause')) + ')') if e['kind'] == 'failure' else kind}"
            sev = 3.0 if e["kind"] == "failure" else 1.5 if e["kind"] in ("maintenance_start", "tool_change") else 1.0
            prox = 1.0 - min(1.0, (t0 - e["t"]) / 120.0)
            prior = 1.6 if asset in infl.get(a, set()) else 1.0 if a == asset else 0.6
            score = sev * (0.4 + 0.6 * prox) * prior
            h = scored.setdefault(label, {"cause": label, "asset": a, "score": 0.0, "evidence": [], "first_t": e["t"]})
            h["score"] += score
            h["evidence"].append(
                {
                    "t": e["t"],
                    "sim_time": (p.start_dt).isoformat() if False else None,
                    "event": e["kind"],
                    "detail": {k: v for k, v in e.items() if k in ("to", "reason", "cause", "frm")},
                }
            )
        hyps = sorted(scored.values(), key=lambda h: -h["score"])[:6]
        tot = sum(h["score"] for h in hyps) or 1.0
        for i, h in enumerate(hyps, 1):
            h["rank"], h["confidence"] = i, round(h["score"] / tot, 2)
            h["evidence"] = h["evidence"][:4]
            h["explanation"] = (
                f"{h['asset']} event preceded the symptom on {asset} by {t0 - h['first_t']} min and is {'upstream/utility-linked' if h['asset'] != asset else 'on the same asset'}."
            )
    return {
        "asset": asset,
        "symptom": ({"t": symptom["t"], "state": symptom["to"], "reason": symptom.get("reason")} if symptom else None),
        "pareto": par,
        "hypotheses": hyps,
        "graph": graph,
        "assets": [s.id for s in cfg.assets if s.type in PRODUCTION_TYPES],
    }
