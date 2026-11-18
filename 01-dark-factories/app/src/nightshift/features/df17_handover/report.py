"""Shift handover & executive digest (DF-17): structured KPI/ledger facts, LLM narration with a deterministic template fallback."""

from __future__ import annotations

import html
from datetime import timedelta
from typing import Any

from nightshift.core.llm import Narration, narrate
from nightshift.features.df19_kpi.engine import KpiEngine


def shift_name(minute_of_day: int) -> str:
    if 6 * 60 <= minute_of_day < 14 * 60:
        return "Day"
    if 14 * 60 <= minute_of_day < 22 * 60:
        return "Late"
    return "Night"


def build_report_data(core: Any, window_min: int = 480) -> dict[str, Any]:
    p = core.plant
    k = KpiEngine.compute(p, window_min)
    pk, imp = k["plant_kpi"], k["impact_eur"]
    since = p.t - window_min
    led = core.ledger.query(since_t=since, limit=5000, desc=False)["items"]
    avoided = [e for e in led if e["outcome"] == "failure_avoided"]
    failed = [e for e in led if e["kind"] == "observation" and e["outcome"] == "failure"]
    auto = [e for e in led if e["kind"] == "decision" and e["outcome"] == "auto_approved"]
    human = [e for e in led if e["kind"] == "override"]
    vetoes = [e for e in led if e["kind"] == "veto"]
    late = [e for e in led if e["outcome"] == "late_order"]
    saved = sum(float(e["counterfactual"].get("avoided_loss_eur", 0.0)) for e in avoided)
    energy_saved = sum(s["saved_eur"] for s in p.shifts.values())
    pending = core.inbox.pending()
    down = [a for a, st in p.assets.items() if st.state == "DOWN"]
    events = [
        {"sim_time": e["sim_time"], "agent": e["agent"], "summary": e["summary"], "seq": e["seq"]}
        for e in led
        if e["kind"] in ("outcome", "veto", "override")
        or (e["kind"] == "decision" and e["outcome"] in ("auto_approved", "denied", "expired"))
    ][-8:]
    windows = p.next_planned_windows(p.t, 720)
    return {
        "plant": core.plant_id,
        "plant_name": core.cfg.name,
        "shift": shift_name(p.minute_of_day()),
        "window_h": round(window_min / 60, 1),
        "sim_time": p.now.isoformat(timespec="minutes"),
        "from_time": (p.now - timedelta(minutes=window_min)).isoformat(timespec="minutes"),
        "kpi": {
            m: pk[m]
            for m in (
                "oee",
                "availability",
                "throughput_uph",
                "units_good",
                "otif",
                "orders_completed",
                "scrap_pct",
                "downtime_min",
                "energy_kwh",
                "kwh_per_unit",
                "co2_per_unit_kg",
                "tardiness_h",
                "overdue_orders",
                "failures",
                "energy_cost_eur",
            )
        },
        "impact_eur": imp,
        "failures_avoided": len(avoided),
        "failures_occurred": len(failed),
        "missed_due_dates": pk["overdue_orders"] + len(late),
        "eur_saved_estimate": round(saved + energy_saved, 0),
        "avoided_loss_eur": round(saved, 0),
        "energy_shift_saved_eur": round(energy_saved, 1),
        "auto_decisions": len(auto),
        "human_decisions": len(human),
        "vetoes": len(vetoes),
        "pending_approvals": [{"id": i.id, "title": i.title} for i in pending],
        "assets_down": down,
        "highlights": events,
        "next_windows": [
            {
                "start": (p.now + timedelta(minutes=s - p.t)).strftime("%H:%M"),
                "end": (p.now + timedelta(minutes=e - p.t)).strftime("%H:%M"),
            }
            for s, e in windows[:3]
        ],
        "scheduled_maintenance": [
            {
                "asset": w.asset,
                "start": (p.now + timedelta(minutes=w.start_t - p.t)).strftime("%H:%M"),
                "reason": w.reason,
            }
            for w in p.work_orders.values()
            if w.status == "scheduled"
        ],
    }


def _pct(v: Any) -> str:
    return "n/a" if v is None else f"{v * 100:.1f} %"


def template_summary(d: dict[str, Any]) -> str:
    """Deterministic executive summary (used when the model is unreachable, over budget, or offline)."""
    k = d["kpi"]
    parts = [
        f"{d['shift']} shift at {d['plant_name']}: OEE {_pct(k['oee'])}, {k['units_good']:.0f} good units, OTIF {_pct(k['otif'])}."
    ]
    parts.append(
        f"{d['failures_avoided']} failure(s) avoided, {d['failures_occurred']} occurred; {d['missed_due_dates']} due date(s) at risk or missed; "
        f"estimated EUR {d['eur_saved_estimate']:,.0f} saved."
    )
    parts.append(
        f"The swarm took {d['auto_decisions']} autonomous decision(s) and {d['human_decisions']} needed a human; {len(d['pending_approvals'])} approval(s) are open."
    )
    if d["assets_down"]:
        parts.append("Currently down: " + ", ".join(d["assets_down"]) + ".")
    if d["scheduled_maintenance"]:
        m = d["scheduled_maintenance"][0]
        parts.append(f"Next planned maintenance: {m['asset']} at {m['start']} ({m['reason']}).")
    return " ".join(parts)


