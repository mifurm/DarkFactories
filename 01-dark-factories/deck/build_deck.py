#!/usr/bin/env python3
"""Dark Factory (Nightshift) executive deck builder — python-pptx through the shared deckkit.

Run:   /Users/michalfu/Dev/SwarmAI/.venv/bin/python deck/build_deck.py

Writes
  deck/DarkFactory-Executive-Deck.pptx           full deck, incl. the "Azure opportunity" section for Microsoft and partner leadership
  deck/DarkFactory-Executive-Deck-customer.pptx  same storyline without the Azure-opportunity section (customer-only audiences)

Every number is read from ../business-case/outputs.json (Base scenario unless stated) or comes from a cited source (SOURCES below).
Screenshots in deck/assets/screens/ and the feature status in ../FEATURES.md are picked up automatically, so the script is
idempotent and can be re-run after engineering adds screenshots or moves features to Deployed.
"""
from __future__ import annotations

import json
import os
import re
import sys
import warnings
from pathlib import Path

KIT = Path("/Users/michalfu/Dev/SwarmAI/tools/deckkit")
sys.path.insert(0, str(KIT))
from deckkit import Deck, Para, Theme, estimate_height  # noqa: E402
from PIL import Image  # noqa: E402
from pptx.dml.color import RGBColor  # noqa: E402
from pptx.enum.chart import XL_LABEL_POSITION  # noqa: E402
from pptx.enum.shapes import MSO_SHAPE  # noqa: E402
from pptx.util import Inches, Pt  # noqa: E402

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SCREENS = Path(os.environ.get("DECK_SCREENS", HERE / "assets" / "screens"))  # env overrides exist for layout tests only
OUT_DIR = Path(os.environ.get("DECK_OUT_DIR", HERE))
FULL_NAME = "DarkFactory-Executive-Deck.pptx"
CUSTOMER_NAME = "DarkFactory-Executive-Deck-customer.pptx"
FOOTER = "SwarmAI · Dark Factory (Nightshift) · Executive briefing · Illustrative — validate with customer data"
MAX_TOUR_IN_MAIN = 4

# ----------------------------------------------------------------------------------------------------------------------
# data: everything quantitative comes from the business-case model outputs
# ----------------------------------------------------------------------------------------------------------------------
OUT = json.loads((ROOT / "business-case" / "outputs.json").read_text(encoding="utf-8"))
ASSUMP = json.loads((ROOT / "business-case" / "assumptions.json").read_text(encoding="utf-8"))["assumptions"]
SC = OUT["scenarios"]
BASE, CONS, UP = SC["base"], SC["conservative"], SC["upside"]
HB, HC, HU = (OUT["headline"][s] for s in ("base", "conservative", "upside"))
RES = BASE["inputs"]["resolved"]
DER = BASE["derived"]
UNIT = BASE["unit_economics"]
ACR = BASE["acr"]
BEN = BASE["benefits"]
COST = BASE["costs"]
ROI = BASE["roi"]
MINUS = "\u2212"
YEARS = ["Year 1", "Year 2", "Year 3"]


def m(x: float, d: int = 1) -> str:
    """US$ millions from dollars: $8.3M / −$2.1M."""
    return f"{MINUS if x < 0 else ''}${abs(x) / 1e6:,.{d}f}M"


def k(x: float, d: int = 0) -> str:
    """US$ thousands from dollars: $677k."""
    return f"{MINUS if x < 0 else ''}${abs(x) / 1e3:,.{d}f}k"


def km(x: float) -> str:
    """$735k below one million, $1.35M above."""
    return k(x) if abs(x) < 1e6 else m(x, 2)


def pc(x: float, d: int = 0) -> str:
    return f"{x * 100:,.{d}f}%"


def mil(vals, d: int = 2) -> list[float]:
    return [round(v / 1e6, d) for v in vals]


def kil(vals, d: int = 1) -> list[float]:
    return [round(v / 1e3, d) for v in vals]


def add(*lists) -> list[float]:
    return [sum(x) for x in zip(*lists)]


# headline figures used across slides
NPV, ROI_PCT, PAYBACK, IRR = HB["npv"], HB["roi_pct"], HB["payback_months"], HB["irr_pct"]
BEN3, COST3, NET3 = HB["total_benefit"], HB["total_cost"], HB["net_benefit"]
SS_BEN = HB["steady_state_benefit_per_year"]
ACR_Y = HB["acr_by_year"]
ACR_RUN = HB["acr_run_rate"]
ACR_PLANT = HB["acr_per_plant_year"]
ACR_DAY = ACR_PLANT / 365.0
PULL = HB["pull_through_ratio"]
BEN_Y = BEN["total_by_year"]
COST_Y = COST["total_by_year"]
CUM = ROI["cumulative"]
WC_RELEASE = BEN["memo"]["working_capital_release_total_usd"]
LINE_H = DER["downtime_cost_per_line_hour_usd"]
BREAKDOWN_H = 3.5
BREAKDOWN_USD = BREAKDOWN_H * LINE_H
DAYS_COVERED = BREAKDOWN_USD / ACR_DAY
COHORTS = BASE["plants"]["cohorts"]
LIVE = BASE["plants"]["live_by_year_end"]
SENS = BASE["sensitivity"]
MIN_LOW_NPV = min(min(s["npv_low"], s["npv_high"]) for s in SENS)
N_SCENARIO_VARIED = sum(1 for v in ASSUMP.values() if isinstance(v, dict) and "scenario" in v)
OPP = ACR["opportunity"]
RETRIEVED = OUT["price_retrieved_on"]
N_METERS = len(json.loads((ROOT / "business-case" / "assumptions.json").read_text(encoding="utf-8"))["prices"])
N_LINES = len(ACR["line_items"])

# expansion levers E1–E5: optional modules with their own Azure meters, costs and benefits (off in Base, on in Upside)
EXP = BASE["expansion"]
EXP_H = EXP["headline"]
EXP_LEVERS = EXP["levers"]
EXP_BY_ID = {lv["id"]: lv for lv in EXP_LEVERS}
EXP_ACR = EXP["acr"]
EXP_RUN = EXP_H["acr_run_rate"]
EXP_Y = EXP_H["acr_by_year"]
EXP_TIERS = {t["id"]: t for t in EXP["tiers"]}
EXP_PATH = {p["id"]: p for p in EXP["path"]}
LEVER_RUN = EXP_ACR["run_rate_by_lever"]
LEVER_BY_YEAR = EXP_ACR["by_lever"]
LEVER_SUM_RUN = sum(LEVER_RUN[i] for i in EXP_BY_ID)
LEVER_SHORT = {"E1": "E1 Machine vision", "E2": "E2 kHz condition monitoring", "E3": "E3 Sim-first what-if at scale", "E4": "E4 Enterprise data platform",
               "E5": "E5 OT security & connectivity"}
EXP_OPP = EXP_ACR["opportunity"]
FLEET_N = EXP_TIERS["fleet"]["plants"]
LEVER_ADOPT = {lv["id"]: lv["adoption"] for lv in EXP_LEVERS}
LEVER_PAYBACKS = [lv["per_deploying_plant"]["payback_months"] for lv in EXP_LEVERS if lv["per_deploying_plant"]["payback_months"]]

# ----------------------------------------------------------------------------------------------------------------------
# evidence from the deployed reference implementation (../REPORT-TEST-AND-DEPLOYMENT.md) and the evidence class of every benefit
# ----------------------------------------------------------------------------------------------------------------------
REPORT_PATH = ROOT / "REPORT-TEST-AND-DEPLOYMENT.md"
REPORT = REPORT_PATH.read_text(encoding="utf-8") if REPORT_PATH.exists() else ""
REPORT_PROBLEMS: list[str] = []


def report_fact(pattern: str, label: str, default: str, group: int = 1) -> str:
    mt = re.search(pattern, REPORT)
    if not mt:
        REPORT_PROBLEMS.append(f"REPORT fact not found: {label} (fallback {default!r})")
        return default
    return mt.group(group)


LIVE_URL = report_fact(r"\*\*Live URL\*\* \| <(https://[^>]+)>", "live URL", "https://ca-nightshift.blackforest-a28408f9.swedencentral.azurecontainerapps.io")
BUILD_ID = report_fact(r"\*\*Build on the live site\*\* \| `([^`]+)`", "build id", "ca-nightshift--azd-1794963538")
N_TESTS = report_fact(r"\*\*(\d+) passed\*\*", "pytest tests", "113")
COVERAGE = report_fact(r"Coverage[^|]*\|\s*\*\*(\d+) %\*\*", "line coverage", "93")
SMOKE_PASS = report_fact(r"\*\*(\d+) passed, 0 failed\.\*\*", "live smoke", "25")
PW_PASS = report_fact(r"\*\*(\d+)/\d+ on the live URL\*\*", "Playwright", "15")
IDLE_COST = report_fact(r"\*\*Total idle\*\* \| \*\*≈ \$(\d+) \(range", "idle cost", "45")
IDLE_LO, IDLE_HI = report_fact(r"\(range \$(\d+)–(\d+)\)", "idle range", "40", 1), report_fact(r"\(range \$(\d+)–(\d+)\)", "idle range", "55", 2)
AB_CONTAINER_S = report_fact(r"≈ (\d+) s on the 0\.5 vCPU container", "A/B seconds on the container", "41")
LAT_P50, LAT_P95 = report_fact(r"typical feature p50 ([\d.]+–[\d.]+) ms, p95 (\d+–\d+) ms", "server p50", "1.2–2.6", 1), report_fact(r"typical feature p50 ([\d.]+–[\d.]+) ms, p95 (\d+–\d+) ms", "server p95", "6–45", 2)
CLIENT_P50 = report_fact(r"client p50 \*\*(\d+–\d+) ms\*\*", "client p50", "251–256")
N_RESOURCES = report_fact(r"Resources \((\d+) in", "resource count", "14")
AB_SEEDS = report_fact(r"(\d+) seeds × 8 simulated hours", "A/B seeds", "16")


def read_ab_rows() -> list[list[str]]:
    """The 12-metric A/B table of REPORT §4.3 (16 seeds, window 'late'): [metric, OFF, ON, improvement, 95% CI, p, significant]."""
    i = REPORT.find("### 4.3 A/B value realization")
    j = REPORT.find("*Significant*", i)
    rows = []
    for line in REPORT[i:j].splitlines() if i >= 0 and j > i else []:
        if not line.startswith("|") or set(line.strip()) <= set("|-: "):
            continue
        cells = [c.strip().replace("**", "") for c in line.strip().strip("|").split("|")]
        if len(cells) >= 7 and cells[0] != "Metric":
            rows.append(cells)
    return rows


AB_ROWS = read_ab_rows()
if len(AB_ROWS) != 12:
    REPORT_PROBLEMS.append(f"REPORT A/B table has {len(AB_ROWS)} rows (expected 12)")
AB_SIG = sum(1 for r in AB_ROWS if r[6].lower().startswith("yes"))
AB_BY_NAME = {r[0]: r for r in AB_ROWS}

# evidence classes: which benefit categories the A/B simulation supports (downtime, OEE/throughput, late-delivery cost)
SIM_CATS = ["downtime", "throughput", "otif"]
SIM_BEN3 = sum(sum(BEN["by_category"][c]) for c in SIM_CATS)
SIM_SHARE = SIM_BEN3 / BEN3
EVID_GROUPS = [  # simulation-supported first, then benchmark/assumption-only
    ("Unplanned downtime", ["downtime"]),
    ("Throughput / OEE", ["throughput"]),
    ("Late-delivery cost (OTIF)", ["otif"]),
    ("Scrap & rework", ["scrap"]),
    ("Energy (tariff price effect)", ["energy"]),
    ("Indirect labour", ["labour"]),
    ("Maintenance", ["maintenance"]),
    ("Inventory, expedite, capex", ["inventory", "expedite", "capex"]),
]
EVID_COLORS = ["E8890C", "F2B134", "F7D774", "2BA3D8", "0078D4", "3DB88B", "8764B8", "7A8CA3"]

# stress tests on the same model (calculator overrides, Base): the case if the benchmark/assumption-only benefits do not materialise
sys.path.insert(0, str(ROOT / "business-case"))
import model as bc_model  # noqa: E402

_BC_ASSUMPTIONS = bc_model.load_assumptions()


def stress(overrides: dict) -> dict:
    r = bc_model.compute(_BC_ASSUMPTIONS, "base", overrides=overrides, with_sensitivity=False)
    return {"npv": r["roi"]["npv"], "payback": r["roi"]["payback_months"], "npv5": r["memo"]["five_year"]["npv"]}


STRESS_SCRAP_ENERGY = stress({"scrap_reduction_pct": 0, "energy_saving_pct": 0})
STRESS_SIM_ONLY = stress({key: 0 for key in ("scrap_reduction_pct", "energy_saving_pct", "maintenance_cost_reduction_pct", "indirect_labour_productivity_gain_pct",
                                              "inventory_reduction_pct", "expedite_reduction_pct", "capex_carry_cost_pct")})
assert abs(stress({})["npv"] - NPV) < 1.0, "model v. outputs.json mismatch: rerun business-case/model.py"

ATTACH_GROUPS = [
    ("AI core", ["ai_foundry", "azure_ml"]),
    ("Data & analytics", ["fabric", "cosmos", "storage", "messaging", "digital_twins"]),
    ("Compute", ["compute"]),
    ("Security", ["security"]),
    ("Monitoring", ["monitoring"]),
    ("Edge & IoT", ["iot_edge"]),
    ("Networking", ["networking"]),
]
ATTACH_KEY = {"AI core": "ai_core", "Data & analytics": "data", "Compute": "compute", "Security": "security", "Monitoring": "monitoring", "Edge & IoT": "edge", "Networking": "networking"}
FAMILY_SHORT = {
    "ai_foundry": "Foundry models & AI Search", "compute": "Container Apps compute", "fabric": "Fabric (RTI, OneLake, Power BI)",
    "security": "Defender, Sentinel, Key Vault", "cosmos": "Cosmos DB", "monitoring": "Azure Monitor / Log Analytics",
    "iot_edge": "IoT Operations & Arc", "digital_twins": "Azure Digital Twins", "networking": "ExpressRoute, VPN, Front Door",
    "storage": "Storage / ADLS", "azure_ml": "Azure Machine Learning", "messaging": "Event Hubs, Event Grid, Service Bus",
}
PALETTE7 = ["E8890C", "2BA3D8", "3DB88B", "8764B8", "FFB900", "0078D4", "7A8CA3"]


def group_series(src: dict, groups, scale) -> dict[str, list[float]]:
    return {name: scale(add(*[src[key] for key in keys])) for name, keys in groups}


CONF_LO, CONF_HI = min(BEN["confidence"].values()) * 100, max(BEN["confidence"].values()) * 100
CONF_RANGE = f"{CONF_LO:.0f}–{CONF_HI:.0f}%"
BEN_BY_GROUP = group_series(BEN["by_category"], EVID_GROUPS, mil)
ACR_BY_GROUP_K = group_series(ACR["by_family"], ATTACH_GROUPS, kil)
DOWNTIME_SHARE_Y3 = BEN["by_category"]["downtime"][2] / BEN_Y[2]
RUN_BY_FAMILY = ACR["run_rate_by_family"]
TOP3_SHARE = sum(sorted(RUN_BY_FAMILY.values(), reverse=True)[:3]) / ACR_RUN
NON_AI_SHARE = 1 - ACR["attach"]["ai_core"]["share"]
OTHER_COSTS = COST["other_by_category"]
CHANGE_3Y = sum(OTHER_COSTS["change_management"])
SENSOR_RETROFIT = RES["sensor_retrofit_share_of_assets"] * RES["assets_per_plant"] * RES["sensor_retrofit_cost_per_asset_usd"]
PILOT, PLANT1, EIGHT, ENT25 = ACR["tiers"]
PER_PLANT_DROP = 1 - ENT25["per_plant"] / EIGHT["per_plant"]
SMART_2030 = 170e9  # MarketsandMarkets, USD (source [6])

