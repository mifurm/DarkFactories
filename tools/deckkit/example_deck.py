"""Example deck exercising every deckkit slide type (also used as the kit's smoke test).

    /Users/michalfu/Dev/SwarmAI/.venv/bin/python /Users/michalfu/Dev/SwarmAI/tools/deckkit/example_deck.py /tmp/deckkit-example.pptx
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from deckkit import Deck, Theme  # noqa: E402


def build(path: str) -> list[str]:
    d = Deck(Theme.dark_factory(), footer="SwarmAI · Dark Factory · Confidential draft", title="deckkit example")
    d.title_slide("The factory that runs itself", "An Azure-native swarm of AI agents for lights-out manufacturing", meta="Executive briefing · November 2026",
                  notes="Welcome. 30-second framing of the idea.")
    d.bullets("Executive summary: autonomy that is measured, governed and paid back within 14 months",
              ["**Problem** — unplanned downtime, scrap and slow decisions cost plants millions every year",
               ("**Solution** — a swarm of specialised agents on a digital twin, humans on the loop", ["Sim-first validation of every action", "Autonomy dial L0–L5 with policy-as-code"]),
               "**Evidence** — A/B replay shows 31% less downtime over 10 seeds (simulation)",
               "**Ask** — fund a 2-plant pilot and a Lights-Out Readiness Assessment"],
              side_title="Headline numbers", side_items=["3-yr NPV **$41.2M**", "Payback **14 months**", "Year-3 ACR **$6.8M**"],
              takeaway="Start with a readiness assessment; expand plant by plant as trust is earned.", notes="Read the headline numbers.", source="Source: business-case/outputs.json (Base scenario)")
    d.kpi_cards("Measured value in the simulated plant (10 seeds, swarm ON vs OFF)", [
        {"value": "−31%", "label": "Unplanned downtime", "sub": "95% CI −24% … −38%"},
        {"value": "+5.2 pts", "label": "OEE", "sub": "74.1% → 79.3%"},
        {"value": "−22%", "label": "Scrap", "sub": "quality guardian"},
        {"value": "−9%", "label": "Energy cost", "sub": "load shifting"}], takeaway="All figures from the in-app A/B replay; assumptions visible in the UI.", notes="n/a")
    d.chart("Benefits by category compound as plants are added", ["Year 1", "Year 2", "Year 3"],
            {"Downtime": [2.1, 6.4, 11.8], "Scrap": [0.8, 2.5, 4.7], "Energy": [0.4, 1.3, 2.6], "Labour": [0.9, 2.9, 5.1]}, kind="stacked", number_format='$#,##0.0"M"',
            commentary=["Downtime is ~45% of value", "Ramp follows plant roll-out: 2 → 5 → 8 plants", "Conservative case halves every bar"], commentary_title="Reading the chart",
            takeaway="Value scales with the number of plants on the platform.", notes="n/a", source="Source: model.py base scenario")
    d.chart("Where Azure consumption comes from (Year-3, base)", ["AI & models", "Fabric & data", "IoT & edge", "Compute", "Security & ops"], {"ACR $M": [2.1, 1.9, 1.2, 0.9, 0.7]},
            kind="doughnut", number_format='$#,##0.0"M"', labels=True, notes="n/a")
    d.chart("ROI trajectory", ["Q1", "Q2", "Q3", "Q4", "Q5", "Q6", "Q7", "Q8"], {"Cumulative net benefit ($M)": [-2.1, -3.0, -2.4, -0.9, 1.8, 5.2, 9.8, 15.4]}, kind="line", number_format='$#,##0.0"M"', notes="n/a")
    d.waterfall("From gross benefit to net: the bridge", [("Downtime", 11.8), ("Scrap", 4.7), ("Energy", 2.6), ("Labour", 5.1), ("Azure run cost", -6.8), ("Edge & integration", -4.1)], number_format="0.0",
                commentary=["Azure run cost is **~27%** of gross benefit", "Edge & integration are one-time"], commentary_title="So what", takeaway="Net 3-year benefit is 2.4× total cost.", notes="n/a")
    d.tornado("Sensitivity: what moves the NPV", [("Downtime cost per hour", 22.0, 61.0), ("Adoption ramp", 28.0, 52.0), ("Discount rate", 36.0, 46.0), ("Azure unit prices", 38.0, 43.0)], base_value=41.2,
              metric_label="NPV ($M)", number_format="0.0", takeaway="Downtime cost/hour is the assumption to validate first.", notes="n/a")
    d.table("Azure consumption by plant tier", ["Tier", "Plants", "Assets", "Year-1 ACR", "Year-3 ACR"],
            [["Pilot", "1", "400", "$0.35M", "$0.9M"], ["Expansion", "2", "800", "$0.70M", "$1.8M"], ["Region", "8", "3,200", "$2.4M", "$6.8M"], ["Enterprise", "25", "10,000", "$6.1M", "$19.5M"]],
            col_weights=[1.6, 1, 1, 1.3, 1.3], align=["left", "right", "right", "right", "right"], highlight_rows=[2], takeaway="Consumption grows with plants and with agent autonomy.", notes="n/a")
    d.architecture("Azure reference architecture: edge keeps safety loops local, cloud adds intelligence", [
        {"name": "Experience", "items": ["Control Tower (Container Apps)", "Teams approvals", "Power BI"]},
        {"name": "Agent swarm", "items": [{"title": "Foundry Agent Service", "sub": "models + tools"}, {"title": "Orchestrator", "sub": "policy-as-code"}, "Azure ML endpoints"]},
        {"name": "Data & twin", "items": ["Fabric RTI", "OneLake", "Digital Twins", "Cosmos DB"]},
        {"name": "Edge", "items": [{"title": "Azure IoT Operations", "sub": "OPC UA · MQTT"}, "Arc-enabled K8s", "Local ONNX inference"]}],
        side={"name": "Cross-cutting", "items": ["Entra ID", "Key Vault", "Defender", "Monitor"]}, notes="n/a", source="Source: ARCHITECTURE.md")
    d.hub_spoke("The swarm: seven specialists, one supervisor, hard guardrails", {"title": "Shift Supervisor", "sub": "arbitration · sim-first · policy"},
                [{"title": "Planner", "sub": "finite-capacity schedule"}, {"title": "Maintenance", "sub": "RUL + work orders"}, {"title": "Quality", "sub": "SPC + vision"},
                 {"title": "Materials", "sub": "AMR + inventory"}, {"title": "Energy", "sub": "tariff-aware shifting"}, {"title": "Safety", "sub": "veto power"}, {"title": "Process", "sub": "bounded optimisation"}],
                takeaway="Safety has a veto; every action is rehearsed on the twin first.", notes="n/a")
    d.diagram("Voice path: under 800 ms from caller speech to agent reply", [
        {"id": "c", "x": 0.0, "y": 1.6, "w": 1.9, "h": 1.0, "title": "Caller", "sub": "PSTN / web"},
        {"id": "a", "x": 2.7, "y": 1.6, "w": 2.2, "h": 1.0, "title": "ACS Call Automation", "kind": "accent"},
        {"id": "r", "x": 5.7, "y": 1.6, "w": 2.2, "h": 1.0, "title": "Realtime relay", "sub": "Container Apps", "kind": "dark"},
        {"id": "m", "x": 8.7, "y": 1.6, "w": 2.4, "h": 1.0, "title": "Azure OpenAI Realtime"},
        {"id": "t", "x": 5.7, "y": 3.6, "w": 2.2, "h": 0.9, "title": "Tools / policy engine", "kind": "ghost"}],
        [{"from": "c", "to": "a", "label": "audio"}, {"from": "a", "to": "r", "label": "media stream"}, {"from": "r", "to": "m", "label": "WebSocket"}, {"from": "r", "to": "t", "label": "tool calls", "dashed": True}],
        takeaway="Barge-in and tool calls are handled inside the relay.", notes="n/a")
    d.process("From brief to broadcast in six steps", [{"title": "Brief", "body": "Structured intake and clarifying questions"}, {"title": "Strategy", "body": "Three territories grounded in the Brand Brain"},
              {"title": "Script", "body": "6/15/30 s scripts with claim awareness"}, {"title": "Storyboard", "body": "Consistent frames from the image model"}, {"title": "Produce", "body": ["Voice-over", "Captions", "Brand end-card"]},
              {"title": "Govern", "body": "Guardian review, approval, provenance"}], takeaway="Every step is a stage gate with an audit trail.", notes="n/a")
    d.timeline("Adoption path: assess, pilot, scale", [{"name": "Assess", "when": "Weeks 0–6", "items": ["Lights-Out Readiness Assessment", "Data & connectivity audit"]},
               {"name": "Pilot", "when": "Months 2–6", "items": ["2 plants, L1–L3 autonomy", "Measured A/B value"]}, {"name": "Scale", "when": "Months 7–18", "items": ["5 → 8 plants", "L4 on proven decision classes"]},
               {"name": "Enterprise", "when": "Year 2+", "items": ["Fleet learning", "Lights-out cells"]}], takeaway="Autonomy is earned decision class by decision class.", notes="n/a")
    d.comparison("Night shift: before and after", "Before — reactive", ["Bearing fails at 02:40, line down 3.5 h", "Supervisor called at home", "Rush order missed"], "After — swarm on the loop",
                 ["Failure predicted 14 h ahead, fixed in 05:30 changeover", "Plan rehearsed on the twin, auto-approved at L4", "Due dates held; shift report at 06:00"], takeaway="One failure avoided pays for a plant-month of platform cost.", notes="n/a")
    d.capability_map("Release 1 capability map: 25 features in five epics", [
        {"name": "A · Twin & telemetry", "items": ["DF-01 Simulator", "DF-02 Unified namespace", "DF-03 What-if engine"]},
        {"name": "B · Agent swarm", "items": ["DF-04 Supervisor", "DF-05 Maintenance", "DF-06 Quality", "DF-07 Planner", "DF-08 Materials", "DF-09 Energy", "DF-10 Safety", "DF-11 Process"]},
        {"name": "C · Governance", "items": ["DF-12 Autonomy dial", "DF-13 Approvals", "DF-14 Ledger", "DF-15 Readiness"]},
        {"name": "D · Copilot", "items": ["DF-16 Ask the Factory", "DF-17 Shift report", "DF-18 RCA", "DF-19 KPIs"]},
        {"name": "E · Platform & value", "items": ["DF-20 Control tower", "DF-21 ROI + ACR", "DF-22 Fleet", "DF-23 RBAC", "DF-24 FinOps", "DF-25 IaC"]}], notes="n/a")
    d.two_column("Responsible by design", "What the swarm may do", ["Propose and execute within policy", "Rehearse on the twin first", "Escalate when uncertain"], "What it may never do",
                 ["Override Safety", "Change forbidden setpoints", "Act without an audit entry"], takeaway="Guardrails are code, tested and enforced — not prompts.", notes="n/a")
    d.section("Azure opportunity", "For Microsoft & partner leadership — skip for customer-only audiences", number="02", notes="n/a")
    d.big_statement("The ask", "Approve a two-plant pilot and a Lights-Out Readiness Assessment this quarter.", sub="Decision needed by end of month.", bullets=["Executive sponsor: COO", "Budget: pilot + assessment", "Success: measured A/B uplift"], notes="n/a")
    d.sources("Sources", [f"Publisher {i}, Title of reference document {i}, 2025. https://example.com/{i}" for i in range(1, 22)], notes="n/a")
    out = d.save(path)
    print("saved", out, "slides:", len(d.prs.slides), "warnings:", len(d.warnings))
    return d.warnings


if __name__ == "__main__":
    build(sys.argv[1] if len(sys.argv) > 1 else "/tmp/deckkit-example.pptx")
