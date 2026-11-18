"""Lights-Out Readiness Assessment (DF-15): questionnaire + auto-measured signals -> radar score, gap analysis, roadmap, export."""

from __future__ import annotations

import csv
import io
from typing import Any

DIMENSIONS = {
    "data": ("Data", 0.20),
    "connectivity": ("Connectivity", 0.15),
    "automation": ("Automation", 0.20),
    "safety": ("Safety", 0.15),
    "process": ("Process stability", 0.20),
    "skills": ("Skills & organisation", 0.10),
}
SCALE = "0 = not in place, 1 = ad hoc, 2 = partly, 3 = standardised, 4 = optimised / continuously improved"

QUESTIONS: list[dict[str, Any]] = [
    {
        "id": "data.coverage",
        "dim": "data",
        "text": "Share of critical assets with continuous condition/process data (vibration, temperature, load, quality)",
        "measured": True,
    },
    {
        "id": "data.historian",
        "dim": "data",
        "text": "Time-series historian / unified namespace with consistent asset naming (ISA-95)",
        "measured": False,
    },
    {
        "id": "data.quality",
        "dim": "data",
        "text": "Data quality: time sync, missing-value handling, calibration records",
        "measured": True,
    },
    {
        "id": "data.context",
        "dim": "data",
        "text": "Work orders, recipes and orders linked to machine data (MES/ERP context)",
        "measured": False,
    },
    {
        "id": "conn.protocols",
        "dim": "connectivity",
        "text": "Open protocols (OPC UA / MQTT) available on the controllers in scope",
        "measured": False,
    },
    {
        "id": "conn.segmentation",
        "dim": "connectivity",
        "text": "OT/IT segmentation (Purdue) with a monitored DMZ",
        "measured": False,
    },
    {
        "id": "conn.edge",
        "dim": "connectivity",
        "text": "Edge compute with store-and-forward for safety-relevant loops",
        "measured": False,
    },
    {
        "id": "conn.remote",
        "dim": "connectivity",
        "text": "Secure remote access (MFA, jump host, session recording)",
        "measured": False,
    },
    {
        "id": "auto.handling",
        "dim": "automation",
        "text": "Automated material handling / feeding (AMR, conveyors, kitting)",
        "measured": True,
    },
    {
        "id": "auto.closedloop",
        "dim": "automation",
        "text": "Closed-loop process control and automatic tool/recipe changes",
        "measured": False,
    },
    {
        "id": "auto.share",
        "dim": "automation",
        "text": "Share of routine operating decisions executed without a human",
        "measured": True,
    },
    {
        "id": "auto.recovery",
        "dim": "automation",
        "text": "Automatic recovery from minor stops (jams, restarts)",
        "measured": False,
    },
    {
        "id": "safe.zones",
        "dim": "safety",
        "text": "Safety zones, light curtains / scanners and verified restart procedures",
        "measured": False,
    },
    {
        "id": "safe.risk",
        "dim": "safety",
        "text": "Documented risk assessment (ISO 12100) incl. unattended operation",
        "measured": False,
    },
    {
        "id": "safe.guards",
        "dim": "safety",
        "text": "Hard limits on setpoints / protected assets enforced below the AI layer",
        "measured": False,
    },
    {
        "id": "safe.cyber",
        "dim": "safety",
        "text": "Cyber hygiene posture of the OT network (patching, credentials, monitoring)",
        "measured": False,
    },
    {"id": "proc.mtbf", "dim": "process", "text": "Mean time between failures of critical assets", "measured": True},
    {"id": "proc.scrap", "dim": "process", "text": "Scrap / rework rate", "measured": True},
    {
        "id": "proc.cpk",
        "dim": "process",
        "text": "Process capability (Cpk) of critical characteristics, SPC in use",
        "measured": True,
    },
    {
        "id": "proc.changeover",
        "dim": "process",
        "text": "Standardised changeovers and planned maintenance windows",
        "measured": False,
    },
    {
        "id": "skill.ot_it",
        "dim": "skills",
        "text": "OT and IT teams collaborate on shared roadmaps and incident response",
        "measured": False,
    },
    {"id": "skill.data", "dim": "skills", "text": "Data literacy among engineers and supervisors", "measured": False},
    {
        "id": "skill.remote_ops",
        "dim": "skills",
        "text": "Remote-operator competence for exception handling",
        "measured": False,
    },
    {
        "id": "skill.change",
        "dim": "skills",
        "text": "Structured change management and operator trust-building",
        "measured": False,
    },
]