# ----------------------------------------------------------------------------------------------------------------------
# sources (numbered in the order listed; slides cite them as [n])
# ----------------------------------------------------------------------------------------------------------------------
SOURCES = [
    ("siemens", "Siemens (Senseye), The True Cost of Downtime 2024, 2024. https://assets.new.siemens.com/siemens/assets/api/uuid:1b43afb5-2d07-47f7-9eb7-893fe7d0bc59/TCOD-2024_original.pdf"),
    ("mckinsey", "McKinsey & Company, Manufacturing: Analytics unleashes productivity and profitability, 2017. https://www.mckinsey.com/capabilities/operations/our-insights/manufacturing-analytics-unleashes-productivity-and-profitability"),
    ("oee", "OEE.com (Vorne Industries), World-Class OEE: Set Targets To Drive Improvement, 2025. https://www.oee.com/world-class-oee/"),
    ("deloitte", "Deloitte and The Manufacturing Institute, US Manufacturing Could Need as Many as 3.8 Million New Employees by 2033 (press release), 2024. https://www.prnewswire.com/news-releases/us-manufacturing-could-need-as-many-as-3-8-million-new-employees-by-2033--according-to-deloitte-and-the-manufacturing-institute-302105892.html"),
    ("wef", "World Economic Forum with McKinsey & Company, Global Lighthouse Network: The Mindset Shifts Driving Impact and Scale, 2025. https://reports.weforum.org/docs/WEF_Global_Lighthouse_Network_2025.pdf"),
    ("mnm", "MarketsandMarkets, Smart Factory Market (2025–2030), 2025. https://www.marketsandmarkets.com/Market-Reports/smart-factory-market-1227.html"),
    ("gvr", "Grand View Research, Smart Factory Market Size & Share, Industry Report 2030, 2025. https://www.grandviewresearch.com/industry-analysis/smart-factory-market"),
    ("eurostat", "Eurostat, Businesses in the manufacturing sector (Statistics Explained, 2022 data), 2024. https://ec.europa.eu/eurostat/statistics-explained/index.php?title=Businesses_in_the_manufacturing_sector"),
    ("xiaomi", "Beijing Changping District Government / Xinhua, Xiaomi Beijing smart factory opens (Chinese-language), 2024. https://www.bj.news.cn/20240219/e9d2a3a267774549815f02f7f741cac6/c.html"),
    ("omnibus", "European Parliament Legislative Train Schedule, Digital Omnibus on AI, 2026. https://www.europarl.europa.eu/legislative-train/package-digital-package/file-digital-omnibus-on-ai"),
    ("aiact", "European Union, Regulation (EU) 2024/1689 (Artificial Intelligence Act), 2024. https://eur-lex.europa.eu/eli/reg/2024/1689/oj"),
    ("literacy", "European Commission, AI Literacy — Questions & Answers, 2026. https://digital-strategy.ec.europa.eu/en/faqs/ai-literacy-questions-answers"),
    ("machinery", "European Union, Regulation (EU) 2023/1230 (Machinery Regulation), 2023. https://eur-lex.europa.eu/eli/reg/2023/1230/oj"),
    ("nis2", "European Union, Directive (EU) 2022/2555 (NIS2), 2022. https://eur-lex.europa.eu/eli/dir/2022/2555/oj"),
    ("iec62443", "ISA, ISA/IEC 62443 series of standards. https://www.isa.org/standards-and-publications/isa-standards/isa-iec-62443-series-of-standards"),
    ("iso13849", "ISO, ISO 13849-1:2023 Safety of machinery — Safety-related parts of control systems, 2023. https://www.iso.org/standard/73481.html"),
    ("iso10218", "IBF Solutions (secondary source), New standards for industrial robots EN ISO 10218-1 and -2, 2026. https://www.ibf-solutions.com/en/seminars-and-news/news/new-standards-for-industrial-robots-en-iso-10218-1-and-2"),
    ("nist", "NIST, AI Risk Management Framework, 2023. https://www.nist.gov/itl/ai-risk-management-framework"),
    ("iotops", "Microsoft Learn, What is Azure IoT Operations? and Azure IoT Operations versions, support, and licensing, 2026. https://learn.microsoft.com/azure/iot-operations/overview-iot-operations · https://learn.microsoft.com/azure/iot-operations/overview-support"),
    ("fabric", "Microsoft Learn, Create and configure operations agents (Fabric Real-Time Intelligence, preview), 2026. https://learn.microsoft.com/fabric/real-time-intelligence/operations-agent"),
    ("foundry", "Microsoft Learn, Agents in Microsoft Foundry, 2026. https://learn.microsoft.com/azure/foundry/agents/overview"),
    ("retail", f"Microsoft, Azure Retail Prices API (queried {RETRIEVED}; swedencentral, westeurope for Digital Twins, USD, pay-as-you-go), 2026. https://learn.microsoft.com/rest/api/cost-management/retail-prices/azure-retail-prices"),
    ("billing", "Microsoft Learn, Plan costs and understand Microsoft Sentinel pricing and billing; Cost breakdown of Eventhouse, 2025–2026. https://learn.microsoft.com/azure/sentinel/billing · https://learn.microsoft.com/fabric/real-time-intelligence/pricing-cost-drivers"),
    ("siemenscopilot", "Siemens, Siemens and Microsoft scale industrial AI (press release), 2024. https://press.siemens.com/global/en/pressrelease/siemens-and-microsoft-scale-industrial-ai"),
    ("aws", "AWS, Preserve access and explore alternatives for Amazon Lookout for Equipment, 2024. https://aws.amazon.com/blogs/machine-learning/preserve-access-and-explore-alternatives-for-amazon-lookout-for-equipment/"),
    ("alz", "Microsoft Learn, Azure landing zones; Azure Well-Architected Framework pillars, 2026. https://learn.microsoft.com/azure/cloud-adoption-framework/ready/landing-zone/ · https://learn.microsoft.com/azure/well-architected/pillars"),
    ("m365", "Microsoft, Power BI pricing (Pro US$14 per user per month), 2026. https://www.microsoft.com/en-us/microsoft-fabric/features/power-bi/pricing · Microsoft Learn, Microsoft Defender for IoT billing (site-based licences, no Azure meter), 2026. https://learn.microsoft.com/azure/defender-for-iot/organizations/billing"),
    ("model", f"SwarmAI, business-case/model.py, assumptions.json ({len(ASSUMP)} assumptions) and outputs.json — model v{OUT['model_version']}, deterministic, stdlib only. 2026."),
]
SRC_NO = {key: i + 1 for i, (key, _) in enumerate(SOURCES)}


def ref(*keys: str) -> str:
    return "".join(f"[{SRC_NO[key]}]" for key in keys)


MODEL_SRC = f"business-case/outputs.json (Base scenario, model v{OUT['model_version']})"

# ----------------------------------------------------------------------------------------------------------------------
# feature status (from FEATURES.md at build time) and product-tour captions
# ----------------------------------------------------------------------------------------------------------------------


def read_features() -> list[dict]:
    txt = (ROOT / "FEATURES.md").read_text(encoding="utf-8")
    seen: dict[str, dict] = {}
    for mt in re.finditer(r"^\|\s*(DF-\d{2})\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*(P\d)\s*\|\s*([^|]+?)\s*\|", txt, re.M):
        fid = mt.group(1)
        if int(fid[3:]) <= 25:
            seen.setdefault(fid, {"id": fid, "name": mt.group(2), "epic": mt.group(3), "prio": mt.group(4), "status": mt.group(5)})
    return [seen[key] for key in sorted(seen)]


FEATURES = read_features()
N_FEATURES = len(FEATURES)
N_DEPLOYED = sum(1 for f in FEATURES if f["status"].startswith("Deployed"))
N_TESTED = sum(1 for f in FEATURES if f["status"].startswith(("Tested", "Deployed")))
EPICS = [
    ("A", "A · Twin & telemetry"),
    ("B", "B · Agent swarm"),
    ("C", "C · Autonomy governance"),
    ("D", "D · Copilot & insight"),
    ("E", "E · Platform & value"),
]


def feature_label(f: dict) -> str:
    return f"{f['id']} {f['name']}"


TOUR_RULES = [  # (word prefixes found in the file name, TOUR key); first match wins
    (("kill",), "kill"), (("ab",), "ab"), (("roi", "calculator", "acr"), "roi"), (("readiness",), "readiness"), (("autonomy", "policy", "dial"), "autonomy"),
    (("approval", "inbox"), "approval"), (("ledger",), "ledger"), (("digest", "shift", "handover"), "digest"), (("copilot", "ask"), "ask"), (("fleet",), "fleet"),
    (("feature",), "feature"), (("twin", "whatif", "what"), "twin"), (("swarm", "agent"), "swarm"), (("predictive", "maintenance"), "pdm"), (("planner", "gantt", "schedul"), "planner"),
    (("quality", "spc", "vision"), "quality"), (("deploy", "iac"), "deploy"), (("observab", "finops"), "obs"), (("control",), "control"), (("value",), "roi"),
]
TOUR = {
    "control": {
        "title": "Control Tower: one live view of the plant, the agents and every approval",
        "caption": "Control Tower (DF-20) — reference implementation over a simulated plant; synthetic data",
        "callouts": ["Live plant map with machine cards: state, health index, alerts", "KPI tiles — OEE, throughput, first-pass yield, energy and $ impact (DF-19)",
                     "Agent activity stream: proposals, what-ifs and decisions as they happen", "Autonomy Dial, approvals inbox and kill switch one click away"],
        "notes": "This is the Control Tower, where the plant manager and the remote operator spend their time. The map shows machine state and health; the KPI tiles are computed by the KPI engine; the activity stream shows the swarm working in the open — proposals, simulations, decisions. Notice the footer: the plant is simulated and says so. Everything on screen is served by the same APIs a production deployment would use. Likely question: can I run it myself? Yes — it is deployed on Azure and reproducible with one command.",
    },
    "swarm": {
        "title": "The swarm in the open: specialists propose, the Supervisor arbitrates, Safety can veto",
        "caption": "Agent swarm view (DF-04 to DF-11) — synthetic data",
        "callouts": ["Each agent shows what it perceives and what it proposes", "Conflicts between proposals are detected and shown", "Utility arbitration: explicit weights and a stored breakdown", "Safety Sentinel veto and policy routing on every bundle"],
        "notes": "Here the swarm is visible rather than hidden behind a chat box. Each specialist lists what it sees and what it proposes; the Supervisor shows where proposals collide — for example maintenance wants a machine stopped while the planner needs it for a rush order — and how the utility arbitration resolved it. The Safety Sentinel's veto is a first-class element, not an afterthought. This transparency is what lets an operations leader trust a decision made at 02:14 without being present.",
    },
    "twin": {
        "title": "Sim-first: every candidate action is rehearsed on a forked twin before it runs",
        "caption": "Digital twin and what-if panel (DF-03) — synthetic data",
        "callouts": ["Live asset graph: hierarchy, state, health and KPIs", "Fork the twin and simulate candidate actions ahead", "KPI deltas per option: due dates, throughput, energy", "The what-if result is attached to the decision record"],
        "notes": "The twin is the safety net. Before a consequential action reaches the plant, the Supervisor forks the twin, applies the candidate bundle and simulates ahead; the panel shows the KPI deltas — missed due dates, throughput, energy. That result travels with the decision into the ledger, so the reason for acting is auditable. If the twin cannot answer, the system fails closed and asks a human. Fidelity matters, which is why calibration from plant history is on the roadmap and shadow mode comes first.",
    },
    "autonomy": {
        "title": "Autonomy Dial: levels L0–L5 are set per decision class, with risk and blast-radius limits",
        "caption": "Autonomy Dial and policy-as-code (DF-12) — synthetic data",
        "callouts": ["One level per decision class — never a global switch", "Risk score blends blast radius, reversibility, safety proximity and exposure", "Policy rules are versioned, tested files — not prompts", "Time-boxed break-glass and the global kill switch"],
        "notes": "This is the trust model made tangible. Each decision class — maintenance scheduling, rescheduling, reorders, quality compensation — has its own level from observe to lights-out. The risk score and the thresholds live in a versioned policy file that a deterministic engine evaluates; promotion is a controlled change with dual control. Break-glass is time-boxed, and the kill switch halts agent-initiated actions within one tick while protective stops stay allowed. Likely question: who decides the level? The OT and cyber lead, with evidence.",
    },
    "approval": {
        "title": "Humans on the loop: an approval card carries options, impact and an SLA timer",
        "caption": "Human-on-the-loop inbox (DF-13) — synthetic data",
        "callouts": ["Options with their what-if impact side by side", "Plain-language explanation and evidence links", "SLA timers with automatic escalation", "Optional Teams card for the shift lead"],
        "notes": "When a decision is above the autonomous threshold it lands here, not in a flood of alarms. Each card shows the options, the simulated impact of each, a plain-language explanation and an SLA timer; if nobody responds, it escalates. The aim is a decision in minutes with the evidence in front of you, recorded in the ledger. For teams that live in Microsoft Teams, the same card can be delivered as an adaptive card; in the production design approvals become actionable there.",
    },
    "ledger": {
        "title": "Decision Ledger: a hash-chained record from observation to outcome, with counterfactuals",
        "caption": "Decision Ledger explorer (DF-14) — synthetic data",
        "callouts": ["Query by asset, agent, time or outcome", "Every entry: rationale, evidence, simulation and counterfactual", "Hash chain with a verify-chain check", "JSONL export for auditors"],
        "notes": "The ledger is what makes autonomy auditable. Every observation, proposal, simulation, decision, action and outcome is appended to a hash-chained record; the verify-chain function proves nothing was altered. Each entry carries the rationale and the counterfactual — what would have happened without the action — which is also how the shift report and the value tracking compute savings. Auditors can export it. In production the segments are anchored to immutable storage so retention and tamper-evidence survive a cloud incident.",
    },
    "ask": {
        "title": "Ask the Factory: answers grounded in KPIs, assets and the ledger, with citations",
        "caption": "Copilot (DF-16) — synthetic data",
        "callouts": ["Natural-language questions over KPIs, assets, ledger and twin", "Answers cite the ledger entries and assets they used", "Streaming responses with tool calls visible", "Read-only by default; proposals go through the approval flow"],
        "notes": "The copilot is how a plant manager interrogates the factory: why did the Supervisor move the CNC-04 jobs, what is driving scrap on line two, what happens if the compressor trips. It calls tools over the KPI engine, the ledger and the twin, and it cites what it used. It is read-only by default; if it proposes an action, that action enters the same policy and approval flow as any agent proposal. Language models interpret and narrate here — they do not bypass the guardrails.",
    },
    "digest": {
        "title": "The 06:00 shift report writes itself from the ledger",
        "caption": "Shift handover and executive digest (DF-17) — synthetic data",
        "callouts": ["What happened, what was decided, what was avoided", "Savings computed from ledger counterfactuals", "Open exceptions and approvals for the incoming shift", "HTML and Markdown export"],
        "notes": "At every shift boundary the system produces the handover: events, decisions, avoided failures, missed or protected due dates and the exceptions that need a human. The numbers come from the ledger counterfactuals, not from a language model's imagination; the model only narrates, and a deterministic template is the fallback. The effect is a five-minute handover instead of a thirty-minute briefing, and an executive digest the COO can read on a phone.",
    },
    "readiness": {
        "title": "Lights-Out Readiness Assessment: a radar score, the gaps and a sequenced roadmap",
        "caption": "Lights-Out Readiness Assessment (DF-15) — synthetic data",
        "callouts": ["Questionnaire plus signals measured from the data feed", "Radar score across data, connectivity, automation and governance", "Gap analysis ranked by effort and value", "Exportable roadmap to pick the first two plants"],
        "notes": "The readiness assessment is our land motion. It combines a short questionnaire with signals measured from the live data — coverage, MTBF, scrap, automation share — and produces a radar score, a ranked gap list and a sequenced roadmap. In an engagement it takes about six weeks and answers the practical questions: which two plants first, what must be fixed before autonomy, and where the OT and cyber lead needs to be involved. It is also where we replace our baseline assumptions with your actuals.",
    },
    "roi": {
        "title": "ROI calculator: editable drivers on the same business-case model as this deck, with a parity check on the page",
        "caption": "Value realization — ROI calculator (DF-21) — synthetic data",
        "callouts": ["Scenario selector and editable drivers, validated server-side against the model range", "Outputs: NPV, ROI, payback, IRR, benefits and costs", "A parity check against the published outputs is shown on the page", "The same model.py that produced every number in this deck"],
        "notes": "This screen is why the numbers in this deck are not slideware. The calculator lets the CFO pick a scenario, change plants, revenue, downtime cost, labour rates or the discount rate and see NPV, ROI and payback immediately. It vendors the same model file as the business case, and the page shows a parity check against the published outputs, so a number cannot drift between the deck and the product. The assumptions behind it are visible and editable. Simulated uplift informs; only a pilot proves.",
    },
    "ab": {
        "title": "A/B replay: the same seeded plant with the swarm off and on, reported with 95% confidence intervals",
        "caption": "Value realization — A/B replay (DF-21) — synthetic data",
        "callouts": ["Inputs: seeds, horizon, fault intensity and human approval latency", "Per-metric improvement with a 95% confidence interval", "Significance is reported, not assumed: intervals that cross zero stay visible", "The result can seed the ROI calculator"],
        "notes": "This is the evidence engine behind the value claim. The replay runs identical seeds and fault schedules twice, swarm off and swarm on, and reports the paired improvement per metric with a 95 percent confidence interval. Look at the honesty of the display: on a short run only some metrics are statistically significant, and intervals that cross zero are shown as they are. Simulation informs mechanisms; it does not prove real-plant results, which is why shadow mode and a pilot follow. The result can seed the ROI calculator.",
    },
    "kill": {
        "title": "Kill switch: one click halts every agent action; only the protective safety stop stays active",
        "caption": "Control Tower with the kill switch engaged (DF-12) — synthetic data",
        "callouts": ["A banner states that agent actions are halted", "Only the protective safety stop remains active", "The Autonomy Dial shows KILL SWITCH ON; release is an explicit act", "Policy keeps denying proposals and the ledger records it"],
        "notes": "The kill switch is the most important button in the product. One click halts every agent-initiated action: the banner says so, the Autonomy Dial shows it, and from then on policy denies proposals while the ledger records each denial. Only the protective safety stop remains active. Releasing it is a separate, explicit act by an authorised role. In the production design the same control sits in the policy enforcement point at the edge, so it works even when the cloud link is down. Likely question: who can press it? Anyone with the right role, instantly.",
    },
    "pdm": {
        "title": "Predictive maintenance: drift scores, failure signatures and remaining-life estimates feed planned work orders",
        "caption": "Predictive Maintenance agent (DF-05) — synthetic data",
        "callouts": ["Per-asset anomaly scores from online baselines (EWMA z-score plus isolation forest)", "Failure signature matched with a confidence — here bearing wear at 93% on PRESS-02", "Vibration and bearing-temperature traces per asset", "Work orders scheduled through the planner, spares and the policy engine"],
        "notes": "Maintenance is where the night-shift story starts. Per-asset baselines are learned online; an exponentially weighted z-score and an isolation-forest score flag drift, and a failure-signature library turns a drift pattern into a named failure mode with a confidence and a remaining-useful-life estimate. Here PRESS-02 shows a bearing-wear signature at 93 percent. The agent does not just alert: it proposes a work order in the next planned window, checks spares and routes the decision through policy. Detection quality on a real plant depends on your sensors and history, which the readiness assessment measures.",
    },
    "planner": {
        "title": "Production planner: a finite-capacity Gantt with a feasibility check, a rationale and a comparison with FIFO",
        "caption": "Production Planner agent (DF-07) — synthetic data",
        "callouts": ["Gantt of the next hours across 14 machines; set-ups hatched, running jobs outlined", "Feasibility check on every schedule", "Planner versus FIFO on the same plant state", "'Why this schedule?' explains the trade-offs in plain language"],
        "notes": "The planner schedules finite-capacity machines with sequence-dependent set-ups, checks feasibility and re-plans on disruption. It always shows its comparison with plain first-in-first-out on the same plant state, plus a plain-language explanation. Be careful with single snapshots: on this particular frame FIFO happens to show no late orders. The claim we make is measured over many seeds in the A/B replay, not read from one picture, and putting the comparison on screen is deliberate transparency rather than a sales device.",
    },
    "quality": {
        "title": "Quality Guardian: SPC charts and process capability per characteristic, with vision inspection and human review",
        "caption": "Quality Guardian agent (DF-06) — synthetic data",
        "callouts": ["Process capability per asset: Cpk, shift, compensation and rule violations", "X-bar chart with Western Electric rule checks", "Vision inspection on synthetic part images with a multimodal model", "Low-confidence calls wait in a human review queue"],
        "notes": "Quality Guardian watches every measured characteristic with statistical process control: capability, shift, X-bar and range charts and the Western Electric rules. On a drift it compensates within bounds, contains the lot and tells Maintenance. Vision inspection uses a multimodal model on synthetic part images, and anything below a confidence threshold goes to a human review queue whose verdict feeds back into the statistics. The images here are generated, not real parts, and the interface says so. In production, inline inspection would run on edge GPUs.",
    },
    "obs": {
        "title": "Observability and FinOps: latency by feature, agent decision metrics and an AI-spend meter with a daily cap",
        "caption": "Observability and FinOps (DF-24) — live instance, synthetic data",
        "callouts": ["Uptime, request counts, server errors and event volume at a glance", "API latency by feature (p50, p95, mean) and agent decision-cycle time", "AI spend today against a daily cap that fails closed", "OpenTelemetry to Application Insights over managed identity"],
        "notes": "A system that decides on its own must be observable, and its AI cost must be bounded. This view shows the live instance: request counts and latency by feature, the decision-cycle time of each agent and what each agent proposed, executed or had vetoed. It also shows today's estimated AI spend against a daily cap that fails closed, and confirms that telemetry reaches Application Insights over managed identity. These are the meters a customer's finance team would use to track the cost per plant-day that our business-case model forecasts.",
    },
    "deploy": {
        "title": "Deployed on Azure: Bicep and azd, keyless managed identity, local keys disabled — and honest about the sandbox",
        "caption": "IaC and deployment view (DF-25) — live instance in Sweden Central",
        "callouts": ["Runtime facts of the live instance: region, build, model deployments", "Infrastructure as code: Bicep and azd — one command up, one command down", "Keyless posture: managed identity; local authentication disabled on Cosmos DB and AI, shared key off on storage", "Live dependency checks through /readyz"],
        "notes": "Because the reference implementation is real, it can show its own deployment. This view reports the live instance: region Sweden Central, the build, the model deployments and dependency checks. The whole stack is defined as code in Bicep and deployed with azd, one command up and one command down. The security posture is keyless: a user-assigned managed identity, with local authentication disabled on Cosmos DB and the AI account and shared-key access disabled on storage. This is a sandbox demonstration; a production landing zone adds private endpoints, policy and network isolation.",
    },
    "fleet": {
        "title": "Fleet view: benchmark plants and reuse failure signatures across sites",
        "caption": "Multi-plant fleet (DF-22) — synthetic data",
        "callouts": ["Three simulated plants with different profiles", "Fleet KPIs and plant-to-plant benchmarking", "Failure signatures learned in one plant reused in another", "Where to roll out next, and why"],
        "notes": "Scale is where the economics compound. The fleet view compares plants with different profiles, benchmarks their KPIs and shows playbook sharing: a failure signature learned at one plant becomes available at the others. For the reference customer, each additional plant adds about the same benefit for a fraction of the first plant's cost because the platform foundation and integration templates are reused. This is the view the COO uses to decide the next cohort of plants.",
    },
    "feature": {
        "title": "Feature map: every Release-1 feature, its status and the screen that proves it",
        "caption": "Feature map (all 25 Release-1 features) — generated from the live feature registry",
        "callouts": ["One row per feature DF-01 to DF-25 from the registry API", "Status per feature and a link to its screen", "Everything in the PRD is real software, not slideware", "Synthetic-data indicator visible on every page"],
        "notes": "The feature map is rendered from the live registry API, so it cannot drift from the code. Each of the 25 Release-1 features has a status and a link to the screen that demonstrates it. Where something is simulated — the plant, the MES, the grid feeds — the interface says so. That honesty is deliberate: the reference implementation proves behaviour end to end, while production edge and cloud services plug in behind the same interfaces.",
    },
}