def render_markdown(d: dict[str, Any], summary: str) -> str:
    k, imp = d["kpi"], d["impact_eur"]
    lines = [
        f"# Shift report - {d['plant_name']} - {d['shift']} shift",
        f"_{d['from_time']} to {d['sim_time']} (simulated plant time)_",
        "",
        "## Summary",
        summary,
        "",
        "## KPIs",
        "",
        "| KPI | Value |",
        "|---|---:|",
        f"| OEE | {_pct(k['oee'])} |",
        f"| Availability | {_pct(k['availability'])} |",
        f"| Good units | {k['units_good']:.0f} |",
        f"| OTIF | {_pct(k['otif'])} |",
        f"| Scrap | {k['scrap_pct'] * 100:.2f} % |",
        f"| Unplanned downtime | {k['downtime_min']:.0f} min |",
        f"| Energy | {k['energy_kwh']:.0f} kWh ({k['kwh_per_unit'] or 0:.2f} kWh/unit) |",
        f"| CO2e per unit | {k['co2_per_unit_kg'] or 0:.3f} kg |",
        f"| Tardiness | {k['tardiness_h']:.1f} h ({k['overdue_orders']} overdue orders) |",
        "",
        "## Value",
        "",
        f"- Failures avoided: **{d['failures_avoided']}** (avoided loss EUR {d['avoided_loss_eur']:,.0f})",
        f"- Energy load-shifting saved EUR {d['energy_shift_saved_eur']:,.1f}",
        f"- Loss still incurred: EUR {imp['loss_total']:,.0f} (downtime {imp['downtime']:,.0f}, scrap {imp['scrap']:,.0f}, escapes {imp['escapes']:,.0f}, tardiness {imp['tardiness']:,.0f})",
        "",
        "## Decisions",
        "",
        f"- Autonomous: {d['auto_decisions']}  |  Human: {d['human_decisions']}  |  Safety vetoes: {d['vetoes']}",
    ]
    for h in d["highlights"]:
        lines.append(f"  - {h['sim_time'][11:]} {h['agent']}: {h['summary']} (ledger #{h['seq']})")
    if d["pending_approvals"]:
        lines += ["", "## Open approvals", ""] + [f"- {i['id']}: {i['title']}" for i in d["pending_approvals"]]
    lines += ["", "## Outlook", ""] + [f"- Planned window {w['start']}-{w['end']}" for w in d["next_windows"]]
    lines += [f"- Scheduled: {m['asset']} at {m['start']} - {m['reason']}" for m in d["scheduled_maintenance"]]
    lines += ["", "_Simulated plant, synthetic data._"]
    return "\n".join(lines) + "\n"


def render_html(d: dict[str, Any], summary: str) -> str:
    md = render_markdown(d, summary)
    body = []
    for line in md.splitlines():
        e = html.escape(line)
        if line.startswith("# "):
            body.append(f"<h1>{e[2:]}</h1>")
        elif line.startswith("## "):
            body.append(f"<h2>{e[3:]}</h2>")
        elif line.startswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if set("".join(cells)) <= set("-: "):
                continue
            body.append("<tr>" + "".join(f"<td>{html.escape(c)}</td>" for c in cells) + "</tr>")
        elif line.lstrip().startswith("- "):
            body.append(f"<li>{html.escape(line.lstrip()[2:])}</li>")
        elif line.strip():
            body.append(f"<p>{e}</p>")
    css = "body{font-family:system-ui,sans-serif;max-width:860px;margin:2rem auto;color:#102030}td{padding:2px 10px;border-bottom:1px solid #ddd}h1{font-size:1.4rem}"
    return f"<!doctype html><html><head><meta charset='utf-8'><title>Shift report</title><style>{css}</style></head><body>{''.join(body)}</body></html>"


async def generate(rt: Any, core: Any, window_min: int = 480, use_llm: bool = True) -> dict[str, Any]:
    d = build_report_data(core, window_min)
    nar: Narration = await narrate(
        rt.llm if use_llm else None,
        "shift-report",
        d,
        "Write the executive summary of this shift for the plant manager in 4-6 sentences: what happened, what the swarm did, "
        "value protected (failures avoided, due dates, EUR), and what needs attention next shift. Use only the facts.",
        template_summary,
        role="chat",
        max_tokens=600,
    )
    report = {
        "id": f"SR-{core.plant_id}-{core.plant.t:06d}",
        "plant": core.plant_id,
        "t": core.plant.t,
        "sim_time": d["sim_time"],
        "shift": d["shift"],
        "summary": nar.text,
        "source": nar.source,
        "model": nar.model,
        "budget_blocked": nar.blocked,
        "data": d,
        "markdown": render_markdown(d, nar.text),
        "html": render_html(d, nar.text),
    }
    core.reports.append(report) if hasattr(core, "reports") else None
    if hasattr(core, "reports"):
        del core.reports[:-30]
    try:
        rt.writer.enqueue(
            "reports", {"id": report["id"], "pk": core.plant_id, **{k: v for k, v in report.items() if k != "html"}}
        )
    except Exception:  # pragma: no cover
        pass
    return report