LEVELS = [
    (0, "L0 Manual", "Largely manual; data on paper or in isolated machines."),
    (25, "L1 Digitised", "Data collected, humans decide everything."),
    (45, "L2 Assisted", "Analytics advise; humans act on every exception."),
    (65, "L3 Supervised autonomy", "Agents act within guardrails; humans supervise."),
    (80, "L4 Lights-out ready", "Extended unattended operation with exception-only supervision."),
]

ROADMAP = [
    {
        "dim": "data",
        "title": "Instrument critical assets & stream to a unified namespace",
        "effort": "M",
        "months": "0-3",
        "azure": "Azure IoT Operations, Event Hubs, Fabric RTI",
        "below": 70,
    },
    {
        "dim": "data",
        "title": "Link orders, recipes and work orders to machine data",
        "effort": "M",
        "months": "3-6",
        "azure": "Fabric OneLake, MES/ERP connectors",
        "below": 60,
    },
    {
        "dim": "connectivity",
        "title": "Enable OPC UA / MQTT on controllers and segment the OT network (Purdue DMZ)",
        "effort": "L",
        "months": "0-6",
        "azure": "Azure IoT Operations, Defender for IoT",
        "below": 65,
    },
    {
        "dim": "connectivity",
        "title": "Edge inference + store-and-forward for safety-relevant loops",
        "effort": "M",
        "months": "3-6",
        "azure": "Arc-enabled Kubernetes, ONNX runtime",
        "below": 60,
    },
    {
        "dim": "automation",
        "title": "Automate feeding, tool changes and minor-stop recovery",
        "effort": "L",
        "months": "3-12",
        "azure": "AMR fleet manager integration",
        "below": 65,
    },
    {
        "dim": "automation",
        "title": "Raise autonomy per decision class with policy-as-code (Autonomy Dial)",
        "effort": "S",
        "months": "0-3",
        "azure": "Nightshift policy engine, Teams approvals",
        "below": 70,
    },
    {
        "dim": "safety",
        "title": "Close safety-risk assessment gaps for unattended running; verified remote restart",
        "effort": "M",
        "months": "0-6",
        "azure": "Safety PLC + Nightshift Safety Sentinel",
        "below": 75,
    },
    {
        "dim": "safety",
        "title": "OT cyber-hygiene programme (patching, credentials, monitoring)",
        "effort": "M",
        "months": "0-6",
        "azure": "Defender for IoT, Sentinel",
        "below": 75,
    },
    {
        "dim": "process",
        "title": "Deploy SPC and predictive maintenance on bottleneck assets",
        "effort": "M",
        "months": "0-6",
        "azure": "Azure ML, Foundry, Nightshift PdM/Quality agents",
        "below": 75,
    },
    {
        "dim": "process",
        "title": "Standardise changeovers and planned maintenance windows",
        "effort": "S",
        "months": "0-3",
        "azure": "Planner agent + MES calendar",
        "below": 65,
    },
    {
        "dim": "skills",
        "title": "Train remote operators on exception handling; build OT/IT squads",
        "effort": "S",
        "months": "0-6",
        "azure": "Teams, Microsoft Learn",
        "below": 70,
    },
]