def label_end_points(slide, fmt, positions: dict, colors: list[str]) -> None:
    """Data label on the last point of each series of the (single) chart on `slide`."""
    for shape in slide.shapes:
        if getattr(shape, "has_chart", False) and shape.has_chart:
            for si, ser in enumerate(shape.chart.plots[0].series):
                vals = list(ser.values)
                dl = ser.points[len(vals) - 1].data_label
                dl.has_text_frame = True
                dl.text_frame.text = fmt(vals[-1])
                dl.position = positions.get(si, XL_LABEL_POSITION.ABOVE)
                run = dl.text_frame.paragraphs[0].runs[0]
                run.font.size = Pt(12)
                run.font.bold = True
                run.font.color.rgb = RGBColor.from_string(colors[si])


def tour_meta(path: Path) -> dict:
    stem = re.sub(r"^\d+[-_ ]*", "", path.stem).lower()
    pretty = stem.replace("-", " ").replace("_", " ").title()
    words = [w for w in re.split(r"[-_ ]+", stem) if w]
    for prefixes, key in TOUR_RULES:
        if any(w == p or (len(p) > 2 and w.startswith(p)) for w in words for p in prefixes):
            return TOUR[key]
    return {
        "title": f"Product tour: {pretty}",
        "caption": f"{pretty} — reference implementation, synthetic data",
        "callouts": None,
        "notes": f"This screen from the reference implementation shows {pretty.lower()}. The plant behind it is simulated and the interface says so; the software — agents, policy engine, ledger, KPI engine and APIs — is real and deployed on Azure. Use it to ground the discussion in something tangible: ask the audience what they would want to see here for their own plant, and note the answers as input to the pilot design. The screens are captured from the live application, not mock-ups.",
    }


def tour_files() -> list[Path]:
    if not SCREENS.exists():
        return []
    return sorted(p for p in SCREENS.iterdir() if p.suffix.lower() in (".png", ".jpg", ".jpeg") and not p.name.startswith(("_", ".")))


def add_screens(d: Deck, files: list[Path]) -> None:
    for f in files:
        meta = tour_meta(f)
        d.screenshot(meta["title"], f, caption=meta["caption"], callouts=meta.get("callouts"),
                     takeaway=meta.get("takeaway"), notes=meta["notes"],
                     source="Screenshot of the reference implementation (simulated plant, synthetic data) — production edge and cloud services plug in behind the same interfaces")


# ----------------------------------------------------------------------------------------------------------------------
# main storyline
# ----------------------------------------------------------------------------------------------------------------------
def main_slides(d: Deck, azure: bool) -> None:
    # 1 — title ------------------------------------------------------------------------------------------------------
    d.title_slide(
        "The factory that runs itself",
        "Nightshift — an Azure-native swarm of governed AI agents for lights-out manufacturing",
        tagline="SWARMAI · DARK FACTORY · EXECUTIVE BRIEFING",
        meta="November 2026 · Reference customer: Contoso Industrial Group (fictional) · Illustrative — validate with customer data",
        notes="Welcome, and let me frame the next half hour. Nightshift is a swarm of governed AI agents that runs the night shift of a factory: it plans, maintains, protects quality, feeds materials and saves energy within rules your people set, and it proves its own value. Everything you will see is an Azure-native reference implementation running over a simulated plant. The business case is built on public benchmarks for a fictional customer, Contoso Industrial Group, and is meant to be replaced with your own actuals. We will cover why now, how it works and stays safe, the numbers, and a concrete first step.")

    # 2 — executive summary --------------------------------------------------------------------------------------------
    d.set_section("Executive summary")
    d.bullets(
        f"Governed AI agents run the night shift; the Base case pays back in {PAYBACK:.0f} months",
        [f"**Problem** — unplanned downtime costs the largest manufacturers about 11% of revenue; the average large plant loses 326 hours a year {ref('siemens')}",
         "**Product** — seven specialist AI agents and a Shift Supervisor, grounded in a live digital twin of the plant",
         "**Trust** — every action rehearsed on the twin first; autonomy earned per decision class; every decision in a tamper-evident ledger",
         f"**Value** — Contoso, 8 plants rolled out 2 → 5 → 8: ten risk-adjusted benefit levers against all-in cost (Azure, hardware, integration, people, licences)",
         "**Proof** — simulation A/B, then shadow mode, then a measured pilot; only Finance-validated benefits count",
         "**Ask** — a six-week Lights-Out Readiness Assessment, then a two-plant pilot"],
        side_title="Headline numbers · Base case",
        side_items=[f"3-year benefit **{m(BEN3)}** vs cost **{m(COST3)}**", f"NPV **{m(NPV)}** at a 10% discount rate", f"ROI **{ROI_PCT:.0f}%** · payback **{PAYBACK:.0f} months**",
                    f"NPV range: **{m(HC['npv'])}** to **{m(HU['npv'])}** (Conservative to Upside, which adds optional modules)", f"Steady state: **{m(SS_BEN)}** of benefit a year at 8 plants",
                    f"Azure run cost: **{m(ACR_RUN, 2)}** a year at 8 plants (list price)"],
        size=16,
        takeaway="The case is a hypothesis built on public benchmarks; the assessment replaces them with Contoso actuals.",
        source=f"Source: {MODEL_SRC}; Siemens 2024 {ref('siemens')}. Risk-adjusted and illustrative — validate with customer data.",
        notes=f"Open with the decision we are asking for: a six-week readiness assessment and, if the evidence holds, a two-plant pilot. The argument in one breath: unplanned downtime is the largest controllable loss in discrete manufacturing, and Nightshift puts a governed swarm of AI agents on the night shift. For Contoso's eight plants the Base case returns {m(BEN3)} of risk-adjusted benefit against {m(COST3)} of cost: an NPV of {m(NPV)}, ROI of {ROI_PCT:.0f}% and payback in {PAYBACK:.0f} months. The range matters: Conservative is {m(HC['npv'])}, Upside {m(HU['npv'])} once optional expansion modules are switched on. Likely question: how firm are these numbers? Public benchmarks plus visible assumptions; the assessment replaces them with Contoso actuals.")

    # 3 — why now -----------------------------------------------------------------------------------------------------
    d.set_section("Why now")
    d.kpi_cards(
        "Why now: costly downtime, scarce labour and mature AI make adaptive autonomy practical",
        [{"value": "$1.4T", "label": "Yearly cost of unplanned downtime", "sub": "11% of revenue at the 500 largest companies · Siemens 2024"},
         {"value": "326 h", "label": "Lost per large plant, per year", "sub": "27 h a month and 25 incidents a month · Siemens 2024"},
         {"value": "30–50%", "label": "Less downtime with predictive maintenance", "sub": f"McKinsey 2017 · our Base case assumes only {pc(RES['downtime_reduction_pct'])}"},
         {"value": "≈60% vs 85%", "label": "Typical vs world-class OEE", "sub": "OEE.com · headroom beyond availability"},
         {"value": "1.9M", "label": "US factory jobs that could go unfilled by 2033", "sub": "of 3.8M needed · Deloitte and Manufacturing Institute 2024"},
         {"value": "$104B → $170B", "label": "Smart-factory market, 2025 → 2030", "sub": "MarketsandMarkets · Grand View: $155B → $273B"}],
        columns=3,
        takeaway="Dark factories exist but are built greenfield and rigid; brownfield variability needs a cognitive layer.",
        source=f"Sources: Siemens 2024 {ref('siemens')}; McKinsey 2017 {ref('mckinsey')}; OEE.com {ref('oee')}; Deloitte/MI 2024 {ref('deloitte')}; MarketsandMarkets {ref('mnm')}; Grand View {ref('gvr')}; Xiaomi Changping {ref('xiaomi')}.",
        notes="Four forces make this timely. First, downtime is expensive and persistent: Siemens puts it at 1.4 trillion dollars a year across the world's 500 largest companies, 11% of revenue, and 326 hours a year for the average large plant. Second, most plants run near 60% OEE against an 85% world-class benchmark. Third, labour is scarce: up to 1.9 million US manufacturing jobs could go unfilled by 2033. Fourth, the technology is ready and the market is investing, from Xiaomi's Changping plant, built for robots to do most work around the clock, to a smart-factory market forecast at 104 to 170 billion dollars. Dark factories are built greenfield and rigid; brownfield plants need a cognitive layer.")

    # 4 — vision ------------------------------------------------------------------------------------------------------
    d.set_section("The solution")
    d.big_statement(
        "The vision: a plant that adapts at 02:00 within rules people set — and proves it",
        "A factory that runs itself on the night shift — and can prove it was safe, explain every decision and show the money.",
        sub="Agents absorb variability — a failing bearing, a late supplier, a rush order, a tariff spike. Humans move from in the loop to on the loop: they set goals and guardrails and review exceptions.",
        bullets=["**Sim-first** — every consequential action is rehearsed on a forked digital twin before it touches the plant",
                 "**Earned autonomy** — Autonomy Dial L0–L5 per decision class, policy-as-code, blast-radius limits and a kill switch",
                 "**Explainable swarm** — conflicts arbitrated by explicit utility; every decision in a tamper-evident ledger",
                 "**Measured value** — counterfactual A/B replay feeds an ROI and Azure-consumption calculator",
                 "**Land motion** — a Lights-Out Readiness Assessment picks the first plants and closes the gaps",
                 "**Azure-native and open** — OPC UA, MQTT and ISA-95; connectors for MES, ERP and SCADA vendors"],
        notes="This is the vision in one sentence: a factory that runs itself on the night shift, and can prove it was safe, explain every decision and show the money. Classic lights-out automation breaks on variability, so agents absorb it; people move from in the loop to on the loop and handle exceptions rather than babysit machines. Six things make it different: sim-first rehearsal on a twin, earned autonomy per decision class, an explainable swarm with a tamper-evident ledger, measured value through counterfactual replay, a readiness assessment as the land motion, and an Azure-native, open design. What it is not: a safety system, a MES or SCADA replacement, or a worker-monitoring tool.")

    # 5 — the swarm ------------------------------------------------------------------------------------------------------
    d.hub_spoke(
        "The swarm: seven specialists propose, one supervisor decides, safety can always say no",
        {"title": "Shift Supervisor", "sub": "arbitration · what-if · policy routing"},
        [{"title": "Planner", "sub": "finite-capacity schedule · rush orders"}, {"title": "Maintenance", "sub": "remaining life · planned-window work orders"},
         {"title": "Quality", "sub": "SPC · bounded compensation · vision"}, {"title": "Materials", "sub": "inventory · spares · AMR dispatch"},
         {"title": "Energy", "sub": "tariff- and carbon-aware load shifting"}, {"title": "Process", "sub": "bounded parameter trials with rollback"},
         {"title": "Safety Sentinel", "sub": "veto power · protective stops"}],
        takeaway="Conflicting objectives are arbitrated by explicit, auditable utility — not by hidden prompts.",
        source="Source: SwarmAI PRD §6.2 and FEATURES DF-04 to DF-11 (reference implementation).",
        notes="Seven specialists each perceive, propose and explain: Planner, Maintenance, Quality, Materials, Energy, Process and the Safety Sentinel. They never act alone. The Shift Supervisor merges their proposals, detects conflicts, asks the digital twin what would happen, and arbitrates by an explicit utility function whose weights and breakdown are stored. The Safety Sentinel holds a veto that no other agent can override. Everything is routed through the policy engine and recorded in the ledger. Likely question: is this just language-model agents talking? No. The core is deterministic and tested; language models interpret, propose and narrate.")

    # 6 — the night-shift story -------------------------------------------------------------------------------------------
    d.comparison(
        "At 02:14 one bearing, two outcomes: a 3.5-hour breakdown becomes a planned fix",
        "Before — reactive",
        ["Drift stays under the fixed alarm limit; nobody is watching at 02:14",
         f"Bearing on CNC-04 fails mid-run about 14 hours later: ~{BREAKDOWN_H:.1f} h unplanned stop",
         "Supervisor re-plans by phone and spreadsheet; a rush order slips",
         "Emergency repair and premium freight for the spare",
         f"≈ {k(BREAKDOWN_USD, 1)} of line time lost ({BREAKDOWN_H:.1f} h × {k(LINE_H, 1)} per line-hour)"],
        "After — swarm on the loop",
        ["02:14 Maintenance flags the drift: remaining life ≈\u00a014\u00a0h",
         "02:15 Supervisor rehearses on the twin: move jobs to CNC-05, service CNC-04 at 05:30 → 0 missed due dates",
         "02:16 Safety: nobody in the zone; policy: risk 31, L4 auto-approve",
         "05:30 Planned fix in the changeover; 06:00 shift report with the ledger trail",
         f"≈ {k(BREAKDOWN_USD, 1)} avoided and one failure prevented (illustrative)"],
        takeaway=f"One avoided breakdown covers about {DAYS_COVERED:.0f} plant-days of Azure run cost (≈ ${ACR_DAY:,.0f} per plant-day).",
        source=f"Illustrative narrative. Cost per line-hour {k(LINE_H, 1)} = derived Base-case downtime cost; Azure per plant-day = run-rate ÷ 8 plants ÷ 365 ({MODEL_SRC}).",
        notes=f"Walk through 02:14. Maintenance sees bearing temperature drift on CNC-04 and estimates remaining life at about 14 hours. The Supervisor asks the twin: move the job set to CNC-05 and service CNC-04 in the 05:30 changeover, with zero missed due dates. Materials stages the spare, Energy shifts compressor load, Safety confirms nobody is in the zone. Policy classifies it as low risk, so it auto-approves at level four and the ledger records the whole chain. At 06:00 the plant manager reads one paragraph. Illustratively, a 3.5-hour breakdown at about {k(LINE_H, 1)} per line-hour is worth roughly {k(BREAKDOWN_USD, 1)}.")

    # 7 — sim-first safety and Autonomy Dial -----------------------------------------------------------------------------
    w, gap = 1.76, 0.308
    steps = [("Agents propose", "action · rationale · evidence · risk", "box", "E8890C"), ("What-if on the twin", "fork state, simulate each option", "box", "2BA3D8"),
             ("Arbitrate by utility", "explicit weights, stored", "box", "E8890C"), ("Safety Sentinel", "veto over any action", "dark", "E8890C"),
             ("Policy engine", "level · risk · blast radius", "box", "2BA3D8"), ("Execute or ask", "auto-run, or human inbox", "box", "E8890C")]
    levels = [("L0 · Observe", "analyse and log only", "7A8CA3", "ghost"), ("L1 · Recommend", "humans execute", "7A8CA3", "ghost"),
              ("L2 · Approve-to-act", "default for new decision classes", "2BA3D8", "ghost"), ("L3 · Act-with-veto", "short veto window, humans notified", "2BA3D8", "ghost"),
              ("L4 · Auto-approve", "inside guardrails and blast radius", "E8890C", "dark"), ("L5 · Lights-out", "widest envelope; humans handle exceptions", "E8890C", "dark")]
    nodes = [{"id": f"s{i}", "x": i * (w + gap), "y": 0.0, "w": w, "h": 1.2, "title": t, "sub": s, "kind": kd, "color": c} for i, (t, s, kd, c) in enumerate(steps)]
    nodes.append({"id": "ledger", "x": 0, "y": 1.45, "w": 12.1, "h": 0.5, "title": "Decision Ledger: hash-chained record from observation to outcome, with the counterfactual", "kind": "ghost"})
    nodes.append({"id": "dial", "x": 0, "y": 2.2, "w": 12.1, "h": 0.42, "title": "Autonomy Dial — set per decision class, never globally; promotion needs evidence and OT/Cyber sign-off", "kind": "dark"})
    nodes += [{"id": f"l{i}", "x": i * (w + gap), "y": 2.8, "w": w, "h": 1.5, "title": t, "sub": s, "color": c, "kind": kd} for i, (t, s, c, kd) in enumerate(levels)]
    edges = [{"from": f"s{i}", "to": f"s{i + 1}"} for i in range(5)] + [{"from": f"l{i}", "to": f"l{i + 1}"} for i in range(5)]
    d.diagram(
        "Trust is engineered: rehearse first, then earn autonomy one decision class at a time",
        nodes, edges,
        takeaway="Certified safety functions stay in certified controllers — the swarm can add protection, never relax it.",
        source="Source: SwarmAI PRD §6.3–6.4 and ARCHITECTURE §6.5–6.6; ISO 13849-1 boundary " + ref("iso13849") + ".",
        notes="Two ideas build trust. Sim-first: no consequential action reaches the plant until it has been rehearsed on a forked copy of the twin; if the twin cannot answer, the system fails closed to human approval. Earned autonomy: the Autonomy Dial runs from observe to lights-out and is set per decision class, so maintenance scheduling can reach level four while process-parameter changes stay at three. Promotion needs shadow-mode evidence and sign-off from the OT and cyber lead. Safety-rated functions remain in certified controllers; the Sentinel can only add protection. Likely question: who can switch it off? Anyone with the right role, instantly, through the kill switch.")

    # 8 — capability map ----------------------------------------------------------------------------------------------------
    groups = []
    for letter, name in EPICS:
        items = [feature_label(f) for f in FEATURES if f["epic"].startswith(letter + " ")]
        groups.append({"name": name, "items": items})
    if N_DEPLOYED:
        tk = f"{N_DEPLOYED} of {N_FEATURES} Release-1 features are deployed and smoke-tested on Azure over a simulated plant; production edge and cloud services plug in behind the same interfaces."
        status_note = f"At build time {N_DEPLOYED} of {N_FEATURES} features are deployed and smoke-tested on Azure."
    else:
        tk = "Release 1 is a reference implementation over a simulated plant; production edge and cloud services plug in behind the same interfaces."
        status_note = "The appendix lists the current status of every feature."
    d.capability_map(
        "Twenty-five Release-1 features in five epics cover the loop from telemetry to ROI",
        groups, subtitle=tk, source="Source: FEATURES.md (feature IDs, names and status board).",
        notes=f"Release 1 contains 25 features in five epics: the plant twin and telemetry; the agent swarm; autonomy governance; copilot and insight; and the platform and value layer. Together they close the loop from a sensor reading to a decision, an audit entry and a number on the CFO's slide. P0 features are the ones the demonstration cannot work without. All of it is built on Azure over a simulated plant behind production-style interfaces, so edge and cloud services can be swapped in per plant. {status_note}")
    # 9 — product tour (auto-included from deck/assets/screens/) ------------------------------------------------------------
    tour = tour_files()
    if tour:
        d.set_section("Product tour · reference implementation")
        add_screens(d, tour[:MAX_TOUR_IN_MAIN])

    # 10 — Azure reference architecture -----------------------------------------------------------------------------------------
    d.set_section("Azure architecture and trust")
    d.architecture(
        "Azure reference architecture: the edge keeps safety loops local, the cloud adds intelligence",
        [{"name": "Experience", "items": [{"title": "Control Tower", "sub": "Container Apps · Front Door"}, {"title": "Teams approvals", "sub": "adaptive cards"}, {"title": "Power BI", "sub": "Direct Lake on OneLake"}]},
         {"name": "Agents & AI", "items": [{"title": "Supervisor + 7 agents", "sub": "Container Apps"}, {"title": "Foundry models", "sub": "Agent Service · MCP tools"}, {"title": "Azure ML · AI Search", "sub": "ONNX to the edge"}, {"title": "Policy engine", "sub": "signed bundles"}]},
         {"name": "Data & twin", "items": [{"title": "Fabric RTI + OneLake", "sub": "Eventhouse · Activator"}, {"title": "Azure Digital Twins", "sub": "semantic graph"}, {"title": "Cosmos DB", "sub": "state · ledger index"}, {"title": "Blob WORM", "sub": "ledger anchors"}]},
         {"name": "Edge (per plant)", "items": [{"title": "Azure IoT Operations", "sub": "OPC UA · MQTT UNS"}, {"title": "Arc-enabled Kubernetes", "sub": "K3s · AKS on Azure Local"}, {"title": "Local ONNX inference", "sub": "anomaly · vision"}, {"title": "Safety Sentinel + PEP", "sub": "protective loops"}]},
         {"name": "Plant (OT)", "items": [{"title": "PLCs · SCADA · MES", "sub": "Purdue levels 0–3"}, {"title": "Machines · sensors", "sub": "CNC · presses · AMRs"}, {"title": "Certified safety", "sub": "stays authoritative"}]}],
        side={"name": "Cross-cutting", "items": ["Entra ID + Agent ID", "Key Vault · Defender · Sentinel", "Azure Monitor", "Azure Policy · landing zone", "ExpressRoute · Private Link"]},
        takeaway="Outbound-only, Purdue-aligned connections; protective loops never depend on the cloud link.",
        source=f"Source: SwarmAI ARCHITECTURE §3–§5; Microsoft Learn: Azure IoT Operations {ref('iotops')}, Fabric Real-Time Intelligence {ref('fabric')}, Foundry Agent Service {ref('foundry')}, landing zones {ref('alz')}.",
        notes="Read the picture from the bottom. Plants stay in the OT zone; an Azure IoT Operations cluster on Arc-enabled Kubernetes sits in the DMZ, speaks OPC UA and MQTT, hosts the Unified Namespace and runs the safety-critical checks locally. Connections are outbound-only into Azure: Event Hubs to Fabric Real-Time Intelligence for streaming analytics, Digital Twins for the semantic model, Cosmos DB for agent state and the ledger index. Agents run on Container Apps with Foundry models; Entra ID, Key Vault, Defender and Monitor span every layer. If the cloud link drops, protective loops keep running.")

    # 11 — responsible AI, security and compliance --------------------------------------------------------------------------------
    d.table(
        "Responsible by design: human oversight, evidence and OT-grade security — without over-claiming",
        ["Area", "How Nightshift enforces it", "Frameworks it supports (no certification claimed)"],
        [["Human oversight", "Autonomy Dial per decision class, approvals with SLA timers, dual-controlled break-glass, global kill switch", f"EU AI Act oversight discipline {ref('aiact')}; NIST AI RMF {ref('nist')}"],
         ["Traceability", "Hash-chained Decision Ledger with rationale and counterfactual; immutable anchors; exportable", f"EU AI Act record-keeping {ref('aiact')}; ISO/IEC 42001 evidence"],
         ["OT security", "Outbound-only edge, zones and conduits, policy-gated control API, no direct cloud-to-PLC writes", f"IEC 62443 {ref('iec62443')}; NIS2 covers most manufacturers {ref('nis2')}"],
         ["Identity and data", "Entra ID and managed identities, least-privilege RBAC, agent identities, private networking, regional residency", "ISO/IEC 27001 controls supported; certification belongs to the operator"],
         ["Safety boundary", "Safety functions stay in certified controllers; the Sentinel can only veto or stop, never relax", f"ISO 13849-1 {ref('iso13849')}; ISO 10218 {ref('iso10218')}; Machinery Regulation from 20 Jan 2027 {ref('machinery')}"],
         ["Regulatory timing", "No individual-worker monitoring; AI-literacy material for operators; legal review per deployment", f"AI Act: high-risk duties deferred to Dec 2027 / Aug 2028 {ref('omnibus')}; Art. 4 literacy since Feb 2025 {ref('literacy')}"]],
        col_weights=[1.35, 4.2, 4.0], takeaway="We design to these frameworks and keep claims factual: no certification, no safety rating, no real-plant results from simulation.",
        source="Source: SwarmAI PRD §16 and ARCHITECTURE §7. Planning guidance, not legal advice.",
        notes="We design to these frameworks and keep our claims narrow. Human oversight comes from the Autonomy Dial, approvals and the kill switch. Traceability comes from the hash-chained ledger. OT security follows IEC 62443 zones and conduits, outbound-only connections and no direct cloud-to-PLC writes. Functional safety stays in certified controllers under ISO 13849 and ISO 10218. On regulation: the EU AI Act's high-risk duties were deferred to December 2027 and August 2028, the Machinery Regulation applies from January 2027, and NIS2 covers most manufacturers. We claim support, not certification, and no safety rating. This is planning guidance, not legal advice.")

    # 12 — measured value: four stages of evidence -------------------------------------------------------------------------------
    d.set_section("Business case")
    d.process(
        "Value is measured in four stages, and only Finance-validated benefits are banked",
        [{"title": "Simulation A/B", "body": ["**Method** — same seeds, swarm OFF vs ON, ≥ 10 seeds, paired deltas with 95% confidence intervals", "**Proves** — mechanisms, not real-plant results", "**When** — available today in the reference implementation", "**Gate** — confidence interval excludes zero"]},
         {"title": "Shadow mode", "body": ["**Method** — agents run on historian replay and live feeds at L0–L1; compare proposals with what humans did", "**Replaces** — baselines with Contoso actuals", "**When** — about 8 weeks per decision class (example)", "**Gate** — OT/Cyber sign-off to move up a level"]},
         {"title": "Pilot A/B", "body": ["**Method** — two plants or lines with matched controls, pre-registered metrics, difference-in-differences", "**Replaces** — confidence factors with measured realisation", "**When** — 3–6 months", "**Gate** — Finance validates the uplift"]},
         {"title": "Production tracking", "body": ["**Method** — ledger counterfactuals every shift, quarterly Finance validation", "**Output** — quarterly re-forecast of benefits and " + ("ACR" if azure else "Azure run cost"), "**When** — continuous", "**Gate** — benefits recognised only after sign-off"]}],
        takeaway=f"Base case NPV {m(NPV)} and payback {PAYBACK:.0f} months stay a hypothesis until stage 3 replaces the confidence factors with measurements.",
        source="Source: SwarmAI PRD §10.2 (measurement plan); counterfactual A/B replay in the reference implementation (DF-21).",
        notes="Value is a hypothesis until it is measured, so we stage the evidence. Stage one is simulation A/B: identical seeds, swarm off versus on, at least ten seeds, with confidence intervals. It proves mechanisms, not real-plant results. Stage two is shadow mode on your data: agents propose, humans act, and we compare. Stage three is a pilot with matched controls and pre-registered metrics. Stage four is production tracking with quarterly Finance validation. Only then are benefits banked. Each stage replaces assumptions in the model with measurements: baselines first, then confidence factors. Likely question: why not trust the simulation? Because it informs; only a pilot proves.")

    # 12b — what the simulation shows (and does not): the A/B table, reported without selection ----------------------------------
    ab_pct = lambda name: (re.search(r"\(([\u2212-]?\d+) %", AB_BY_NAME[name][3]) or [None, "?"])[1].replace("-", MINUS)  # noqa: E731
    ab_rows = [[r[0], r[1], r[2], r[3], r[4].replace(" (better = positive)", ""), "Yes" if r[6].lower().startswith("yes") else "No"] for r in AB_ROWS]
    d.table(
        f"The simulation proves the mechanism for downtime and OEE, and shows no proven effect on scrap, OTIF or absolute energy use",
        ["Metric (per 8-hour window)", "Swarm OFF", "Swarm ON", "Improvement", "95% CI", "Significant"],
        ab_rows, col_weights=[3.6, 1.1, 1.1, 2.0, 2.3, 1.2], align=["left", "right", "right", "right", "right", "center"],
        highlight_rows=[i for i, r in enumerate(ab_rows) if r[5] == "Yes"],
        subtitle=f"{AB_SEEDS} seeds, swarm OFF vs ON on identical seeds, order book and fault schedule · {AB_SIG} of 12 metrics significant (95% interval excludes zero)",
        takeaway="Simulation evidence on synthetic assumptions, not a customer guarantee. The energy benefit is a lower price per kWh where tariffs vary, not lower consumption.",
        source="Source: REPORT-TEST-AND-DEPLOYMENT.md §4.3 (live A/B replay, window 'late', approvals answered after 20 sim-min); all twelve metrics shown, none selected.",
        notes=(f"This is the honest version of the simulation result. Over {AB_SEEDS} seeds, with identical seeds and faults for both arms, six of twelve metrics improve significantly: unplanned downtime falls {ab_pct('Unplanned downtime (h)')} percent, OEE rises 13.5 points, late orders and tardiness fall, total loss falls, and the effective energy price is ten percent lower. "
               "Three things do not show up. Absolute energy cost is slightly higher, because less downtime means more machine-hours running and the energy agent moves load to cheaper hours rather than cutting kWh. Scrap and OTIF show no significant effect. "
               "So the simulation proves mechanisms, not Contoso results, and we claim only what the intervals support."))

    # 12c — evidence classes: how much of the case rests on the simulation, and the stress tests ---------------------------------------------
    d.chart(
        f"Only {pc(SIM_SHARE)} of the benefit is simulation-backed; without scrap and energy savings the NPV falls from {m(NPV)} to {m(STRESS_SCRAP_ENERGY['npv'])}",
        ["Base case", "Scrap and energy benefits at zero", "Only simulation-supported benefits"],
        {"3-year NPV (US$ M)": [round(NPV / 1e6, 2), round(STRESS_SCRAP_ENERGY["npv"] / 1e6, 2), round(STRESS_SIM_ONLY["npv"] / 1e6, 2)]},
        kind="column", number_format='$#,##0.0"M"', labels=True, legend=False, colors=["E8890C"],
        commentary=[f"**{pc(SIM_SHARE)}** of the 3-year benefit (**{m(SIM_BEN3)}**) sits in categories the simulation supports: downtime, throughput / OEE and late-delivery cost",
                    f"**{pc(1 - SIM_SHARE)}** rests on benchmarks and assumptions: scrap, energy, labour, maintenance, inventory, expedite and capex — each haircut by a confidence factor",
                    f"Payback stretches from **{PAYBACK:.0f}** to **{STRESS_SCRAP_ENERGY['payback']:.0f} months** without scrap and energy, and to **{STRESS_SIM_ONLY['payback']:.0f} months** if only the simulation-supported benefits are real (5-year NPV {m(STRESS_SIM_ONLY['npv5'])})",
                    "Shadow mode and the pilot replace these assumptions with your measurements"],
        commentary_title="Evidence classes",
        takeaway="The case does not depend on any single benefit, but it does depend on measuring the benchmark-based ones on your data.",
        source=f"Source: {MODEL_SRC} re-run with overrides (calculator): scrap_reduction_pct and energy_saving_pct = 0; all benchmark-only levers = 0. Illustrative stress tests, not forecasts.",
        notes=(f"We split the benefit by evidence strength. About {pc(SIM_SHARE)} of the three-year benefit sits in downtime, throughput and late-delivery cost, the categories the simulation supports. The rest comes from published benchmarks and our assumptions, each with a confidence factor. "
               f"As a stress test we run the same model with scrap and energy benefits at zero: NPV is {m(STRESS_SCRAP_ENERGY['npv'])} and payback {STRESS_SCRAP_ENERGY['payback']:.0f} months. With only the simulation-supported benefits, NPV is {m(STRESS_SIM_ONLY['npv'])} over three years and positive over five. "
               "That is exactly why we stage the evidence: shadow mode and a pilot on your plants replace benchmarks with measurements before benefits are banked. Which benefit would you drop first? Energy: it is a price effect that needs a varying tariff."))

    # 13 — ROI 1: benefits by category by year ----------------------------------------------------------------------------------
    d.chart(
        f"Benefits build from {m(BEN_Y[0])} to {m(BEN_Y[2])} a year as plants go live, led by unplanned downtime",
        YEARS, BEN_BY_GROUP, kind="stacked", number_format='$#,##0.0"M"', labels=False, colors=PALETTE7,
        commentary=[f"**{m(BEN3)}** risk-adjusted benefit over 3 years; **{m(SS_BEN)}** a year once all 8 plants are mature",
                    f"Plants live at year-end: **{LIVE[0]} → {LIVE[1]} → {LIVE[2]}**; benefits ramp {pc(RES['benefit_ramp'][0])} / {pc(RES['benefit_ramp'][1])} / {pc(RES['benefit_ramp'][2])} after go-live",
                    f"Downtime is **{pc(DOWNTIME_SHARE_Y3)}** of Year-3 benefit; each lever carries a confidence factor of {CONF_RANGE}",
                    f"One-time working-capital release of **{m(WC_RELEASE)}** is reported separately and excluded from NPV"],
        commentary_title="Reading the chart",
        takeaway=f"Value scales with plants on the platform: {m(BEN_Y[0])}, {m(BEN_Y[1])}, then {m(BEN_Y[2])} a year (US$ millions, Base).",
        source=f"Source: {MODEL_SRC} — benefits.by_category, risk-adjusted; levers calibrated to Siemens {ref('siemens')} and McKinsey {ref('mckinsey')}.",
        notes=f"Benefits come from ten levers per plant, each risk-adjusted by a confidence factor between {CONF_LO:.0f} and {CONF_HI:.0f} percent. They ramp 35, 75 and 95 percent in the twelve months after each plant goes live, and plants go live in cohorts of two, three and three, so Year 1 is {m(BEN_Y[0])}, Year 2 {m(BEN_Y[1])} and Year 3 {m(BEN_Y[2])}. Unplanned downtime is the largest lever at {pc(DOWNTIME_SHARE_Y3)} of Year 3. At steady state with all eight plants mature, the case is {m(SS_BEN)} a year. The one-time working-capital release of {m(WC_RELEASE)} is reported separately and excluded from NPV, so the case does not rely on balance-sheet effects.")

    # 14 — ROI 2: cumulative net benefit across scenarios ----------------------------------------------------------------------------
    cum = {"Conservative": [0.0] + mil(CONS["roi"]["cumulative"]), "Base": [0.0] + mil(CUM), "Upside": [0.0] + mil(UP["roi"]["cumulative"])}
    sl = d.chart(
        f"Cumulative net benefit turns positive in Year 2: payback in {PAYBACK:.0f} months in the Base case",
        ["Programme start", "End of Year 1", "End of Year 2", "End of Year 3"], cum, kind="line", number_format='$#,##0"M"', labels=False,
        colors=["7A8CA3", "E8890C", "3DB88B"],
        commentary=[f"**Base** · NPV **{m(NPV)}** · ROI **{ROI_PCT:.0f}%** · payback **{PAYBACK:.0f} months**",
                    f"**Conservative** · NPV **{m(HC['npv'])}** · payback **{HC['payback_months']:.0f} months**",
                    f"**Upside** (optional expansion modules on) · NPV **{m(HU['npv'])}** · payback **{HU['payback_months']:.0f} months**",
                    f"5-year NPV (memo): {m(HC['npv_5yr'])} / {m(HB['npv_5yr'])} / {m(HU['npv_5yr'])}",
                    f"IRR is {IRR:.0f}% in Base because early outlay is small — lean on NPV and payback"],
        commentary_title="Three scenarios · 10% discount rate",
        takeaway=f"Costs of {m(COST3)} include Azure run cost, edge hardware, integration, people, licences and 10% contingency.",
        source=f"Source: {MODEL_SRC} — roi.cumulative by scenario (US$ millions, end of year). Scenarios vary {N_SCENARIO_VARIED} assumptions; the Conservative case stacks slower ramps, later go-live and higher costs.",
        notes=f"This is the CFO slide. In the Base case cumulative net benefit is {m(CUM[0])} after Year 1 because investment precedes benefit, turns positive during Year 2 at month {PAYBACK:.0f}, and reaches {m(NET3)} by Year 3. NPV at a 10 percent discount rate is {m(NPV)}, ROI {ROI_PCT:.0f} percent. Conservative stacks slower ramps, later go-live and higher costs: NPV {m(HC['npv'])}, payback {HC['payback_months']:.0f} months. Upside, with the optional expansion modules switched on, reaches {m(HU['npv'])} with payback in {HU['payback_months']:.0f} months. IRR looks high because early outlay is small, so we lean on NPV and payback. The five-year view, for memo only, is an NPV of {m(HB['npv_5yr'])}.")
    label_end_points(sl, lambda v: f"{MINUS if v < 0 else ''}${abs(v):,.1f}M", {0: XL_LABEL_POSITION.BELOW, 1: XL_LABEL_POSITION.RIGHT, 2: XL_LABEL_POSITION.LEFT}, ["7A8CA3", "E8890C", "3DB88B"])

    # 15 — ROI 3: sensitivity (tornado) ---------------------------------------------------------------------------------------------------
    short = {
        "benefit_ramp": "Benefit ramp after go-live", "downtime_reduction_pct": "Unplanned downtime avoided", "plants_cum_share_by_year": "Roll-out pace (plants live)",
        "go_live_month_in_year": "Go-live month in cohort year", "oee_performance_uplift_pts": "OEE performance uplift", "downtime_cost_pct_of_line_revenue": "Downtime cost per line-hour",
        "baseline_unplanned_downtime_pct": "Baseline unplanned downtime", "scrap_reduction_pct": "Scrap and rework reduction", "indirect_labour_productivity_gain_pct": "Indirect-labour productivity",
        "scrap_rework_cost_pct_revenue": "Scrap and rework baseline", "conf_downtime": "Downtime confidence factor", "maintenance_cost_reduction_pct": "Maintenance cost reduction",
        "energy_saving_pct": "Energy saving", "demand_capture_pct": "Share of freed capacity sold", "inventory_reduction_pct": "Inventory reduction",
    }
    drivers = [(short[s["id"]], round(s["npv_low"] / 1e6, 2), round(s["npv_high"] / 1e6, 2)) for s in SENS[:8]]
    d.tornado(
        "No single assumption turns the NPV negative; the benefit ramp and downtime reduction matter most",
        drivers, base_value=round(NPV / 1e6, 2), metric_label="NPV", number_format="+0.0;-0.0;0.0",
        subtitle=f"Change in 3-year NPV (US$ M) versus the Base {m(NPV)} when one assumption moves to its low or high value",
        takeaway="Validate three things first: the benefit ramp, the share of downtime avoided and the roll-out pace.",
        source=f"Source: {MODEL_SRC} — sensitivity (15 drivers tested, top 8 shown). Ranges are in assumptions.json; the lowest single-driver NPV is {m(MIN_LOW_NPV)}.",
        notes=f"Each bar moves one assumption to its low and high value while the others stay at Base. The biggest swings are the benefit ramp after go-live, the share of downtime avoided and the roll-out pace. Even at the low end of every single driver tested, NPV stays at or above {m(MIN_LOW_NPV)}; it takes several adverse assumptions together, the Conservative scenario, to push NPV to {m(HC['npv'])}. That is why the assessment and the pilot concentrate on measuring exactly these drivers on your data first. A good question for the room: which of these do you already know from your own plants?")

    # 16 — adoption path -------------------------------------------------------------------------------------------------------------
    d.set_section("Adoption and next steps")
    c1, c2, c3 = COHORTS
    d.timeline(
        "Adoption path: assess in weeks, pilot in months, scale plant by plant as trust is earned",
        [{"name": "Assess", "when": "Weeks 0–6", "items": ["Lights-Out Readiness Assessment", "Pick the first two plants (score ≥ 70)", "OT/Cyber lead engaged in week 1", "Baselines from Contoso actuals"]},
         {"name": "Pilot", "when": f"Months 2–{c1['go_live_month']}", "items": ["Shadow mode at L1, then L3 on 2–3 decision classes", f"{c1['plants']} plants live by month {c1['go_live_month']}", "A/B evidence with confidence intervals", "Exit: overrides < 10%, zero safety findings"]},
         {"name": "Scale", "when": f"Months {c1['go_live_month']}–36", "items": [f"{LIVE[1]} plants live by month {c2['go_live_month']}, {LIVE[2]} by month {c3['go_live_month']}", "L4 on proven decision classes", "Onboarding ≤ 12 weeks from templates", "Benefits validated by Finance"]},
         {"name": "Enterprise", "when": "Year 3 and beyond", "items": ["Fleet learning and benchmarking", "Signed policy bundles per region", "Lights-out cells (L4–L5) where proven", "Option: scale beyond 8 plants"]}],
        takeaway="Autonomy is earned decision class by decision class; every stage has an exit gate with evidence.",
        source=f"Source: SwarmAI PRD §13.1 and {MODEL_SRC} — go-live cohorts. Timings are planning assumptions.",
        notes=f"We propose four stages with exit gates. Assess: about six weeks, a readiness questionnaire plus measured signals, pick two pilot plants and bring the OT and cyber lead in on day one. Pilot: shadow mode first, then level three on two or three decision classes, with A/B evidence; two plants are live by month {c1['go_live_month']}. Scale: {LIVE[1]} plants live by month {c2['go_live_month']} and {LIVE[2]} by month {c3['go_live_month']}, reusing templates so onboarding takes about twelve weeks. Enterprise: fleet learning and signed policy bundles. Autonomy is earned decision class by decision class, and nothing scales without Finance-validated benefits. Timings are planning assumptions.")

    # 17 — risks and mitigations -------------------------------------------------------------------------------------------------------
    d.table(
        "The biggest risks are safety, trust and data — each has a design-level mitigation",
        ["Risk", "Impact", "Mitigation"],
        [["An agent action causes a safety or quality incident", "Critical", "Sim-first validation; Safety veto and forbidden setpoints; autonomy earned per class; blast-radius limits; kill switch; certified safety functions stay authoritative"],
         ["OT/Cyber lead vetoes, or new connectivity widens the attack surface", "High", "Engage OT/Cyber in week 1; IEC 62443 zones and conduits; outbound-only edge; no direct cloud-to-PLC writes; policy-gated control API"],
         ["Data gaps cap detection quality", "High", f"Readiness assessment with measured signals; sensor retrofit budgeted (≈ {k(SENSOR_RETROFIT)} per plant); Unified Namespace validation"],
         ["Benefits fall short of the case", "High", f"Confidence factors of {CONF_RANGE}; baselines from customer actuals; staged evidence; Finance sign-off; sensitivity shows the drivers"],
         ["Trust gap and change resistance (operators, works council)", "High", f"Shadow mode, explanations and citations, visible overrides; {m(CHANGE_3Y, 2)} change budget over 3 years; early works-council engagement"],
         ["Twin fidelity makes sim-first misleading", "Medium", "Calibrate from plant history; risk score penalises novelty; outcomes compared with the counterfactual; shadow mode first"],
         ["LLM errors, prompt injection or cost spikes", "Medium", "Deterministic core — models interpret, propose and narrate; tool allow-list; output validation; budget caps"]],
        col_weights=[3.0, 0.9, 6.9], align=["left", "center", "left"], highlight_rows=[0],
        takeaway="Risks are mitigated structurally in the design, then evidenced in shadow mode and the pilot.",
        source="Source: SwarmAI PRD §15 (15 risks; the seven highest shown), ARCHITECTURE §17.",
        notes="Seven risks matter most. Safety first: the mitigations are structural, not procedural. They are sim-first validation, the Safety veto, forbidden setpoints, the kill switch, and certified safety functions that remain authoritative. Second, the OT and cyber lead holds a veto, so we engage them in week one and design to IEC 62443 zones and conduits. Third, data quality: the assessment measures coverage before we promise anything. Fourth, benefits may fall short; confidence factors, customer baselines and staged evidence handle that. Trust and change management have a dedicated budget. Twin fidelity and language-model behaviour are controlled by calibration, a deterministic core, tool allow-lists and budget caps.")

    # 18 — KPIs we hold ourselves to ----------------------------------------------------------------------------------------------------------
    dr = ASSUMP["downtime_reduction_pct"]["scenario"]
    d.table(
        "We will hold ourselves to measurable targets for value, autonomy, safety and cost",
        ["KPI", "Target (Base; validate on customer data)", "Baseline source", "Measured by"],
        [["Unplanned downtime", f"−{pc(RES['downtime_reduction_pct'])} of unplanned hours (−{pc(dr['conservative'])} … −{pc(dr['upside'])})", "CMMS / MES, last 12 months", "A/B replay, shadow mode, pilot"],
         ["OEE — performance part", f"+{RES['oee_performance_uplift_pts'] * 100:.1f} points, reported apart from availability and quality", f"MES (typical OEE ≈ 60% {ref('oee')})", "KPI engine"],
         ["Scrap and rework cost", f"−{pc(RES['scrap_reduction_pct'])}", "Quality system", "KPI engine, pilot"],
         ["Late and short-delivery cost", f"−{pc(RES['late_delivery_reduction_pct'])}; lower tardiness than FIFO", "ERP / MES", "A/B replay"],
         ["Energy cost", f"−{pc(RES['energy_saving_pct'])}", "Meters and tariff", "KPI engine"],
         ["Autonomy and overrides", "≥ 60% of eligible decisions at L3+; < 10% overrides after month 12", "Decision Ledger", "Ledger analytics"],
         ["Safety", "0 agent-attributable incidents; protective stop within one tick; 100% veto compliance", "Incident log", "Sentinel, drills"],
         ["Explainability and integrity", "100% of decisions with rationale and counterfactual; 100% chain verification", "Decision Ledger", "verify-chain"],
         ["Platform", f"99.9% control-plane availability; ≈ ${ACR_DAY:,.0f} Azure per plant-day all-in", "Azure Monitor, Cost Management", "Observability and FinOps"]],
        col_weights=[2.0, 5.0, 2.4, 2.2], font_pt=12,
        source=f"Business KPIs are Base-case values with ranges; autonomy, safety and platform KPIs are product targets. Source: SwarmAI PRD §10.1 (KPI-01 to KPI-22), {MODEL_SRC}.",
        notes=f"These are the targets we will be held to, in four groups. Value: downtime, OEE, scrap, delivery and energy. They are Base-case values with ranges, all to be validated on your data. Autonomy: at least 60 percent of eligible decisions at level three or above, with fewer than 10 percent overrides after month twelve of the pilot. Safety and trust: zero agent-attributable incidents, every decision with rationale and counterfactual, chain verification at 100 percent. Platform: 99.9 percent control-plane availability and about ${ACR_DAY:,.0f} of Azure per plant-day. The KPI engine in the product measures them continuously.")

    # 19 — the ask ------------------------------------------------------------------------------------------------------------------------------
    d.big_statement(
        "The ask: start with evidence, not a big-bang rollout",
        "Approve a six-week Lights-Out Readiness Assessment now — and a two-plant shadow-mode pilot once readiness and baselines are in.",
        sub="Decision requested from the COO, CFO and CIO · all figures illustrative until replaced with Contoso actuals",
        bullets=[f"**Assessment** — fixed fee of about {k(ASSUMP['readiness_assessment_usd']['base'])} (assumption), creditable against the pilot; picks the first two plants",
                 "**Pilot** — shadow mode at L1, then L3 on 2–3 decision classes within four months; measured A/B on matched controls",
                 "**Success** — benefits validated by Finance, override rate below 10%, zero safety findings",
                 "**You provide** — an operations sponsor, a finance co-owner for the value proof, OT/Cyber lead from week 1, historian and CMMS exports"],
        notes=f"Close with the ask. We are not asking you to bet the plant. We ask for a six-week Lights-Out Readiness Assessment now, a fixed fee of about {k(ASSUMP['readiness_assessment_usd']['base'])}, which is an assumption and can be credited against the pilot, to pick the first two plants and to replace our assumptions with your baselines. If readiness is 70 or above and the OT and cyber lead is comfortable, a two-plant pilot starts in shadow mode. Success means validated benefits, an override rate below ten percent and zero safety findings. Decisions needed today: an operations sponsor, a finance co-owner for the value proof, and access to historian and CMMS exports.")