def _bands(value: float, thresholds: list[float], higher_is_better: bool = True) -> float:
    """Map a measured value onto 0..4 using 4 ascending (or descending) thresholds."""
    s = 0
    for t in thresholds:
        if (value >= t) if higher_is_better else (value <= t):
            s += 1
    return float(s)


def measure(core: Any) -> dict[str, dict[str, Any]]:
    """Auto-measured signals from the running simulation, already mapped to question scores (0..4)."""
    from nightshift.features.df19_kpi.engine import KpiEngine

    p = core.plant
    k = KpiEngine.compute(p, 480)["plant_kpi"]
    prod = [s for s in core.cfg.assets if s.type in ("CNC", "PRESS", "ASM", "TEST", "PACK", "COMP", "CHILL")]
    with_data = [s for s in prod if len(s.sensors) >= 2]
    cov = len(with_data) / max(1, len(prod))
    series = p.store.data[:, : min(p.store.n, p.store.cap)]
    finite = float((series == series).mean()) if series.size else 1.0
    sup = core.supervisor.stats
    auto_share = sup["auto"] / max(1, sup["auto"] + sup["approvals"]) if (sup["auto"] + sup["approvals"]) else 0.0
    amr = [a for a in p.assets.values() if core.cfg.asset(a.id).type == "AMR"]
    amr_avail = sum(a.mins["RUN"] + a.mins["IDLE"] for a in amr) / max(1.0, sum(sum(a.mins.values()) for a in amr))
    cpks = [r["cpk"] for r in core.quality.summary(core.world()) if r.get("cpk") is not None]
    out: dict[str, dict[str, Any]] = {
        "data.coverage": {
            "score": _bands(cov, [0.25, 0.5, 0.75, 0.95]),
            "value": round(cov, 3),
            "unit": "share of assets with >=2 live sensor channels",
        },
        "data.quality": {
            "score": _bands(finite, [0.3, 0.5, 0.7, 0.85]),
            "value": round(finite, 3),
            "unit": "share of non-missing samples",
        },
        "auto.handling": {
            "score": _bands(amr_avail, [0.5, 0.7, 0.85, 0.95]),
            "value": round(amr_avail, 3),
            "unit": "AMR fleet availability",
        },
        "auto.share": {
            "score": _bands(auto_share, [0.1, 0.3, 0.55, 0.8]),
            "value": round(auto_share, 3),
            "unit": "auto-approved / (auto + human) decisions",
        },
        "proc.scrap": {
            "score": _bands(k["scrap_pct"], [0.05, 0.02, 0.01, 0.005], higher_is_better=False),
            "value": round(k["scrap_pct"], 4),
            "unit": "scrap share of started units",
        },
    }
    if k["mtbf_h"] is not None:
        out["proc.mtbf"] = {
            "score": _bands(k["mtbf_h"], [20, 50, 120, 300]),
            "value": round(k["mtbf_h"], 1),
            "unit": "h (running hours per failure)",
        }
    else:
        out["proc.mtbf"] = {"score": 3.0, "value": None, "unit": "no failure in the window (>= window length)"}
    if cpks:
        out["proc.cpk"] = {
            "score": _bands(min(cpks), [0.67, 1.0, 1.33, 1.67]),
            "value": round(min(cpks), 2),
            "unit": "worst Cpk of SPC characteristics",
        }
    return out