# ----------------------------------------------------------------------------------------------------------------------
# Azure opportunity (Microsoft and partner leadership)
# ----------------------------------------------------------------------------------------------------------------------
LINES = ACR["line_items"]
KIND_SHARE = {kind: sum(x["annual"] for x in LINES if x["kind"] == kind) / ACR_RUN for kind in {x["kind"] for x in LINES}}
PROV_SHARE = KIND_SHARE.get("provisioned", 0) + KIND_SHARE.get("shared", 0) + KIND_SHARE.get("stock", 0)
USAGE_SHARE = KIND_SHARE.get("usage", 0)
UPLIFT_SHARE = KIND_SHARE.get("uplift", 0)
TOP_LINES = sorted((x for x in LINES if x["kind"] != "uplift"), key=lambda x: -x["annual"])[:8]
TOP_LINES_SHARE = sum(x["annual"] for x in TOP_LINES) / ACR_RUN
AVG_LIVE = BASE["plants"]["average_live_plants_by_year"]
_ACR_TOP2 = {s["id"] for s in BASE["acr_sensitivity"][:2]}
ACR_LEVERS = "LLM usage and the number of plants live" if _ACR_TOP2 == {"llm_usage_multiplier", "plants_cum_share_by_year"} else "see acr_sensitivity in outputs.json"


def fmt_qty(x: dict) -> str:
    return f"{x['quantity']:,.0f} {x['unit']}"


def fmt_price(x: dict) -> str:
    return f"${x['unit_price']:.4g}"


def azure_slides(d: Deck) -> None:
    d.set_section(None)
    d.section(
        "Azure opportunity", "For Microsoft & partner leadership — skip for customer-only audiences", number="02",
        notes="This section is for Microsoft and partner leadership; skip it for customer-only audiences. It translates the business case into Azure consumed revenue, bottom-up per service family, per customer per year, at public list prices with no enterprise-agreement discount. We separate the core platform from five optional expansion levers, each with its own meters, cost and benefit, so the path from a pilot to a fleet is explicit. Nothing here is a Microsoft commitment or a forecast: it is an assumption-driven model whose every line can be audited in the appendix and reproduced from business-case/model.py.")
    d.set_section("Azure opportunity · ACR")

    # A0 — Azure opportunity at a glance --------------------------------------------------------------------------------------------------------------------
    e25, fl_ = EXP_TIERS["enterprise_25"], EXP_TIERS["fleet"]
    d.kpi_cards(
        f"Azure opportunity at a glance: from a ≈{k(PILOT['total'])} pilot to {m(EXP_RUN, 2)} a year at one customer and ≈{m(fl_['with_levers']['total'], 0)} across a fleet",
        [{"value": m(ACR_Y[2], 2), "label": "Year-3 ACR, core platform", "sub": f"Contoso, Base case, 8 plants · Conservative {m(HC['acr_year3'], 2)}"},
         {"value": m(ACR_RUN, 2), "label": "Run-rate, core platform (8 plants)", "sub": f"≈ {k(ACR_PLANT)} per plant-year · pull-through {PULL:.1f}×"},
         {"value": m(EXP_RUN, 2), "label": "Run-rate with five expansion levers", "sub": f"{EXP_RUN / ACR_RUN:.2f}× core · ≈ {k(EXP_H['acr_per_plant_year'])} per plant-year · pull-through {EXP_ACR['pull_through_ratio']:.1f}×"},
         {"value": m(e25["with_levers"]["total"], 1), "label": "25-plant enterprise, levers on", "sub": f"core platform {m(e25['without_levers']['total'], 1)}"},
         {"value": m(fl_["with_levers"]["total"], 1), "label": f"{FLEET_N}-plant fleet, levers on", "sub": f"core platform {m(fl_['without_levers']['total'], 1)} · illustration of scale"},
         {"value": m(HU["acr_year3"], 2), "label": "Year-3 ACR, Upside scenario", "sub": f"levers on · run-rate {m(HU['acr_run_rate'], 2)} at 8 plants"}],
        columns=3,
        subtitle="Bottom-up from Azure list prices (USD, pay-as-you-go, no EA discount) — modelled, not a forecast or a commitment",
        takeaway="The core platform is the platform decision; the five levers are customer-by-customer decisions that each pay back on their own — except OT security, a risk lever.",
        source=f"Source: {MODEL_SRC} — acr, expansion.acr, expansion.tiers; Upside scenario for the last card. Azure Retail Prices API {ref('retail')}. The {FLEET_N}-plant tier extrapolates shared-platform capacity.",
        notes=f"Start here if you only have two minutes. Bottom-up from Azure list prices, the core platform for Contoso's eight plants consumes {m(ACR_Y[2], 2)} in Year 3 and {m(ACR_RUN, 2)} a year at run-rate. Five optional levers, machine vision, high-frequency monitoring, continuous simulation, an enterprise data platform and OT security, each carry their own meters, cost and benefit and lift the run-rate to {m(EXP_RUN, 2)}. At 25 plants that is {m(e25['with_levers']['total'], 1)}; a {FLEET_N}-plant fleet, an illustration of scale, is {m(fl_['with_levers']['total'], 1)}. The core is a platform decision, the levers are customer decisions. All list price, modelled, not a forecast or a commitment.")

    # A1 — ACR by year, stacked by attach group -------------------------------------------------------------------------------------------
    d.chart(
        f"Core-platform Azure consumption ramps to {k(ACR_Y[2])} in Year 3 and {k(ACR_RUN)} a year at eight plants",
        YEARS, ACR_BY_GROUP_K, kind="stacked", number_format='$#,##0"k"', labels=False, colors=PALETTE7,
        commentary=[f"Bottom-up: units × Azure Retail Prices API list price {ref('retail')}; USD, pay-as-you-go, no EA discount",
                    f"Year 1 **{k(ACR_Y[0])}** · Year 2 **{k(ACR_Y[1])}** · Year 3 **{k(ACR_Y[2])}** (average live plants {AVG_LIVE[0]:.1f} → {AVG_LIVE[1]:.1f} → {AVG_LIVE[2]:.1f})",
                    f"Run-rate at 8 plants: **{k(ACR_RUN)}** a year ≈ **{k(ACR_PLANT)}** per plant-year ≈ **${ACR['per_asset_year']:,.0f}** per asset-year",
                    f"Year-3 range: **{m(HC['acr_year3'], 2)}** Conservative to **{m(HU['acr_year3'], 2)}** Upside, where the expansion levers are on (slides that follow)"],
        commentary_title="Contoso, Base case, levers off",
        takeaway=f"The core platform adds about {k(ACR_PLANT)} a year per plant at list price; the optional levers roughly double it.",
        source=f"Source: {MODEL_SRC} — acr.by_year, by_family ({N_LINES} lines, {N_METERS} price meters queried {RETRIEVED}); Azure Retail Prices API {ref('retail')}. Modelled, not a forecast.",
        notes=f"This is the bottom-up view for one customer. Each bar is the sum of about seventy lines: units times the public Azure retail unit price, in US dollars, pay-as-you-go, no enterprise-agreement discount. Consumption follows go-lives: {k(ACR_Y[0])} in Year 1, {k(ACR_Y[1])} in Year 2 and {k(ACR_Y[2])} in Year 3, reaching a run-rate of {k(ACR_RUN)} a year at eight plants, about {k(ACR_PLANT)} per plant-year. Conservative is {m(HC['acr_year3'], 2)} in Year 3; Upside, with the optional expansion levers on, {m(HU['acr_year3'], 2)}. Modelled values, not forecasts or commitments; discounts would lower them.")

    # A2 — run-rate by service family ------------------------------------------------------------------------------------------------------
    order = sorted(RUN_BY_FAMILY, key=lambda f: -RUN_BY_FAMILY[f])
    d.chart(
        "Twelve service families drive consumption; Foundry, compute and Fabric are the top three",
        [FAMILY_SHORT[f] for f in order], {"Run-rate ACR, US$ thousands a year": kil([RUN_BY_FAMILY[f] for f in order])}, kind="bar",
        number_format='$#,##0"k"', labels=True,
        commentary=[f"Top three families are **{pc(TOP3_SHARE)}** of the {k(ACR_RUN)} run-rate",
                    f"**{pc(PROV_SHARE)}** is provisioned, shared or stored capacity — predictable and landed by the pilot",
                    f"**{pc(USAGE_SHARE)}** is usage-based: model tokens, logs, operations — grows with autonomy",
                    f"**{pc(UPLIFT_SHARE)}** is dev/test and disaster-recovery uplift",
                    f"Biggest ACR levers: {ACR_LEVERS}"],
        commentary_title="Run-rate at 8 plants",
        takeaway="The platform lands as committed capacity with the pilot; usage and plants then drive growth.",
        source=f"Source: {MODEL_SRC} — acr.run_rate_by_family, line_items by kind; Azure Retail Prices API {ref('retail')}.",
        notes=f"Twelve service families make up the run-rate. Foundry models, Container Apps compute and Fabric are the top three at {pc(TOP3_SHARE)} of the total. Note the shape: {pc(PROV_SHARE)} is provisioned, shared or stored capacity, which is predictable, while {pc(USAGE_SHARE)} is usage-based, mostly model tokens, logs and operations, and {pc(UPLIFT_SHARE)} is dev/test and disaster-recovery uplift. That mix matters for account planning: the capacity lands with the pilot, and usage grows with autonomy. Likely question: what moves it most? The LLM usage multiplier and the number of plants live.")

    # A3 — pull-through / attach ---------------------------------------------------------------------------------------------------------------
    att = ACR["attach"]
    ex_att = EXP_ACR["attach"]
    EXP_PULL = EXP_ACR["pull_through_ratio"]
    d.chart(
        f"Every $1 of AI services pulls through ${PULL:.1f} of other Azure consumption — ${EXP_PULL:.1f} once the expansion levers are on",
        [name for name, _ in ATTACH_GROUPS], {"Run-rate ACR, US$ thousands": kil([att[ATTACH_KEY[name]]["annual"] for name, _ in ATTACH_GROUPS])},
        kind="doughnut", number_format='$#,##0"k"', labels=True, label_format="pct", colors=PALETTE7,
        commentary=[f"**AI core** (Foundry models, AI Search, Azure ML): **{pc(att['ai_core']['share'])}** · {k(att['ai_core']['annual'])}",
                    f"**Data** (Fabric, Cosmos DB, Storage, messaging, Digital Twins): **{pc(att['data']['share'])}** · {k(att['data']['annual'])}",
                    f"Compute {pc(att['compute']['share'])} · Security {pc(att['security']['share'])} · Monitoring {pc(att['monitoring']['share'])} · Edge {pc(att['edge']['share'])} · Networking {pc(att['networking']['share'])}",
                    f"Core pull-through **{PULL:.2f}×** (Conservative {HC['pull_through_ratio']:.2f}×)",
                    f"With the five levers on: **{EXP_PULL:.2f}×** — AI core falls to {pc(ex_att['ai_core']['share'])}, data rises to {pc(ex_att['data']['share'])}, security to {pc(ex_att['security']['share'])}"],
        commentary_title="Attach and pull-through (core, 8 plants)",
        takeaway=f"Security and monitoring alone are {pc(att['security']['share'] + att['monitoring']['share'])} of core consumption — landed by the same pilot.",
        source=f"Source: {MODEL_SRC} — acr.attach, pull_through_ratio and expansion.acr.attach (non-AI consumption ÷ AI-core consumption, 8-plant run-rate).",
        notes=f"Pull-through is the strategic point. For every dollar of AI services, meaning Foundry models, AI Search and Azure ML, the core solution consumes {PULL:.1f} dollars of other Azure services: data and analytics at {pc(att['data']['share'])} of the total, then compute, security, monitoring, edge and networking. With the five expansion levers on, the ratio rises to {EXP_PULL:.1f} because enterprise Fabric, security and networking grow faster than model usage. For Microsoft and partners, security and monitoring are {pc(att['security']['share'] + att['monitoring']['share'])} of core consumption and land with the same pilot.")

    # A4 — ACR by plant tier, core vs expansion levers ---------------------------------------------------------------------------------------------------
    tier_labels = {"pilot": "Pilot — one line", "plant_1": "One plant, full scope", "customer": "Eight plants (Contoso)", "enterprise_25": "25-plant enterprise",
                   "fleet": f"{FLEET_N}-plant enterprise fleet"}
    rows = []
    for tid in ("pilot", "plant_1", "customer", "enterprise_25", "fleet"):
        t = EXP_TIERS[tid]
        w_, wo_ = t["with_levers"], t["without_levers"]
        rows.append([tier_labels[tid], f"{t['plants']} × {t['assets_per_plant']:.0f}", km(wo_["total"]), km(w_["total"]) + (" (no levers)" if tid == "pilot" else ""),
                     k(w_["per_plant"]), f"${w_['per_asset_year']:,.0f}", f"{w_['total'] / wo_['total']:.2f}×"])
    ce = CONS["expansion"]["acr"]
    rows.append(["Eight plants — Conservative inputs", "8 × 400", km(HC["acr_run_rate"]), km(HC["expansion_acr_run_rate"]), k(ce["per_plant_year"]), f"${ce['per_asset_year']:,.0f}",
                 f"{HC['expansion_acr_run_rate'] / HC['acr_run_rate']:.2f}×"])
    rows.append(["Eight plants — Upside inputs (levers on)", "8 × 400", km(UP["acr"]["run_rate_by_lever"]["core"]), km(HU["acr_run_rate"]), k(HU["acr_per_plant_year"]),
                 f"${UP['acr']['per_asset_year']:,.0f}", f"{HU['acr_run_rate'] / UP['acr']['run_rate_by_lever']['core']:.2f}×"])
    fleet_t = EXP_TIERS["fleet"]
    d.table(
        f"Consumption scales with plants: ≈{k(PILOT['total'])} for a pilot line, {m(ACR_RUN, 2)} at eight plants, {m(fleet_t['with_levers']['total'], 0)} across {FLEET_N} plants with levers",
        ["Tier", "Plants × assets", "Core platform / year", "With expansion levers / year", "Per plant (levers on)", "Per asset-year (levers on)", "Uplift"],
        rows, col_weights=[3.0, 1.2, 1.6, 2.0, 1.5, 1.6, 0.9], align=["left", "right", "right", "right", "right", "right", "right"], highlight_rows=[2],
        takeaway=f"Per-plant consumption falls {pc(PER_PLANT_DROP)} from 8 to 25 plants as shared platform cost is spread; the levers roughly double it at every scale.",
        source=f"Source: {MODEL_SRC} — acr.tiers and expansion.tiers (Base inputs, list price; levers at Upside adoption). Shared-platform capacity beyond 25 plants is extrapolated: the {FLEET_N}-plant tier illustrates scale.",
        notes=f"This table shows how consumption scales with scope, steady-state at list price. A one-line pilot lands at about {k(PILOT['total'])} a year. A full single plant is {k(PLANT1['total'])} core. Eight plants reach {k(EIGHT['total'])}, or {k(EIGHT['per_plant'])} per plant, and {m(EXP_RUN, 2)} with the expansion levers. A 25-plant enterprise reaches {m(ENT25['total'])} core and {m(EXP_TIERS['enterprise_25']['with_levers']['total'], 2)} with levers. A {FLEET_N}-plant fleet reaches {m(fleet_t['without_levers']['total'], 1)} and {m(fleet_t['with_levers']['total'], 1)}; that tier illustrates scale, not a plan for Contoso. Reservations and enterprise agreements would lower all of it.")

    # A5 — the five expansion levers -----------------------------------------------------------------------------------------------------------------------
    lever_what = {
        "E1": "Image archive (Blob/ADLS), GPU retraining (Azure ML), frame escalations to multimodal models (Foundry); inference stays at the edge",
        "E2": "Event Hubs, waveform archive (ADLS), feature extraction (Fabric), signature models (Azure ML); raw waveforms uploaded only 5% of the time",
        "E3": "Monte-Carlo simulation pools on AKS / Batch / Container Apps jobs (D16s v5), result storage, Cosmos DB twin snapshots",
        "E4": "Enterprise-scale Fabric capacity, OneLake with 96-month retention, migrated historian archives",
        "E5": "ExpressRoute per plant, Azure Firewall Premium hubs, Defender for Servers on Arc, Sentinel OT-log ingestion",
    }
    lever_rows = []
    for lid in EXP_BY_ID:
        pb = EXP_BY_ID[lid]["per_deploying_plant"]["payback_months"]
        lever_rows.append([LEVER_SHORT[lid], lever_what[lid], k(LEVER_RUN[lid]), pc(LEVER_ADOPT[lid]), f"{pb:.0f} months" if pb else "none — risk lever"])
    lever_rows.append(["Five levers together", "", km(LEVER_SUM_RUN), "", ""])
    lever_rows.append(["Core platform → with levers", "", f"{km(LEVER_RUN['core'])} → {km(EXP_RUN)}", "", ""])
    d.table(
        f"Five optional levers add {m(LEVER_SUM_RUN, 2)} of run-rate at eight plants; enterprise data platform and OT security carry most of it",
        ["Lever", "What Azure carries (list-price meters)", "Run-rate, 8 plants", "Plants deploying", "Customer payback per plant"],
        lever_rows, col_weights=[2.5, 5.9, 1.5, 1.2, 1.6], align=["left", "left", "right", "right", "right"], highlight_rows=[len(lever_rows) - 1], font_pt=11,
        takeaway=f"Honest sizing: E2 and E3 add only {k(LEVER_RUN['E2'] / 8)} and {k(LEVER_RUN['E3'] / 8)} per plant, E1 is modest because inference is customer-side, and E5 is a risk lever.",
        source=f"Source: {MODEL_SRC} — expansion.levers and acr.run_rate_by_lever (Base inputs, levers at Upside adoption); Azure Retail Prices API {ref('retail')}. Power BI and Defender for IoT are Microsoft 365 licences, not ACR {ref('m365')}.",
        notes=f"Real programmes add workloads that are Azure-heavy at fleet scale; we model five as optional levers, each with its own meters, customer cost and benefit. Machine vision keeps inference on customer edge GPUs, so Azure carries the image archive, retraining and escalations: {k(LEVER_RUN['E1'])}. High-frequency monitoring is small unless raw waveforms stream continuously: {k(LEVER_RUN['E2'])}. Continuous simulation is {k(LEVER_RUN['E3'])}. The enterprise data platform, {k(LEVER_RUN['E4'])}, and OT security and connectivity, {k(LEVER_RUN['E5'])}, are the big steps. E5 is a risk lever; the others pay back within a year or two per plant.")

    # A6 — ACR by lever, stacked ---------------------------------------------------------------------------------------------------------------------------
    lever_series = {"Core platform": kil(LEVER_BY_YEAR["core"]) + [round(LEVER_RUN["core"] / 1e3, 1)]}
    for lid in EXP_BY_ID:
        lever_series[LEVER_SHORT[lid]] = kil(LEVER_BY_YEAR[lid]) + [round(LEVER_RUN[lid] / 1e3, 1)]
    E1_LAG, E3_LAG = EXP_BY_ID["E1"]["start_lag_months"], EXP_BY_ID["E3"]["start_lag_months"]
    d.chart(
        f"With the five levers on, consumption reaches {m(EXP_Y[2], 2)} in Year 3 and {m(EXP_RUN, 2)} a year at eight plants",
        YEARS + ["Run-rate, 8 plants"], lever_series, kind="stacked", number_format='$#,##0"k"', labels=False,
        colors=["7A8CA3", "E8890C", "2BA3D8", "3DB88B", "8764B8", "FFB900"],
        commentary=[f"Year 1 **{k(EXP_Y[0])}** · Year 2 **{k(EXP_Y[1])}** · Year 3 **{m(EXP_Y[2], 2)}** · run-rate **{m(EXP_RUN, 2)}** (US$ thousands in the chart)",
                    f"Core platform alone: {k(ACR_Y[0])} · {k(ACR_Y[1])} · {k(ACR_Y[2])} · {k(ACR_RUN)}; the levers lift the run-rate to **{EXP_RUN / ACR_RUN:.2f}×**",
                    f"**E4** and **E5** start with each plant's go-live (lags {EXP_BY_ID['E4']['start_lag_months']} and {EXP_BY_ID['E5']['start_lag_months']} months) and are {pc((LEVER_RUN['E4'] + LEVER_RUN['E5']) / LEVER_SUM_RUN)} of the lever run-rate",
                    f"**E1** and **E3** start {E1_LAG} and {E3_LAG} months after go-live, so they appear from Year 2",
                    "Base inputs with the levers at their Upside adoption; list price, no discounts"],
        commentary_title="ACR by lever, Contoso",
        takeaway="The pilot lands the core platform; each lever is a separate, plant-by-plant or platform-level decision on its own business case.",
        source=f"Source: {MODEL_SRC} — expansion.acr.by_lever and run_rate_by_lever (US$ thousands); Azure Retail Prices API {ref('retail')}. Modelled, not a forecast.",
        notes=f"This is the same customer with the five optional levers switched on, stacked by lever. Year 1 is {k(EXP_Y[0])}, Year 2 {k(EXP_Y[1])}, Year 3 {m(EXP_Y[2], 2)}, and the run-rate at eight plants {m(EXP_RUN, 2)}, {EXP_RUN / ACR_RUN:.2f} times the core platform. The data platform and security levers land first, because they start with each plant's go-live; machine vision and continuous simulation start {E1_LAG} and {E3_LAG} months later. Each lever is decided on its own business case, so a customer may take some and not others. All at list price, with no discounts.")

    # A7 — the ACR expansion path (waterfall) --------------------------------------------------------------------------------------------------------------
    path_steps = [("Core platform, 8 plants", LEVER_RUN["core"] / 1e3)] + [(LEVER_SHORT[lid], LEVER_RUN[lid] / 1e3) for lid in EXP_BY_ID]
    e25, fl_ = EXP_TIERS["enterprise_25"], EXP_TIERS["fleet"]
    ups = {t["id"]: t for t in UP["acr"]["tiers"]}
    wf2 = d.waterfall(
        f"ACR expansion path: {m(ACR_RUN, 2)} core → {m(EXP_RUN, 2)} with levers at eight plants → {m(e25['with_levers']['total'], 1)} at 25 → {m(fl_['with_levers']['total'], 0)} at {FLEET_N}",
        [(f"{name} +{v:,.0f}k" if i else name, round(v, 1)) for i, (name, v) in enumerate(path_steps)], number_format='$#,##0"k"', total_label="With levers, 8 plants",
        subtitle="Run-rate Azure consumption per year, US$ thousands, Base inputs, list price",
        commentary=[f"**8 plants:** {km(LEVER_RUN['core'])} core → **{m(EXP_RUN, 2)}** with levers ({EXP_RUN / ACR_RUN:.2f}×)",
                    f"**25 plants:** {m(e25['without_levers']['total'], 2)} → **{m(e25['with_levers']['total'], 2)}**",
                    f"**{FLEET_N} plants:** {m(fl_['without_levers']['total'], 1)} → **{m(fl_['with_levers']['total'], 1)}** ({k(fl_['with_levers']['per_plant'])} per plant)",
                    f"**Upside inputs:** {m(HU['acr_run_rate'], 2)} (8) · {m(ups['enterprise_25']['total'], 2)} (25) · {m(HU['fleet_acr_run_rate_expansion'], 1)} ({FLEET_N})",
                    "Not modelled: reservations, savings plans, EA discounts (lower); provisioned throughput, physics-level twins (higher)"],
        commentary_title="Same levers at scale",
        source=f"Source: {MODEL_SRC} — expansion.path and expansion.tiers; Upside tiers from the Upside scenario. The {FLEET_N}-plant tier extrapolates shared-platform capacity beyond 25 plants and illustrates scale.",
        notes=f"The ACR expansion path in one picture. Contoso's core platform is {km(LEVER_RUN['core'])} a year at eight plants; each lever adds a step, from {k(LEVER_RUN['E2'])} for high-frequency monitoring to {k(LEVER_RUN['E4'])} for the enterprise data platform, reaching {m(EXP_RUN, 2)}. The same levers at 25 plants are {m(e25['with_levers']['total'], 2)} and across {FLEET_N} plants {m(fl_['with_levers']['total'], 1)} a year; with Upside inputs {m(HU['fleet_acr_run_rate_expansion'], 1)}. The fleet tier is an illustration of scale, not a plan. Discounts would reduce these figures.")
    for shape in wf2.shapes:  # label the bars in thousands with a dollar sign; the small steps keep their amounts in the category names
        if getattr(shape, "has_chart", False) and shape.has_chart:
            plot = shape.chart.plots[0]
            for idx in (1, 3):
                ser = plot.series[idx]
                for pi, val in enumerate(ser.values):
                    if val:
                        dl = ser.points[pi].data_label
                        dl.has_text_frame = True
                        dl.text_frame.text = f"${val:,.0f}k" if (pi in (0, len(path_steps)) and val > 400) else "\u00a0"
                        run = dl.text_frame.paragraphs[0].runs[0]
                        run.font.size = Pt(12)
                        run.font.bold = True
                        run.font.color.rgb = RGBColor.from_string("FFFFFF")

    # A8 — land and expand ---------------------------------------------------------------------------------------------------------------------------
    d.timeline(
        "Land with the assessment and expand plant by plant: consumption follows each go-live, then each lever",
        [{"name": "Land: assess", "when": "Weeks 0–6", "items": ["Readiness assessment and landing-zone design", "Dev/test only — no production consumption", "Architecture review with the cloud team"]},
         {"name": "Pilot", "when": "Months 2–7", "items": [f"One line ≈ {k(PILOT['total'])}; one plant ≈ {k(PLANT1['total'])} a year", "IoT Operations on Arc, Foundry, Fabric, Cosmos DB", "Edge, data and AI foundations reused later"]},
         {"name": "Expand", "when": "Months 7–36", "items": [f"Year 2 {k(ACR_Y[1])} → Year 3 {k(ACR_Y[2])} (core)", f"{LIVE[1]} → {LIVE[2]} plants on the same platform", f"Levers on proven plants: {m(EXP_Y[2], 2)} in Year 3 — data platform and OT security first"]},
         {"name": "Enterprise", "when": "Year 3 and beyond", "items": [f"8 plants: {k(ACR_RUN)} core → {m(EXP_RUN, 2)} with levers", f"25 plants ≈ {m(e25['with_levers']['total'], 1)}; a {FLEET_N}-plant fleet ≈ {m(fl_['with_levers']['total'], 0)} a year", "Reservations and EA discounts not modelled"]}],
        takeaway="The pilot is the landing zone: edge, data and AI foundations are reused by every later plant and every lever.",
        source=f"Source: {MODEL_SRC} — acr.by_year, acr.tiers, expansion.tiers. Partner roles and co-sell motions are candidate routes to validate, not commitments.",
        notes=f"The land-and-expand motion follows the customer's adoption path. The assessment lands almost no production consumption; its value is choosing plants and designing the landing zone with the customer's cloud team. The pilot lands the edge, data and AI foundations at roughly {k(PILOT['total'])} to {k(PLANT1['total'])} a year. Each further plant reuses them, so core consumption follows go-lives to {k(ACR_Y[2])} in Year 3. The expansion levers then land on proven plants, taking Year 3 to {m(EXP_Y[2], 2)} and the eight-plant run-rate to {m(EXP_RUN, 2)}. Partner roles are candidate routes to validate, not commitments.")

    # A9 — illustrative opportunity sizing -----------------------------------------------------------------------------------------------------------------
    cons_opp, up_opp = CONS["acr"]["opportunity"], UP["acr"]["opportunity"]
    t_jobs, t_share, t_size, t_ready, t_mult = (RES["tam_eu_manufacturing_persons"] / 1e6, RES["tam_eu_large_enterprise_employment_share"], RES["tam_employees_per_large_plant"],
                                                RES["tam_automation_ready_share"], RES["tam_global_to_eu_multiplier"])
    d.kpi_cards(
        f"Illustrative sizing: at {pc(OPP['penetration_year5'])} penetration the pool is ≈{m(OPP['acr_at_penetration_year5'], 0)} a year on the core platform, ≈{m(EXP_OPP['acr_at_penetration_year5'], 0)} with expansion levers",
        [{"value": f"≈{OPP['addressable_plants_eu'] / 1e3:.1f}k", "label": "Addressable EU plants", "sub": f"{t_jobs:.1f}M jobs × {pc(t_share, 1)} {ref('eurostat')} ÷ {t_size:.0f} per plant × {pc(t_ready)} ready"},
         {"value": f"≈{OPP['addressable_plants_global'] / 1e3:.1f}k", "label": "Addressable plants worldwide", "sub": f"{t_mult:.0f}× the EU figure (assumption)"},
         {"value": f"{k(OPP['acr_per_plant_year'])} → {k(EXP_OPP['acr_per_plant_year'])}", "label": "ACR per plant-year: core → with levers (Base)", "sub": "bottom-up, list price, 8-plant run-rate"},
         {"value": f"${OPP['potential_acr_at_full_penetration'] / 1e9:.1f}B → ${EXP_OPP['potential_acr_at_full_penetration'] / 1e9:.1f}B", "label": "Annual ACR pool at 100% penetration", "sub": f"{OPP['addressable_plants_global'] / 1e3:.1f}k plants × ACR per plant-year"},
         {"value": f"≈{m(OPP['acr_at_penetration_year5'], 0)} → ≈{m(EXP_OPP['acr_at_penetration_year5'], 0)}", "label": f"Annual ACR at {pc(OPP['penetration_year5'])} penetration", "sub": f"≈ {OPP['plants_at_penetration_year5']:,.0f} plants ≈ {OPP['customers_equivalent_at_penetration']:,.0f} customers of 8 plants"},
         {"value": f"{m(cons_opp['acr_at_penetration_year5'], 0)} – ${up_opp['acr_at_penetration_year5'] / 1e9:.2f}B", "label": "Conservative to Upside", "sub": f"Upside: levers on, {pc(up_opp['penetration_year5'])} penetration, larger addressable base"}],
        columns=3,
        subtitle="ILLUSTRATIVE — assumption-driven order of magnitude; not a forecast or a commitment",
        takeaway=f"{m(EXP_OPP['acr_at_penetration_year5'], 0)} is under {EXP_OPP['acr_at_penetration_year5'] / SMART_2030 * 100:.1f}% of the 2030 smart-factory market forecast of $170B {ref('mnm')} — validate with segment data.",
        source=f"Source: Eurostat 2022 employment {ref('eurostat')}; MarketsandMarkets {ref('mnm')}; plant size, readiness share, global multiplier and penetration are assumptions ({MODEL_SRC}, acr.opportunity and expansion.acr.opportunity).",
        notes=f"Treat this as an order of magnitude, clearly labelled illustrative. The EU base comes from Eurostat employment, {t_jobs:.0f} million manufacturing jobs with {pc(t_share, 1)} in large enterprises, divided by an assumed {t_size:.0f} employees per plant and an assumed {pc(t_ready)} automation-ready share: about {OPP['addressable_plants_eu'] / 1e3:.1f} thousand plants; the global figure is an assumed {t_mult:.0f} times that. At the modelled {k(OPP['acr_per_plant_year'])} per plant-year, full penetration is {OPP['potential_acr_at_full_penetration'] / 1e9:.1f} billion dollars a year, and {pc(OPP['penetration_year5'])} by year five about {m(OPP['acr_at_penetration_year5'], 0)}; with the expansion levers, {k(EXP_OPP['acr_per_plant_year'])} per plant-year and about {m(EXP_OPP['acr_at_penetration_year5'], 0)}. Validate with segment data before using externally.")

    # A10 — pricing basis and the eight largest lines ---------------------------------------------------------------------------------------------------------
    d.table(
        "Every ACR line is auditable: units × Azure list price × stated assumptions",
        ["Line (Base, 8 plants)", "Family", "Quantity per year", "Unit price (US$)", "Annual"],
        [[x["item"], FAMILY_SHORT[x["family"]], fmt_qty(x), fmt_price(x), k(x["annual"])] for x in TOP_LINES],
        col_weights=[4.4, 2.3, 2.3, 1.1, 1.0], align=["left", "left", "right", "right", "right"], font_pt=11,
        subtitle=f"Core platform: {N_LINES} lines from {N_METERS} price meters queried {RETRIEVED} · swedencentral (Digital Twins: westeurope) · pay-as-you-go list price · no EA discount",
        takeaway=f"The eight largest core lines are {pc(TOP_LINES_SHARE)} of the {k(ACR_RUN)} run-rate; every line, including the {len(EXP_ACR['line_items']) - N_LINES} added by the levers, is in business-case/outputs.md.",
        source=f"Source: Azure Retail Prices API {ref('retail')}; Sentinel and Eventhouse billing models {ref('billing')}; {MODEL_SRC} — acr.line_items and expansion.acr.line_items.",
        notes=f"For the sceptical executive: every number is auditable. Each line is a quantity driven by an assumption, such as nodes, vCPU-hours, gigabytes or tokens, times a unit price from the Azure Retail Prices API, queried on {RETRIEVED} for Sweden Central, with Digital Twins priced in West Europe. These are the eight largest core lines at eight plants; the rest, the lever lines and the dev/test and disaster-recovery uplifts, are in the outputs file. Prices are pay-as-you-go list prices; enterprise agreements, reservations and savings plans would reduce them and are not modelled.")