def score(
    answers: dict[str, float], measured: dict[str, dict[str, Any]], measured_weight: float = 0.7
) -> dict[str, Any]:
    qs = {q["id"]: q for q in QUESTIONS}
    per_q: dict[str, dict[str, Any]] = {}
    for qid, q in qs.items():
        ans = answers.get(qid)
        m = measured.get(qid)
        if m is not None and ans is not None:
            val, basis = (
                measured_weight * m["score"] + (1 - measured_weight) * float(ans),
                "blend (70 % measured, 30 % questionnaire)",
            )
        elif m is not None:
            val, basis = m["score"], "measured from the running plant"
        elif ans is not None:
            val, basis = float(ans), "questionnaire"
        else:
            val, basis = 0.0, "unanswered (counted as 0)"
        per_q[qid] = {
            "score": round(min(4.0, max(0.0, val)), 2),
            "basis": basis,
            "measured": m,
            "answer": ans,
            "text": q["text"],
            "dim": q["dim"],
        }
    dims: dict[str, dict[str, Any]] = {}
    for d, (label, weight) in DIMENSIONS.items():
        rows = [v["score"] for v in per_q.values() if v["dim"] == d]
        dims[d] = {
            "label": label,
            "weight": weight,
            "score": round(sum(rows) / (4 * len(rows)) * 100, 1) if rows else 0.0,
            "questions": len(rows),
        }
    overall = round(sum(dims[d]["score"] * DIMENSIONS[d][1] for d in dims), 1)
    level = max((lv for lv in LEVELS if overall >= lv[0]), key=lambda lv: lv[0])
    return {
        "overall": overall,
        "level": level[1],
        "level_description": level[2],
        "dimensions": dims,
        "questions": per_q,
    }


def gap_analysis(result: dict[str, Any], target: float = 75.0) -> list[dict[str, Any]]:
    gaps = [
        {
            "dim": d,
            "label": v["label"],
            "score": v["score"],
            "target": target,
            "gap": round(max(0.0, target - v["score"]), 1),
        }
        for d, v in result["dimensions"].items()
    ]
    return sorted(gaps, key=lambda g: -g["gap"] * DIMENSIONS[g["dim"]][1])


def roadmap(result: dict[str, Any]) -> list[dict[str, Any]]:
    items = []
    for r in ROADMAP:
        sc = result["dimensions"][r["dim"]]["score"]
        if sc < r["below"]:
            items.append({**r, "current": sc, "priority": round((r["below"] - sc) * DIMENSIONS[r["dim"]][1], 2)})
    items.sort(key=lambda x: (-x["priority"], x["months"]))
    phases = {"0-3": [], "3-6": [], "3-12": [], "0-6": []}
    for it in items:
        phases.setdefault(it["months"], []).append(it)
    return items


def assess(core: Any, answers: dict[str, float] | None = None, target: float = 75.0) -> dict[str, Any]:
    meas = measure(core)
    res = score(answers or {}, meas)
    res["gaps"] = gap_analysis(res, target)
    res["roadmap"] = roadmap(res)
    res["plant"] = core.plant_id
    res["measured_signals"] = meas
    res["scale"] = SCALE
    return res


def to_markdown(res: dict[str, Any]) -> str:
    lines = [
        f"# Lights-Out Readiness - {res.get('plant', '')}",
        "",
        f"**Overall {res['overall']} / 100 - {res['level']}** ({res['level_description']})",
        "",
        "| Dimension | Score | Gap to target |",
        "|---|---:|---:|",
    ]
    gaps = {g["dim"]: g for g in res["gaps"]}
    for d, v in res["dimensions"].items():
        lines.append(f"| {v['label']} | {v['score']} | {gaps[d]['gap']} |")
    lines += ["", "## Recommended roadmap", ""]
    for it in res["roadmap"]:
        lines.append(f"- **{it['title']}** ({it['months']} months, effort {it['effort']}; Azure: {it['azure']})")
    lines += ["", "## Auto-measured signals", ""]
    for qid, m in res["measured_signals"].items():
        lines.append(f"- {qid}: {m['value']} {m['unit']} -> score {m['score']}")
    lines += ["", "_Synthetic simulated plant - illustrative scoring model._"]
    return "\n".join(lines) + "\n"


def to_csv(res: dict[str, Any]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["question_id", "dimension", "score_0_4", "basis", "text"])
    for qid, v in res["questions"].items():
        w.writerow([qid, v["dim"], v["score"], v["basis"], v["text"]])
    return buf.getvalue()