# ----------------------------------------------------------------------------------------------------------------------
# appendix
# ----------------------------------------------------------------------------------------------------------------------
S_BY_ID = {s["id"]: s for s in SENS}
RANK = {s["id"]: i + 1 for i, s in enumerate(SENS)}


def fl(values) -> str:
    return "/".join(f"{v * 100:.0f}" for v in values) + "%"


def rk(*ids: str) -> str:
    return "NPV driver " + " and ".join(f"#{RANK[i]}" for i in ids) + f" of {len(SENS)}"


def appendix_slides(d: Deck, azure: bool) -> None:
    d.set_section(None)
    d.section(
        "Appendix", "Assumptions, value drivers, costs, scenarios, features, glossary and sources", number="03" if azure else "02",
        notes="The appendix collects the evidence behind the numbers and the product: the assumptions that most need customer validation, value drivers per plant, the cost bridge and cost table, the three scenarios, a differentiation view, the full feature list with status, what is real and what is simulated, a glossary and the sources. Use it to answer detailed questions without disturbing the main storyline. Every figure on these pages is read from the business-case outputs file or comes from a cited source, and the model, the assumptions and the unit tests are in the repository so a finance team can reproduce them.")
    d.set_section("Appendix · assumptions")

    # P1 — assumptions that most need validation ---------------------------------------------------------------------------------------------------
    dr = ASSUMP["downtime_reduction_pct"]["scenario"]
    ramp = RES["benefit_ramp"]
    d.table(
        "Nine assumptions most need customer validation — and we know where the evidence will come from",
        ["Assumption", "Base value (range tested)", "Why it matters", "How we validate"],
        [["Benefit ramp after go-live", f"{fl(ramp)} in 12-month steps (tested {fl(S_BY_ID['benefit_ramp']['low_value'])} to {fl(S_BY_ID['benefit_ramp']['high_value'])})", rk("benefit_ramp"), "Pilot onboarding curve"],
         ["Unplanned downtime avoided", f"{pc(RES['downtime_reduction_pct'])} (Conservative {pc(dr['conservative'])}, Upside {pc(dr['upside'])}); literature 30–50% {ref('mckinsey')}", rk("downtime_reduction_pct"), "Shadow mode, then pilot A/B"],
         ["Roll-out pace and go-live month", f"{LIVE[0]} → {LIVE[1]} → {LIVE[2]} plants live at year-ends; cohorts go live in month {COHORTS[0]['go_live_month']}", rk("plants_cum_share_by_year", "go_live_month_in_year"), "Readiness assessment, plant sequencing"],
         ["Baseline downtime and cost per line-hour", f"{pc(RES['baseline_unplanned_downtime_pct'], 1)} of scheduled line time (≈ {DER['baseline_unplanned_downtime_hours_per_plant_year']:,.0f} line-hours a plant); ≈ {k(LINE_H, 1)} per line-hour", "Scales the largest lever", "CMMS/MES log; Finance: margin, idle labour, recovery"],
         ["OEE uplift and demand capture", f"+{RES['oee_performance_uplift_pts'] * 100:.1f} OEE points; {pc(RES['demand_capture_pct'])} of freed capacity sold", rk("oee_performance_uplift_pts"), "Order book, A/B replay"],
         ["Labour effect", f"{pc(RES['indirect_labour_productivity_gain_pct'])} productivity on {RES['indirect_labour_fte_per_plant']} indirect FTE a plant — capacity released, not headcount", rk("indirect_labour_productivity_gain_pct"), "Time study; redeployment decision"],
         ["Confidence factors", f"{CONF_RANGE} by lever (downtime {pc(BEN['confidence']['downtime'])}, throughput {pc(BEN['confidence']['throughput'])}, OTIF {pc(BEN['confidence']['otif'])}, capex {pc(BEN['confidence']['capex'])})", "Risk-adjusts every benefit", "Replaced by measured realisation"],
         ["SwarmAI licence and integration prices", f"{k(RES['platform_licence_per_plant_usd_year'])} per plant-year; integration {k(RES['integration_per_plant_first_usd'])}, then {k(RES['integration_per_plant_next_usd'])} per plant", "Pricing hints, not a price list", "Commercial proposal"],
         ["Telemetry, model-token and expansion-module volumes", f"{RES['llm_agent_calls_per_plant_day']:,} agent assessments and {RES['llm_triage_calls_per_plant_day']:,} triage calls per plant-day; modules: {RES['exp_vision_cameras_per_plant']:.0f} cameras, {pc(RES['exp_hf_duty_cycle'])} waveform upload, {RES['exp_sim_rollouts_per_decision']:.0f} rollouts per decision", "Drives Azure run cost and lever sizing", "Measured in shadow mode and the first plants"]],
        col_weights=[2.3, 4.2, 2.1, 2.5], font_pt=11,
        source=f"Source: assumptions.json ({len(ASSUMP)} assumptions, each with low/base/high, rationale and source flag); {MODEL_SRC} — sensitivity ranking.",
        notes=f"These are the assumptions we would validate first, ordered roughly by their influence on NPV, using the sensitivity ranking. For each we show the Base value and where the evidence will come from: CMMS and MES exports for downtime, Finance for the cost of a line-hour, and the pilot for the ramp and the labour effect. Two rows are commercial: SwarmAI licence and integration prices are pricing hints, not a price list. Ask the audience to challenge any row. Changing them in the live calculator updates every number within seconds, and the model and its unit tests are in the repository.")

    # P2 — value drivers per plant ---------------------------------------------------------------------------------------------------------------
    gross, adj, conf, labels = BEN["steady_state_per_plant_gross"], BEN["steady_state_per_plant_risk_adjusted"], BEN["confidence"], BEN["category_labels"]
    lever = {
        "downtime": f"{pc(RES['downtime_reduction_pct'])} of unplanned downtime avoided × {k(LINE_H, 1)} per line-hour",
        "maintenance": f"{pc(RES['maintenance_cost_reduction_pct'])} lower maintenance spend (baseline {pc(RES['maintenance_spend_pct_revenue'], 1)} of revenue)",
        "throughput": f"+{RES['oee_performance_uplift_pts'] * 100:.1f} OEE points; {pc(RES['demand_capture_pct'])} of freed capacity sold at {pc(RES['contribution_margin_pct'])} margin",
        "scrap": f"{pc(RES['scrap_reduction_pct'])} lower scrap and rework (baseline {pc(RES['scrap_rework_cost_pct_revenue'], 1)} of revenue)",
        "energy": f"{pc(RES['energy_saving_pct'])} lower energy cost (baseline {pc(RES['energy_spend_pct_revenue'], 1)} of revenue)",
        "labour": f"{pc(RES['indirect_labour_productivity_gain_pct'])} productivity on {RES['indirect_labour_fte_per_plant']} FTE × ${RES['loaded_labour_rate_usd_per_hour']} per hour",
        "inventory": f"{pc(RES['inventory_reduction_pct'])} lower inventory × {pc(RES['inventory_carrying_cost_pct'])} carrying cost",
        "expedite": f"{pc(RES['expedite_reduction_pct'])} lower expedite spend (baseline {pc(RES['expedite_spend_pct_revenue'], 1)} of revenue)",
        "otif": f"{pc(RES['late_delivery_reduction_pct'])} lower late-delivery cost (baseline {pc(RES['late_delivery_cost_pct_revenue'], 1)} of revenue)",
        "capex": f"freed capacity that is not sold ({pc(1 - RES['demand_capture_pct'])}) defers capex at {pc(RES['capex_carry_cost_pct'])} carry",
    }
    cats = sorted(gross, key=lambda c: -adj[c])
    rows = [[labels[c], lever[c], m(gross[c], 2), pc(conf[c]), m(adj[c], 2)] for c in cats]
    rows.append(["Total per plant-year", f"Plant revenue {m(DER['plant_revenue_usd'], 0)} (Contoso US$2.0B ÷ 8 plants)", m(sum(gross.values()), 2), "", m(sum(adj.values()), 2)])
    d.table(
        f"Each plant is worth about {m(UNIT['benefit_per_plant_year_risk_adjusted'], 2)} a year at maturity after risk adjustment",
        ["Benefit lever", "Base assumption", "Gross", "Confidence", "Risk-adjusted"],
        rows, col_weights=[3.0, 5.4, 1.0, 1.0, 1.3], align=["left", "left", "right", "right", "right"], highlight_rows=[len(rows) - 1], font_pt=11,
        source=f"Source: {MODEL_SRC} — benefits.steady_state_per_plant_gross / confidence / risk_adjusted (US$ per plant-year, steady state).",
        notes=f"This is the per-plant value build at steady state. Each lever has a gross value from a simple formula on plant revenue of {m(DER['plant_revenue_usd'], 0)}, then a confidence factor that reflects how measurable it is: downtime, maintenance and scrap at 80 percent, energy at 90, throughput and inventory at 60, capex deferral at 40. The risk-adjusted total per plant is {m(UNIT['benefit_per_plant_year_risk_adjusted'], 2)} a year against about {m(UNIT['azure_per_plant_year_incl_shared_share'] + UNIT['other_run_cost_per_plant_year'], 2)} of run cost, so each added plant pays back about {UNIT['payback_months_after_go_live_single_plant']:.1f} months after go-live. The formulas are in the assumptions file.")

    # P3 — cost bridge (waterfall) ---------------------------------------------------------------------------------------------------------------------
    oc = OTHER_COSTS
    azure_total = sum(COST["azure_total_by_year"])
    bridge = [("Benefits", BEN3), ("Integration", -sum(oc["integration"])), ("Platform licences", -sum(oc["licences"])), ("AgentOps people", -sum(oc["agentops"])),
              ("Azure run cost", -azure_total), ("Hardware & support", -(sum(oc["edge_hardware"]) + sum(oc["hardware_support"]))), ("Change mgmt", -sum(oc["change_management"])),
              ("Assessment & contingency", -(sum(oc["assessment"]) + sum(oc["contingency"])))]
    assert abs(sum(v for _, v in bridge) - NET3) < 1.0, "cost bridge does not reconcile to net benefit"
    wf = d.waterfall(
        f"Where the money goes: {m(BEN3)} of benefit less {m(COST3)} of cost leaves {m(NET3)} over three years",
        [((f"{name} {MINUS}{abs(v) / 1e6:.1f}" if v < 0 else name), round(v / 1e6, 2)) for name, v in bridge], number_format='$#,##0"M"', total_label="Net benefit",
        subtitle="US$ millions, Base case, three-year totals",
        commentary=[f"Azure run cost is **{pc(azure_total / COST3, 1)}** of total cost ({m(azure_total, 2)}) at list price",
                    f"Integration is the largest cost: {k(RES['integration_per_plant_first_usd'])} per plant for the first {RES['integration_first_plants_count']}, then {k(RES['integration_per_plant_next_usd'])} with templates",
                    f"AgentOps: {RES['agentops_fte_central']} central FTE plus {RES['agentops_fte_per_plant']} per live plant — humans on the loop",
                    f"Benefits are **{BEN3 / COST3:.1f}×** the cost over three years; net benefit **{m(NET3)}** (ROI {ROI_PCT:.0f}%)"],
        commentary_title="So what",
        source=f"Source: {MODEL_SRC} — benefits.total, costs.azure_total_by_year, costs.other_by_category (3-year sums).",
        notes=f"A bridge for the CFO. Three-year benefits of {m(BEN3)} on the left; costs come off one by one. Integration is the largest, because the platform foundation and the first plants carry the learning; it falls per plant as templates are reused. Platform licences and the AgentOps team, two central people plus half a person per live plant, follow. Azure run cost at list price is only {pc(azure_total / COST3, 1)} of total cost. Benefits are {BEN3 / COST3:.1f} times the cost, which leaves {m(NET3)} of net benefit. Contingency of ten percent on one-time costs is included, as is the readiness assessment.")
    for shape in wf.shapes:  # amounts sit in the category names: bars for the small costs are too thin to carry a label
        if getattr(shape, "has_chart", False) and shape.has_chart:
            cost_series = shape.chart.plots[0].series[2]
            for pi, val in enumerate(cost_series.values):
                if val:
                    cost_series.points[pi].data_label.text_frame.text = "\u00a0"

    # P4 — costs by category and year ------------------------------------------------------------------------------------------------------------------------------
    cl = COST["category_labels"]
    order_c = ["edge_hardware", "integration", "change_management", "agentops", "licences", "hardware_support", "assessment", "contingency"]
    cost_rows = [["Azure consumption (list price)"] + [m(v, 2) for v in COST["azure_total_by_year"]] + [m(azure_total, 2)]]
    cost_rows += [[cl[c]] + [m(v, 2) for v in oc[c]] + [m(sum(oc[c]), 2)] for c in order_c]
    cost_rows.append(["Total cost"] + [m(v, 2) for v in COST_Y] + [m(COST3, 2)])
    d.table(
        "Costs by category and year: front-loaded integration, then licences and people as plants go live",
        ["Cost category", "Year 1", "Year 2", "Year 3", "3-year total"], cost_rows,
        col_weights=[4.6, 1.3, 1.3, 1.3, 1.5], align=["left", "right", "right", "right", "right"], highlight_rows=[len(cost_rows) - 1], font_pt=11,
        source=f"Source: {MODEL_SRC} — costs.azure_total_by_year and costs.other_by_category (US$ millions, Base).",
        notes=f"The full cost table, for the finance team. Year 1 is {m(COST_Y[0], 2)}, dominated by integration and the platform foundation, edge hardware and the readiness assessment. Years 2 and 3 are {m(COST_Y[1], 2)} and {m(COST_Y[2], 2)} as licences, AgentOps and Azure consumption scale with live plants. Hardware covers three edge servers, OT network security, sensor retrofit on about 15 percent of assets and legacy gateways per plant. Change management and training are {m(CHANGE_3Y, 2)} over three years. Every line is driven by an assumption in the assumptions file; none is hard-coded in the model.")

    # P5 — scenarios ---------------------------------------------------------------------------------------------------------------------------------------------------
    def three(fn) -> list[str]:
        return [fn(HC), fn(HB), fn(HU)]
    scen_rows = [
        ["3-year benefit (risk-adjusted)"] + three(lambda h: m(h["total_benefit"])),
        ["3-year cost"] + three(lambda h: m(h["total_cost"])),
        ["Net benefit"] + three(lambda h: m(h["net_benefit"])),
        ["NPV at 10%"] + three(lambda h: m(h["npv"])),
        ["ROI (net ÷ cost)"] + three(lambda h: f"{MINUS if h['roi_pct'] < 0 else ''}{abs(h['roi_pct']):.0f}%"),
        ["Payback (months from programme start)"] + three(lambda h: f"{h['payback_months']:.0f}"),
        ["IRR"] + three(lambda h: f"{MINUS if h['irr_pct'] < 0 else ''}{abs(h['irr_pct']):.0f}%"),
        ["5-year NPV (memo)"] + three(lambda h: m(h["npv_5yr"])),
        ["Steady-state benefit at 8 plants (per year)"] + three(lambda h: m(h["steady_state_benefit_per_year"])),
        ["Azure run cost: Year 3 · run-rate (per year)"] + three(lambda h: f"{m(h['acr_year3'], 2)} · {m(h['acr_run_rate'], 2)}"),
        ["Optional expansion modules E1–E5"] + ["off", "off", "on"],
    ]
    adoption_txt = ", ".join(f"{lid} {pc(a)}" for lid, a in LEVER_ADOPT.items())
    d.table(
        f"Scenarios: the Conservative case is slightly negative on a 3-year view, the Base pays back in {PAYBACK:.0f} months",
        ["Metric", "Conservative", "Base", "Upside"], scen_rows,
        col_weights=[4.6, 2.0, 2.0, 2.0], align=["left", "right", "right", "right"], highlight_rows=[3], font_pt=11.5,
        subtitle=f"Scenarios vary {N_SCENARIO_VARIED} of {len(ASSUMP)} assumptions (benefit levers, ramp, roll-out pace, costs, usage, expansion-module adoption); all other inputs are identical",
        source=f"Source: {MODEL_SRC} — headline by scenario. Upside: faster ramp and roll-out, lower costs and the expansion modules on (share of live plants: {adoption_txt}).",
        notes=f"Three scenarios share one model and differ only in {N_SCENARIO_VARIED} assumptions. Conservative combines a slower ramp, later go-live, a slower roll-out of 1, 4 and 7 plants, lower levers and higher costs: a 3-year NPV of {m(HC['npv'])}, but {m(HC['npv_5yr'])} on a five-year memo view. Upside combines a faster ramp and roll-out with higher levers and switches on the five optional expansion modules, so its cost rises to {m(HU['total_cost'])} and its benefit to {m(HU['total_benefit'])}: NPV {m(HU['npv'])}. Modules are an investment first, so inside three years they cost some NPV. NPV and payback are the headline measures; IRR needs care because early outlay is small.")

    # P5b — optional expansion modules, customer economics -------------------------------------------------------------------------------------------------------------
    module_what = {
        "E1": "Inline machine-vision inspection: cameras, edge GPU servers and a review queue for low-confidence frames",
        "E2": "kHz vibration and acoustic monitoring of rotating assets for earlier failure detection",
        "E3": "Continuous sim-first what-if at scale: Monte-Carlo rehearsal of every consequential decision; higher autonomy earned",
        "E4": "Enterprise data platform: historian migration to a lake, enterprise analytics and BI at scale",
        "E5": "OT security and connectivity hardening: diverse network path, firewall hubs, OT monitoring and SIEM",
    }
    mod_rows = []
    for lid, lv in EXP_BY_ID.items():
        p = lv["per_deploying_plant"]
        mod_rows.append([LEVER_SHORT[lid], module_what[lid], k(p["benefit"]), k(p["azure_run_cost"] + p["other_run_cost"]), k(p["one_time_cost"]), k(p["net"]),
                         f"{p['payback_months']:.0f} months" if p["payback_months"] else "none"])
    e4f = EXP_BY_ID["E4"]["enterprise_fixed"]
    d.table(
        f"Optional expansion modules E1–E4 each pay back in {min(LEVER_PAYBACKS):.0f}–{max(LEVER_PAYBACKS):.0f} months once running; E5 is a risk and compliance module",
        ["Module", "What it adds", "Benefit / year", "Run cost / year", "One-time cost", "Net / year", "Simple payback"],
        mod_rows, col_weights=[2.4, 4.7, 1.2, 1.3, 1.2, 1.1, 1.3], align=["left", "left", "right", "right", "right", "right", "right"], font_pt=11,
        subtitle="Per deploying plant, steady state, Base inputs, risk-adjusted benefit; run cost = Azure at list price + people, licences and hardware support. Off in Base, on in Upside",
        takeaway=f"Bought one at a time: with Base inputs and all five on, 3-year NPV is {m(EXP_H['npv'])} against {m(NPV)}, and 5-year NPV {m(EXP_H['npv_5yr'])} against {m(HB['npv_5yr'])}.",
        source=f"Source: {MODEL_SRC} — expansion.levers. E4 adds a {k(e4f['one_time_cost'])} programme and {k(e4f['azure_run_cost_at_reference_scale'] + e4f['other_run_cost'])} a year at 8 plants. Assumptions to validate; Power BI and Defender for IoT are Microsoft 365 licences {ref('m365')}.",
        notes=f"Upside switches on five optional expansion modules, shown per deploying plant at steady state with risk-adjusted benefits. Machine vision, high-frequency condition monitoring, continuous what-if at scale and the enterprise data platform each earn back their own cost within {min(LEVER_PAYBACKS):.0f} to {max(LEVER_PAYBACKS):.0f} months once running. OT security and connectivity hardening roughly breaks even on expected-loss value and is bought for risk and compliance. Inside three years the modules cost NPV because the investment comes first: with Base inputs and all five on, NPV is {m(EXP_H['npv'])} against {m(NPV)}, and the five-year NPV {m(EXP_H['npv_5yr'])} against {m(HB['npv_5yr'])}. Each is a separate decision.")

    # P6 — differentiation ----------------------------------------------------------------------------------------------------------------------------------------------------
    C, P, N = "Core", "Partial", "—"
    d.table(
        "Nightshift complements the Microsoft building blocks and industrial suites with a governed, measurable swarm",
        ["Capability", "Dashboards and analytics", "Point predictive-maintenance tools", "Engineering copilots", "Nightshift"],
        [["Sim-first validation of actions on a forked twin", N, N, N, C],
         ["Autonomy levels per decision class, policy-as-code, kill switch", N, N, N, C],
         ["Tamper-evident decision ledger with counterfactuals", N, N, N, C],
         ["Multi-objective swarm arbitration with explainable utility", N, N, N, C],
         ["Acts on the plant within guardrails", N, P, N, C],
         ["Counterfactual A/B value measurement and ROI" + ("/ACR" if azure else "") + " calculator", N, P, N, C],
         ["Readiness assessment and roadmap", N, N, N, C],
         ["Strength in one narrow task (alerts, remaining life, code help)", P, C, C, "Partial — by design a swarm"]],
        col_weights=[4.6, 1.7, 1.9, 1.6, 1.9], align=["left", "center", "center", "center", "center"], font_pt=11.5,
        subtitle="Qualitative, category-level view — individual products vary and evolve; no vendor is named or disparaged",
        takeaway=f"Built on Azure IoT Operations {ref('iotops')}, Fabric Real-Time Intelligence {ref('fabric')} and Foundry Agent Service {ref('foundry')} — a solution on these blocks, not a replacement.",
        source=f"Sources: SwarmAI PRD §12; Siemens Industrial Copilot built with Azure OpenAI {ref('siemenscopilot')}; AWS retirement notice for Lookout for Equipment {ref('aws')}. Fabric operations agents are in preview; no roadmap commitment is implied.",
        notes="A qualitative view, by category rather than by vendor. Dashboards and analytics platforms show what happened; point predictive-maintenance tools are excellent at one failure mode; engineering copilots help people write and understand automation. None of them, by category, coordinates competing objectives under explicit guardrails, rehearses actions on a twin, keeps a tamper-evident ledger or measures its own value by counterfactual replay. Nightshift is built on Microsoft building blocks, including Fabric operations agents which are in preview, so it complements rather than replaces them and implies no Microsoft roadmap commitment. The market is also consolidating from point services to platforms.")

    # P7–P9 — feature list with status --------------------------------------------------------------------------------------------------------------------------------------------
    d.set_section("Appendix · features")
    chunks = [FEATURES[0:9], FEATURES[9:18], FEATURES[18:25]]
    for i, chunk in enumerate(chunks, 1):
        d.table(
            f"All {N_FEATURES} Release-1 features with priority and status — part {i} of 3",
            ["ID", "Feature", "Epic", "Priority", "Status"],
            [[f["id"], f["name"], f["epic"], f["prio"], f["status"]] for f in chunk],
            col_weights=[0.8, 4.0, 3.6, 0.9, 1.4], align=["left", "left", "left", "center", "left"], font_pt=12,
            source=f"Source: FEATURES.md status board, read at build time ({N_DEPLOYED} deployed, {N_TESTED} tested or deployed of {N_FEATURES}). Status values: Planned, In progress, Implemented, Tested, Deployed ✔.",
            notes=f"The complete Release-1 feature list, with priority and the current status taken from the engineering status board when this deck was built. Priorities: P0 means the demonstration cannot work without it, P1 is Release-1 depth, P2 is a stretch. Status moves from Planned through Implemented and Tested to Deployed, which means the feature was exercised by the smoke test against the Azure deployment. Part {i} of three. At build time {N_DEPLOYED} of {N_FEATURES} features are deployed and {N_TESTED} are tested or deployed. The Release 2 and later roadmap, DF-26 to DF-46, is in the features document and is product intent only.")

    # P10 — real vs simulated ------------------------------------------------------------------------------------------------------------------------------------------------------------
    d.set_section("Appendix · reference")
    d.table(
        "Release 1 is real software over a simulated plant; production services plug in behind the same interfaces",
        ["Layer", "Reference implementation (Release 1)", "Production target"],
        [["Plant, sensors, PLCs, AMRs", "Simulated: seeded, deterministic, same interfaces", "Real equipment via Azure IoT Operations (OPC UA, MQTT)"],
         ["Telemetry, namespace, twin, what-if", "Real software over the simulator", "Event Hubs → Fabric Real-Time Intelligence; Azure Digital Twins or Fabric digital twin builder"],
         ["Agents, Supervisor, policy engine, ledger, KPI engine", "Real software, deterministic by default; one Container App", "Same code on Container Apps or AKS and at the edge"],
         ["Language-model features", "Real: Azure OpenAI through Foundry with managed identity (gpt-5.4-mini chat, gpt-5.4 reasoning)", "Foundry Agent Service, AI Search grounding, DataZone or regional deployments"],
         ["MES, ERP, CMMS, Teams, grid feeds", "Simulated or optional webhook behind ports", "Certified connectors (for example SAP, Siemens, Rockwell, AVEVA, Dynamics 365)"],
         ["Safety functions", "Simulated; no safety-rated claim", "Certified safety PLCs and relays remain authoritative"],
         ["Identity, network, governance", "Keyless: managed identity and Entra RBAC; public endpoints in a sandbox subscription", "Entra ID with PIM, private endpoints, landing zone with policy-compliant configuration"]],
        col_weights=[2.6, 4.4, 4.2], font_pt=11.5,
        source="Source: SwarmAI PRD §6.5 and ARCHITECTURE §19 (implemented vs target). Demo resources carry sandbox governance tags; production landing zones use private endpoints and policy-compliant settings.",
        notes="Honesty about what is real. The plant is simulated, deterministically, behind the same interfaces a production integration would use; the software that matters — telemetry handling, twin and what-if, agents, Supervisor, policy engine, ledger, KPI engine, copilot — is real and deployed on Azure with keyless managed-identity access. MES, ERP, grid feeds and Teams are simulated or optional webhooks. Safety functions are simulated and carry no safety-rated claim. The right-hand column is the production target: IoT Operations at the edge, Fabric and Digital Twins in the cloud, certified connectors, private networking and a policy-compliant landing zone.")

    # P11 — glossary -----------------------------------------------------------------------------------------------------------------------------------------------------------------------------
    d.table(
        "Glossary of terms used in this deck",
        ["Term", "Meaning"],
        [row for row in [["ACR", "Azure Consumed Revenue — Azure usage billed to the customer, here at list price"]] if azure] + [
         ["A/B replay", "The same seeded scenario run with the swarm OFF and ON, compared with confidence intervals"],
         ["Autonomy Dial", "Autonomy level L0 (observe) … L5 (lights-out), set per decision class"],
         ["Blast radius", "Maximum set of assets, orders or money an action may affect without approval"],
         ["Decision Ledger", "Append-only, hash-chained record of observations, proposals, simulations, decisions, actions and outcomes"],
         ["Digital twin", "Live model of the plant (assets, state, health, KPIs) that can be forked for what-if analysis"],
         ["Expansion modules (E1–E5)", "Optional modules with their own cost, benefit and Azure meters: machine vision, kHz monitoring, simulation at scale, enterprise data platform, OT security"],
         ["OEE · OTIF", "Overall equipment effectiveness (availability × performance × quality) · on-time-in-full"],
         ["Policy-as-code", "Autonomy and guardrail rules held as versioned, tested files evaluated by a deterministic engine"],
         ["Purdue model", "Reference model segmenting plant networks into levels 0–5 with an OT/IT demilitarised zone"],
         ["Sim-first", "Every consequential action is rehearsed on a forked twin before execution"],
         ["Unified Namespace", "One hierarchical (ISA-95) topic space for plant data, served by an MQTT broker"],
         ["Shadow mode", "Agents run on live or replayed data and propose; humans act; nothing is executed"]],
        col_weights=[2.0, 9.4], font_pt=11.5,
        source="Source: SwarmAI PRD §19 (glossary).",
        notes="A short glossary for the terms that appear most often. " + ("ACR is Azure consumed revenue, here modelled at list price. " if azure else "OEE and OTIF are the two operations metrics we quote most. ") + "A/B replay is the counterfactual method behind the measured-value claim. The Autonomy Dial is the level of independence set per decision class, from observe to lights-out. Blast radius limits how much an action may affect without approval. The Decision Ledger is the hash-chained audit record. Sim-first means rehearsing every consequential action on a forked twin. The Purdue model segments plant networks, and the Unified Namespace is one topic space for plant data. Shadow mode means agents propose while humans act. The full glossary is in the PRD.")

    # extra screenshots (beyond the product tour in the main body) -------------------------------------------------------------------------------------------------------
    extra = tour_files()[MAX_TOUR_IN_MAIN:]
    if extra:
        d.set_section("Appendix · more screens")
        add_screens(d, extra)

    # sources -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
    d.set_section("Appendix · sources")
    d.sources(
        "Sources", [text for _, text in SOURCES], per_slide=14,
        notes="Every external statistic in this deck is traceable to a source listed here, with publisher, title, year and URL. Microsoft Learn pages and the Azure Retail Prices API underpin the architecture and the unit prices. Regulation texts come from EUR-Lex. A few publisher sites, such as ISO and MarketsandMarkets, block automated access, so those figures were confirmed through search results and are flagged as such in the PRD; items marked secondary summarise a primary source. Figures are paraphrased, not quoted at length. Anything not sourced here is labelled as an assumption on the slide and in the assumptions file.")


# ----------------------------------------------------------------------------------------------------------------------
# build
# ----------------------------------------------------------------------------------------------------------------------
def check_notes(d: Deck, name: str) -> list[str]:
    problems = []
    for i, s in enumerate(d.prs.slides, 1):
        txt = s.notes_slide.notes_text_frame.text if s.has_notes_slide else ""
        n = len(txt.split())
        if not 60 <= n <= 120:
            problems.append(f"{name} slide {i}: notes have {n} words (need 60–120)")
    return problems


def build(azure: bool) -> Deck:
    d = Deck(Theme.dark_factory(), footer=FOOTER, title="SwarmAI Dark Factory (Nightshift) — Executive deck")
    main_slides(d, azure)
    if azure:
        azure_slides(d)
    appendix_slides(d, azure)
    return d


def main() -> int:
    exit_code = 0
    for azure, name in ((True, FULL_NAME), (False, CUSTOMER_NAME)):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # deckkit also records every warning in d.warnings
            d = build(azure)
        path = d.save(OUT_DIR / name)
        problems = list(d.warnings) + check_notes(d, name)
        print(f"{path.name}: {len(d.prs.slides)} slides, {len(problems)} problems")
        for p in problems:
            print("  -", p)
        exit_code |= 1 if problems else 0
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
