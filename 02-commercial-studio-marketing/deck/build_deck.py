"""Build the Spotlight (Commercial Studio) executive deck with deckkit.

    /Users/michalfu/Dev/SwarmAI/.venv/bin/python deck/build_deck.py

* Every number on a slide is read from ../business-case/outputs.json (or assumptions.json) or comes from a cited source.
* Product-tour slides are built from the PNGs in deck/assets/screens/: four annotated slides in the main deck, the rest as two-up galleries
  in the appendix. A slide whose PNG is missing is skipped; any PNG that is not placed is appended as a plain screenshot slide.
* Measured evidence (tests, smoke checks, latency, cost) is quoted from REPORT-TEST-AND-DEPLOYMENT.md; business-case numbers only from outputs.json.
* Re-runnable and idempotent: the .pptx is regenerated from scratch each time.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, "/Users/michalfu/Dev/SwarmAI/tools/deckkit")
import deckkit  # noqa: E402
from deckkit import Deck, Para, Theme  # noqa: E402
from pptx.dml.color import RGBColor  # noqa: E402
from pptx.enum.shapes import MSO_SHAPE, MSO_SHAPE_TYPE  # noqa: E402
from pptx.util import Inches, Pt  # noqa: E402

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OUT = Path(os.environ.get("DECK_OUT", HERE / "CommercialStudio-Executive-Deck.pptx"))
SCREENS = Path(os.environ.get("DECK_SCREENS", HERE / "assets" / "screens"))

OUTPUTS = json.loads((ROOT / "business-case" / "outputs.json").read_text(encoding="utf-8"))
ASSUME = json.loads((ROOT / "business-case" / "assumptions.json").read_text(encoding="utf-8"))
S = OUTPUTS["scenarios"]
B, C, U = S["base"], S["conservative"], S["upside"]
META = OUTPUTS["meta"]
PRICES = ASSUME["pricing"]["items"]
AS = ASSUME["assumptions"]


def M(x: float, d: int = 2) -> str:
    return f"${x / 1e6:,.{d}f}M"


def K(x: float) -> str:
    return f"${x / 1e3:,.0f}k"


def D(x: float, d: int = 0) -> str:
    return f"${x:,.{d}f}"


def P(x: float, d: int = 0) -> str:
    return f"{x:.{d}f}%"


def SM(x: float) -> str:
    """Signed money: +$1.06M / −$45k."""
    sign = "+" if x >= 0 else "−"
    return f"{sign}{M(abs(x))}" if abs(x) >= 1e6 else f"{sign}{K(abs(x))}"


def MK(x: float) -> str:
    return M(x) if abs(x) >= 1e6 else K(x)


roi, acr, ue = B["roi"], B["acr"], B["unit_economics"]
ben = B["benefits"]
cost = B["costs"]
BY = ben["total_by_year"]
CY = cost["total_by_year"]
tiers = {t["tier"]: t for t in acr["tiers"]}
bycls = ue["by_class"]
sens = {d["id"]: d for d in B["sensitivity"]}
ACR_Y = acr["by_year"]
benefit_per_azure = ben["total"] / sum(acr["by_year"])

FOOTER = "SwarmAI · Commercial Studio (Spotlight) · Confidential draft · Illustrative, assumption-driven - validate with customer data"
d = Deck(Theme.commercial_studio(), footer=FOOTER, title="SwarmAI Commercial Studio - Executive deck")

SRC_BC_BARE = f"business-case/outputs.json (Base scenario, model v{META['model_version']})"
SRC_BC = "Source: " + SRC_BC_BARE
EVID_SRC = "REPORT-TEST-AND-DEPLOYMENT.md (verified 17-18 Nov 2026)"

# ======================================================================================================================
# 1. Title
# ======================================================================================================================
d.title_slide(
    "Spotlight: the AI commercial studio",
    "A crew of governed agents that turns a brief into brand-safe, localised and measurable campaigns - on Azure",
    tagline="SWARMAI · COMMERCIAL STUDIO",
    meta="Executive briefing · November 2026 · Reference customer: Contoso Consumer Brands (fictional)",
    notes=("Welcome. In the next twenty minutes I will show how a crew of governed AI agents can take a brief to broadcast, why it is safe enough "
           "for a regulated brand, and what it is worth. The reference customer is Contoso Consumer Brands, a fictional eight-billion-dollar consumer group. "
           "Everything you see is either a cited market fact, an output of the business-case model, or a working feature of the reference implementation "
           "running on Azure with synthetic data. Where something is simulated, the slide says so. Please challenge the assumptions; that is the point of the pilot."),
)

# ======================================================================================================================
# 2. Executive summary
# ======================================================================================================================
d.bullets(
    "Ship 10× the content with governance built in, and pay back the investment in about 15 months",
    [
        "**Problem** - budgets are flat at 7.8% of revenue while content demand grows 5× and EU AI-content rules now apply",
        "**Solution** - eight governed agents, five human gates and a Brand Brain turn a brief into localised, testable campaigns",
        "**Proof** - Release 1 is live on Azure: 24 of 24 features deployed, 97 tests and 30/30 live smoke checks pass",
        f"**Outcome** - Base case NPV **{M(roi['npv'])}**, ROI **{P(roi['roi_pct'])}**, payback **{roi['payback_months']:.0f} months** for a US$8B group",
        "**Ask** - a 12-week, one-brand pilot that replaces our assumptions with your data",
    ],
    side_title="Headline numbers (Base, 3 years)",
    side_items=[
        f"NPV **{M(roi['npv'])}** · ROI **{P(roi['roi_pct'])}** · IRR **{P(roi['irr_pct'])}**",
        f"Benefit **{M(ben['total'], 1)}** vs cost **{M(cost['total'], 1)}**: net **{M(roi['cumulative'][-1], 1)}** over 3 years",
        f"Payback **{roi['payback_months']:.1f} months** (Conservative {C['roi']['payback_months']:.0f}, Upside with expansion packs {U['roi']['payback_months']:.0f})",
        f"NPV range **{M(C['roi']['npv'])}** (Conservative) to **{M(U['roi']['npv'])}** (Upside, incl. optional expansion packs)",
        f"Benefits can fall **{P(roi['breakeven_benefit_haircut_pct'])}** before NPV turns negative",
        f"Cost per approved version **{D(ue['studio_all_in_cost_per_version'])}** vs **{D(ue['agency_blended_cost_per_baseline_asset'])}** agency blend",
        f"Azure is only **{P(roi['azure_share_of_benefit_pct'], 1)}** of benefit",
    ],
    takeaway="Start with a pilot; let measured results replace the assumptions.",
    source="Sources: Gartner 2026 CMO Spend Survey; Adobe 2025; EC Article 50 quick facts; " + SRC_BC_BARE + "; " + EVID_SRC,
    notes=("The headline: marketing is being asked for roughly ten times the content on flat budgets, while the rules for AI-generated content have just started to apply. "
           "Spotlight answers with a crew of governed agents, and Release 1 is already live on Azure: all twenty-four features are deployed, and ninety-seven tests and a thirty-check live smoke test pass. "
           f"In our Base case for Contoso the three-year net present value is {M(roi['npv'])}, payback is about fifteen months, and benefits could fall by more than half before the case turns negative. "
           "Azure itself is about five percent of the benefit. The ask is a twelve-week pilot on one brand, so that your purchase-order data and a holdout test replace our assumptions."),
)

# ======================================================================================================================
# 3. Why now
# ======================================================================================================================
d.kpi_cards(
    "Budgets are flat, content demand is 5× and AI-content rules are now live",
    [
        {"value": "7.8%", "label": "Marketing budget as % of revenue", "sub": "Flat vs 7.7% in 2025 · Gartner 2026"},
        {"value": "5×", "label": "Content demand expected by 2027", "sub": "71% of marketers · Adobe 2025"},
        {"value": "US$1.34T", "label": "Global ad spend in 2026 (+11.9%)", "sub": "WARC Media, Oct 2026"},
        {"value": "56%", "label": "of CMOs lack budget for their 2026 strategy", "sub": "Gartner 2026 CMO Spend Survey"},
        {"value": "2 Aug 2026", "label": "EU AI Act Article 50 transparency applies", "sub": "Marking + deepfake labels · European Commission"},
        {"value": "27 Sep 2026", "label": "EU green-claims rules apply", "sub": "Directive (EU) 2024/825 · EUR-Lex"},
    ],
    takeaway="Volume and governance are colliding: that is the opening for a governed studio.",
    source="Sources: Gartner (May 2026); Adobe (2025); WARC (Oct 2026); European Commission (Jul 2026); EUR-Lex 32024L0825",
    notes=("Four forces. Budgets have plateaued: Gartner's 2026 survey puts marketing at 7.8 percent of revenue and 56 percent of CMOs say they lack the budget for their strategy. "
           "Demand keeps rising: seventy-one percent of marketers expect content demand to grow five times or more by 2027. "
           "And the rules changed this year: Article 50 of the EU AI Act applies from 2 August 2026, with a marking grace period to December for systems already on the market, "
           "and the EU green-claims directive applies from 27 September. Question to expect: is this legal advice? No; it is context, and counsel should confirm applicability."),
)

# ======================================================================================================================
# 4. Vision: studio of agents (roles + gates)
# ======================================================================================================================
s4 = d.process(
    "A studio of agents takes a brief to broadcast, with people at five gates",
    [
        {"title": "Brief", "body": ["Briefing agent", "3 clarifying questions", "Gate: Brand Manager"]},
        {"title": "Strategy", "body": ["Strategist", "3 grounded territories", "Gate: Creative Director"]},
        {"title": "Script", "body": ["Copywriter", "6/15/30 s, claim-aware", "Gate: Creative + Legal"]},
        {"title": "Storyboard", "body": ["Art Director", "Consistent frames", "Gate: Creative Director"]},
        {"title": "Produce", "body": ["Director, Sound, Localizer", "4 ratios, 8 languages", "Format factory"]},
        {"title": "Govern + learn", "body": ["Guardian blocks failures", "Final gate: Legal + Brand", "Media Analyst learns"]},
    ],
    takeaway="Agents propose and produce; people approve; every step leaves an audit trail.",
    source="Source: PRD §5; FEATURES.md (CS-04 … CS-19)",
    notes=("This is the studio in one picture. Eight specialist agents work in a fixed pipeline: Briefing, Strategist, Copywriter, Art Director, Director and Editor, Sound Designer, Localizer "
           "and Media Analyst, with a ninth agent, the Brand Guardian, checking every stage. The pipeline is deterministic: agents act inside a stage, they never decide transitions. "
           "Five human gates sit on brief, concept, script, storyboard and final, each with a named role. If the Guardian finds a hard failure, approval is simply not possible. "
           "Likely question: is this autonomous? No; it is autonomous within a stage and human-approved between stages."),
)

cw4 = (deckkit.CONTENT_W - 0.4) / 3
for i4, (t4, b4) in enumerate([
    ("Brand Brain grounds every step", "Voice, claims context, catalogue and learnings, with citations on every output"),
    ("Brand Guardian checks every stage", "Claims, rights, identity and safety; auto-revise; hard-fails block approval"),
    ("Audit and provenance record every decision", "Hash-chained log, signed manifest and disclosure labels per asset"),
]):
    x4 = deckkit.MARGIN + i4 * (cw4 + 0.2)
    d._rect(s4, x4, 4.45, cw4, 1.3, d.t.card, radius=0.08)
    d.text(s4, x4 + 0.18, 4.55, cw4 - 0.36, 1.1, [Para(t4, bold=True, size=14, space_after=4), Para(b4, size=12)], size=12, min_size=10)

# ======================================================================================================================
# 5. Dawn Roast story
# ======================================================================================================================
d.comparison(
    "Dawn Roast: from weeks of serial, agency-led work to a governed flow of minutes of machine time",
    "Before: serial and reactive",
    [
        "6-10 weeks from brief to approved assets",
        "One hero spot; every format and language bought separately",
        "Legal finds the health claim and the music rights late",
        "A few variants; learnings stay in decks",
        f"Adapted video costs about **{D(bycls['adapted_video']['agency_cost_per_asset'])}** per asset",
    ],
    "After: Northwind Coffee Roasters with Spotlight",
    [
        "Brief to approved master, formats and localizations within 7 minutes of machine time (live run, draft quality); calendar time is set by the gates",
        "Guardian blocks \"cures morning anxiety\" and an unlicensed cue; auto-revise fixes both",
        "16:9 master plus 9:16, 1:1 and a 6 s cut-down (4:5 and 15/30 s on request); DE, FR and PL versions",
        "12 variants ranked pre-flight; the bandit shifts spend to winners",
        f"Adapted video at about **{D(bycls['adapted_video']['studio_all_in_cost_displaced_asset'])}** all-in",
    ],
    takeaway="Same brand rules, a fraction of the cost, and a receipt for every asset.",
    source="Source: brief (6-10 weeks); " + SRC_BC_BARE + ". Baselines are assumptions; 7 min = sum of the 30 live smoke checks, an upper bound (REPORT-TEST-AND-DEPLOYMENT.md §5).",
    notes=("Here is the demo story. Northwind Coffee Roasters launches Dawn Roast. The marketer pastes a brief; the Briefing agent asks three questions; Strategy proposes three territories; "
           "scripts, storyboard, voice and a fifteen-second spot follow. Then the Guardian blocks a line that claims to cure morning anxiety and a music cue that is not licensed, "
           "suggests compliant fixes and re-checks. After approval the format factory and localiser produce the pack. Be precise on timing: the whole thirty-check live smoke run, which contains this chain "
           "with three derived versions and three localizations at draft quality, took about seven minutes of machine time; calendar time depends on your gates. The costs come from the model and are assumptions until we see your invoices."),
)

# ======================================================================================================================
# 6. Governance-first trust model
# ======================================================================================================================
d.architecture(
    "Governance comes before generation: ground, govern, approve, prove",
    [
        {"name": "1 Ground", "items": ["Brand Brain (versioned)", "Voice profile + identity rules", "Catalogue + personas", "Citations on every output"]},
        {"name": "2 Govern", "items": ["Claims library per market", "Rights + consent registry", {"title": "Brand Guardian", "sub": "auto-revise loop"}, "Azure AI Content Safety"]},
        {"name": "3 Approve", "items": ["5 stage gates", "Roles incl. agency guests", "SLAs + escalation", "Hash-chained audit"]},
        {"name": "4 Prove", "items": ["Provenance manifest per asset", "Disclosure labels", "Evidence pack", "Verification endpoint"]},
    ],
    side={"name": "Cross-cutting", "items": ["Cost caps", "Tenant isolation", "Keyless identity", "Override needs a reason"]},
    takeaway="Nothing ships unless it is grounded, checked, approved and provable.",
    source="Source: PRD §5.3; FEATURES.md (CS-01, CS-02, CS-03, CS-12, CS-13, CS-14)",
    notes=("The trust model has four layers. Ground: every agent retrieves from the Brand Brain and cites it. Govern: the claims library, the rights and consent registry, the Guardian and Azure AI Content Safety "
           "evaluate every stage; failures block approval. Approve: five stage gates with roles, SLAs and a hash-chained audit log. Prove: each asset gets a provenance manifest, disclosure labels and an evidence pack that "
           "a regulator or platform can verify. Cross-cutting: cost caps, tenant isolation, keyless identity. Question to expect: does the Guardian replace legal? No; it pre-screens and documents, and legal keeps the override with a recorded reason."),
)

# ======================================================================================================================
# 7. Capability map
# ======================================================================================================================
d.capability_map(
    "Release 1 is live on Azure: all 24 features are deployed",
    [
        {"name": "A · Brand Brain & governance data", "items": ["CS-01 Brand Brain", "CS-02 Claims library", "CS-03 Rights & consent"]},
        {"name": "B · Creative pipeline", "items": ["CS-04 Briefing", "CS-05 Strategy", "CS-06 Script & copy", "CS-07 Storyboard", "CS-08 Spot compositor", "CS-09 Voice & audio", "CS-10 Localization", "CS-11 Format factory"]},
        {"name": "C · Governance & safety", "items": ["CS-12 Brand Guardian", "CS-13 Approvals & audit", "CS-14 Disclosure & provenance", "CS-15 Budget guardrails"]},
        {"name": "D · Performance", "items": ["CS-16 Pre-flight scorecard", "CS-17 Variants & bandit", "CS-18 Ingestion & insights", "CS-19 Media-mix hints"]},
        {"name": "E · Platform", "items": ["CS-20 Studio UI", "CS-21 Asset library", "CS-22 Roles & integrations", "CS-23 ROI & ACR calculator", "CS-24 Observability & IaC"]},
    ],
    takeaway="97 tests (88% coverage), 18/18 browser journeys and 30/30 live smoke checks pass; every feature has acceptance criteria and evidence.",
    source="Source: FEATURES.md (status board, all Deployed); " + EVID_SRC + " §1, §3-§5",
    notes=("Release 1 is complete and deployed: twenty-four features in five epics, every one showing Deployed on the status board with evidence. Epic A holds the Brand Brain, claims library and rights registry. "
           "Epic B is the creative crew from briefing to format factory. Epic C is governance and safety. Epic D closes the loop with the scorecard, variant engine and insights. Epic E is the platform, "
           "including this calculator. Engineering verified it on 17 and 18 November: ninety-seven automated tests at 88 percent coverage, eighteen browser journeys and a thirty-check smoke test against the live Azure deployment. "
           "The appendix lists every feature and the evidence table."),
)

# ======================================================================================================================
# 8-10. Product tour: annotated screenshots of the live deployment (the calculator slide follows the ROI slide; every other screen is in the appendix)
# ======================================================================================================================
screens = sorted(p for p in SCREENS.glob("*.png")) if SCREENS.exists() else []
placed: set[str] = set()
TOUR_SRC = "Screenshot: live reference implementation on Azure (swedencentral), synthetic data. Evidence: " + EVID_SRC


def shot(name: str) -> Path | None:
    p = SCREENS / name
    if p.exists():
        placed.add(name)
        return p
    return None


def set_alt(pic, text: str) -> None:
    pic._element.nvPicPr.cNvPr.set("descr", text)


def annotate(slide, regions: list[tuple], alt: str) -> None:
    """Outline regions of the 1600x900 screenshot so that each numbered callout points at something visible.
    A region is (x0, y0, x1, y1, badge_x, badge_y) in source pixels; badge_x = None draws the outline without a number."""
    pic = next(sh for sh in slide.shapes if sh.shape_type == MSO_SHAPE_TYPE.PICTURE)
    set_alt(pic, alt)
    emu = 914400
    sx, sy = pic.width / 1600, pic.height / 900
    r, n = 0.15, 0
    for x0, y0, x1, y1, _bx, _by in regions:
        d._rect(slide, (pic.left + x0 * sx) / emu, (pic.top + y0 * sy) / emu, (x1 - x0) * sx / emu, (y1 - y0) * sy / emu, None, d.t.accent, radius=0.05, line_pt=2.25)
    for _x0, _y0, _x1, _y1, bx, by in regions:
        if bx is None:
            continue
        n += 1
        cx, cy = (pic.left + bx * sx) / emu, (pic.top + by * sy) / emu
        badge = d._rect(slide, cx - r, cy - r, 2 * r, 2 * r, d.t.accent, "FFFFFF", shape=MSO_SHAPE.OVAL, line_pt=1.5)
        d.text(slide, cx - r, cy - r, 2 * r, 2 * r, [Para(str(n), bold=True, space_after=0)], size=11, color="FFFFFF", align="center", anchor="middle",
               fit=False, inset=0, shape=badge)


def tour_slide(n: int, name: str, title: str, caption: str, callouts: list[str], regions: list[tuple], takeaway: str, notes: str, alt: str,
               real: str, sim: str, sim_label: str = "Simulated"):
    path = shot(name)
    if path is None:
        return None
    d.set_section(f"Product tour {n}/4 · live on Azure, synthetic data")
    s = d.screenshot(title, path, caption=caption, callouts=callouts, takeaway=takeaway, notes=notes, source=TOUR_SRC)
    annotate(s, regions, alt)
    pic = next(sh for sh in s.shapes if sh.shape_type == MSO_SHAPE_TYPE.PICTURE)
    pw = pic.width / 914400
    cx, cwid = deckkit.MARGIN + pw + 0.5, deckkit.CONTENT_W - pw - 0.5
    d._rect(s, cx + 0.2, 4.62, cwid - 0.4, 0.014, d.t.line)
    d.text(s, cx + 0.2, 4.7, cwid - 0.4, 1.2,
           [Para(f"**Real:** {real}", size=11.5, space_after=5), Para(f"**{sim_label}:** {sim}", size=11.5, space_after=0)],
           size=11.5, min_size=9, color=d.t.muted, label="real vs simulated")
    d.set_section(None)
    return s


tour_slide(
    1, "13-guardian-report-blocked.png",
    "A live Guardian blocks the unsafe script, says why and proposes the fix",
    "Brand Guardian report on the live deployment: a deliberately unsafe subject scores 0/100 and is blocked",
    [
        "Verdict **BLOCK**, score 0/100: 9 blocking findings and 1 warning across eight check categories",
        "Every finding names the rule and quotes the text, with a compliant fix: “cures morning anxiety” → “brings a calmer start to your morning”",
        "“Auto-revise (≤3 iterations)” applies the fixes and re-checks; in the live smoke test it converged in 2 iterations",
    ],
    [(950, 160, 1415, 244, 936, 190), (950, 372, 1545, 700, 936, 430), (303, 780, 680, 826, 283, 803)],
    "Approval stays impossible while a blocking finding is open; only Legal can override, with a recorded reason.",
    ("This is the real Brand Guardian on the live deployment, checking a deliberately unsafe subject: a forbidden word, two prohibited health claims, a missing caffeine disclaimer, an off-palette end card, "
     "an unlicensed track, an expired talent consent, stock outside its territory and a missing AI label. The verdict is BLOCK with nine blocking findings, each showing the rule, the evidence and a compliant fix. "
     "Auto-revise applies the fixes and re-checks; in the live smoke test the generated script was blocked at 56 out of 100 and converged in two iterations. Approval is refused while a block is open. "
     "Question to expect: does it replace legal? No; it pre-screens, documents and keeps the legal override."),
    "Brand Guardian report: verdict BLOCK, compliance score 0 of 100, nine blocking findings with rule ids and suggested fixes",
    real="Guardian rules, Azure AI Content Safety, the auto-revise loop and the audit trail run in the deployed app.",
    sim="Brand, claims, rights and talent data are fictional (Northwind Coffee Roasters); the unsafe subject is a test fixture.",
)

tour_slide(
    2, "07-creative-workspace-video.png",
    "One master becomes a signed, broadcast-spec spot and six governed versions",
    "Creative workspace, Video tab: the rendered spot, its ffprobe delivery specs and the version tree",
    [
        "A real MP4: the “AI-generated” badge is burned in, the Guardian passes it (100) and its provenance is signed",
        "ffprobe confirms the delivery spec: H.264/AAC, 1280×720 at 25 fps, 14.90 s, −16.1 LUFS",
        "Version tree: the master plus 9:16, 1:1, a 6 s cut-down and DE, FR and PL localizations",
    ],
    [(300, 212, 1114, 792, 292, 520), (1148, 208, 1562, 447, 1134, 330), (1148, 466, 1562, 844, 1134, 500)],
    "Generative video plugs in via VideoProvider; the demo uses a compositor because Sora-2 is deprecated in swedencentral.",
    ("This is what the crew delivers: a fifteen-second spot rendered by the compositor, with the AI-generated disclosure burned in, loudness normalised to minus 16 LUFS and verified with ffprobe as H.264 and AAC at 1280 by 720. "
     "The master has become six governed versions: 9:16, 1:1, a six-second cut-down, and German, French and Polish localizations, each Guardian-checked. "
     "In the live smoke test the master render took about 24 seconds on one vCPU. The provider line says generative video models plug in through VideoProvider; Sora-2 is deprecated in Sweden Central, "
     "so the demo animates AI-generated keyframes. Question to expect: is this generated video? It is real rendering of AI-generated images, voice and music."),
    "Creative workspace video tab: the rendered 14.9 second spot with an AI-generated badge, ffprobe delivery specs and a list of seven versions",
    real="ffmpeg rendering with ffprobe checks, Azure OpenAI image and speech models, and the signed provenance manifest.",
    sim="Brand and talent data are fictional; no generative video model is used (VideoProvider is the plug-in point).",
)

tour_slide(
    3, "18-performance-insights.png",
    "Insights close the loop: significant findings flow back into the Brand Brain",
    "Performance insights: connectors and CSV in, statistically tested findings out (simulated ad platforms)",
    [
        "Sync buttons for five ad platforms and a CSV upload; the connectors run against a simulator, so every number is synthetic",
        "KPI strip: impressions, CTR, VTR, CVR, CPA and ROAS, groupable by variant or platform; the daily trend sits below",
        "“What works”: findings with p-value and sample size, written back to the Brand Brain for the next brief",
    ],
    [(289, 205, 1560, 383, 275, 294), (289, 403, 1560, 483, 268, 443), (1150, 503, 1560, 868, 1134, 560)],
    "In the live smoke test the bandit beat uniform allocation by 17.1% on clicks and auto-paused 8 losers (simulated platform).",
    ("The loop closes here. Five connectors and a CSV upload feed the insights engine; in this deployment the connectors run against a deterministic simulator behind the real interface, "
     "so every number is synthetic and labelled. The engine tests findings for statistical significance and writes what works back into the Brand Brain, where the Strategist cites it in the next brief. "
     "In the live smoke test a twelve-variant experiment ran for twenty-four simulated hours: Thompson sampling beat uniform allocation by 17.1 percent on clicks and auto-paused eight losers. "
     "Real uplift must still be proven against a holdout in the pilot."),
    "Performance insights page: connector buttons, KPI strip with impressions, CTR, VTR, CVR, CPA and ROAS, and a What works panel of tested findings",
    real="Significance tests, bandit allocation and the write-back of learnings to the Brand Brain.",
    sim="Ad platforms, the audience and every performance number come from a deterministic simulator.",
)

# ======================================================================================================================
# 11. Azure reference architecture
# ======================================================================================================================
d.architecture(
    "The Azure reference architecture is keyless, governed and ready to scale out",
    [
        {"name": "Experience", "items": ["Studio UI (Container Apps)", "Teams + webhooks", "Power BI", {"title": "Front Door + WAF", "sub": "enterprise edge"}]},
        {"name": "Agent crew", "items": ["Orchestrator + stage gates", {"title": "Brand Guardian", "sub": "rules + judge"}, {"title": "Render jobs", "sub": "ffmpeg compositor"}, "Connectors"]},
        {"name": "AI models", "items": [{"title": "Foundry chat + reasoning", "sub": "GPT-5.x"}, "Image + speech + embeddings", "Azure AI Content Safety", {"title": "VideoProvider", "sub": "pluggable"}]},
        {"name": "Data", "items": ["Cosmos DB", "AI Search (scale-out)", "Blob/ADLS + CDN", "Fabric (performance)"]},
    ],
    side={"name": "Cross-cutting", "items": ["Entra ID + B2B", "Key Vault", "Monitor + Defender", "Purview + Policy"]},
    takeaway="Live today in swedencentral: one Container App, Cosmos DB, Blob and Foundry models; each part swaps to its target service.",
    source="Source: ARCHITECTURE.md §3, §5, §19; " + EVID_SRC + " §2, §9",
    notes=("The architecture is Azure-native and keyless. In the target, the studio runs on Container Apps with event-driven render jobs; models come from Microsoft Foundry with managed identity; Content Safety "
           "checks text and images; Cosmos DB holds versions, gates and audit; Blob holds assets; AI Search and Fabric are the scale-out path. A pluggable VideoProvider matters because Sora is deprecated in this region. "
           "The demo slice is deployed and verified in Sweden Central: one Container App that also renders with ffmpeg, Cosmos DB, Blob and Foundry models, with all six dependency checks green, zero secrets and no local keys. "
           "Front Door, WAF and private networking are the enterprise target, not the demo."),
)

# ======================================================================================================================
# 12. Responsible AI, security and compliance
# ======================================================================================================================
d.table(
    "Responsible AI is built in: each obligation maps to a control",
    ["Obligation or risk", "When", "How Spotlight responds"],
    [
        ["EU AI Act Art. 50: machine-readable marking of AI output", "From 2 Aug 2026; marking grace to Dec 2026 for systems already on the market", "Content Credentials on generated images + C2PA-style manifest on every asset"],
        ["EU AI Act Art. 50: label deepfakes", "From 2 Aug 2026", "Disclosure labels per market and platform, recorded in the manifest"],
        ["EU green-claims rules (Directive 2024/825)", "From 27 Sep 2026", "Claims library: generic claims need substantiation; Guardian blocks"],
        ["Platform AI-disclosure policies", "In force", "Platform label flags in the campaign pack"],
        ["Likeness, voice and music rights", "State digital-replica laws; contracts", "Consent registry with AI-use flags; no voice cloning; rights check blocks export"],
        ["Security and privacy", "Always", "Keyless identity, tenant isolation, PII redaction, EU data-zone option"],
    ],
    col_weights=[3.2, 2.6, 4.2],
    takeaway="Controls are testable features, not policies on a shelf.",
    source="Sources: European Commission Article 50 quick facts and Code of Practice (2026); EUR-Lex 32024L0825; YouTube Help; PRD §16. Not legal advice.",
    notes=("This table maps obligations to controls. Article 50 asks providers to mark synthetic output in a machine-readable way and deployers to disclose deepfakes; the Commission published a code of practice in June. "
           "Azure OpenAI attaches Content Credentials to generated images and Spotlight adds a C2PA-style manifest and disclosure labels to every final asset. The green-claims directive makes vague claims risky, so the claims library "
           "treats them as needing substantiation. Be candid: our manifest is C2PA-style, not a CA-issued credential; that is a Release 2 item. And this is not legal advice."),
)

# ======================================================================================================================
# 13. ROI: value by category and year
# ======================================================================================================================
labels = {k: v for k, v in ben["labels"].items() if sum(ben["by_category"][k]) > 0}
d.chart(
    f"Benefits reach {M(BY[3], 1)} a year by Year 3, and the case pays back in about {roi['payback_months']:.0f} months",
    ["Year 1", "Year 2", "Year 3"],
    {labels[k]: [ben["by_category"][k][t] for t in (1, 2, 3)] for k in labels},
    kind="stacked",
    number_format='$#,##0.0,,"M"',
    labels=False,
    commentary=[
        f"3-year NPV **{M(roi['npv'])}** · ROI **{P(roi['roi_pct'])}** · IRR **{P(roi['irr_pct'])}**",
        f"Year-3 benefit **{M(BY[3], 2)}** vs cost **{M(CY[3], 2)}**; payback **{roi['payback_months']:.1f} months**",
        f"Production & adaptation is **{P(ben['by_category']['production_adaptation'][3] / BY[3] * 100)}** of Year-3 benefit; ROAS uplift **{P(ben['by_category']['roas_uplift'][3] / BY[3] * 100)}**",
        f"Benefits can fall **{P(roi['breakeven_benefit_haircut_pct'])}** before NPV turns negative",
        f"Unit cost: **{D(ue['studio_all_in_cost_per_version'])}** all-in per approved version vs **{D(ue['agency_blended_cost_per_baseline_asset'])}** agency blend; an adapted video **{D(bycls['adapted_video']['studio_all_in_cost_displaced_asset'])}** vs **{D(bycls['adapted_video']['agency_cost_per_asset'])}**",
        f"Conservative: NPV **{M(C['roi']['npv'])}**, payback **{C['roi']['payback_months']:.0f} months**; Upside (incl. optional expansion packs): **{M(U['roi']['npv'])}**, **{U['roi']['payback_months']:.0f} months**",
    ],
    commentary_title="Base case",
    source=SRC_BC + ". Illustrative; every benefit line is haircut by a confidence factor. Unit economics by asset class are in the appendix.",
    notes=(f"Seven benefit categories, each haircut by a confidence factor, build to {M(BY[3], 1)} a year by Year 3. Half of it is production and adaptation cost avoided; ROAS uplift from testing is about a fifth; "
           f"speed to market, agency fees, rework, localisation and compliance make up the rest. Costs, including Azure, licences, integration, change management and human review, reach {M(CY[3], 1)} in Year 3. "
           f"Net present value is {M(roi['npv'])}, payback about fifteen months, and benefits could fall by {P(roi['breakeven_benefit_haircut_pct'])} before NPV is negative. "
           f"A Year-3 approved version costs {D(ue['studio_all_in_cost_per_version'])} all-in against an agency blend of {D(ue['agency_blended_cost_per_baseline_asset'])}, using assumed baselines. "
           "Credit is taken only for work you would otherwise buy plus measurable uplift."),
)

# ======================================================================================================================
# 14. Product tour 4/4: the live ROI and ACR calculator
# ======================================================================================================================
FC = acr["expansion"]["full_expansion_case"]
tour_slide(
    4, "22-roi-acr-calculator.png",
    "The CFO can audit the case live: the same model, three scenarios, expansion on or off",
    "ROI and ACR calculator in Base with expansion off: the live model beside the numbers in this deck",
    [
        "Scenario and scope controls, and a parity badge (top right): the live model matches the published outputs.json within ±0.5%",
        f"Base case: ROI **{P(roi['roi_pct'])}**, NPV **{M(roi['npv'])}**, payback **{roi['payback_months']:.1f} months**, IRR **{P(roi['irr_pct'])}**, Year-3 ACR **{K(ACR_Y[3])}**: the numbers in this deck",
        f"Change volume, markets, variants or media spend and everything recomputes; “Expansion on” moves Year-3 ACR to **{K(FC['run_rate_year3'])}** and NPV to **{M(FC['npv'])}**",
    ],
    [(289, 226, 1562, 348, 275, 290), (1218, 180, 1562, 204, None, None), (648, 366, 1562, 507, 636, 436), (289, 367, 622, 868, 275, 470)],
    "The calculator is the model, not a picture of it: change an assumption and NPV, payback and ACR recompute.",
    (f"The calculator is the business-case model vendored into the app, not a picture of it. With Base selected and expansion off it shows ROI {roi['roi_pct']:.0f} percent, "
     f"NPV {roi['npv'] / 1e6:.2f} million dollars, payback {roi['payback_months']:.0f} months, IRR {roi['irr_pct']:.0f} percent and Year-3 ACR {ACR_Y[3] / 1e3:.0f} thousand dollars: the numbers in this deck. "
     "The parity badge confirms the match within half a percent. Change volume, markets, variants, media spend or discount rate and everything recomputes. "
     f"Switch expansion on and Year-3 ACR rises to {FC['run_rate_year3'] / 1e3:.0f} thousand and NPV to {FC['npv'] / 1e6:.2f} million, while payback lengthens to about {FC['payback_months']:.0f} months. "
     "Question to expect: where do the baselines come from? They are assumptions until we use your purchase orders."),
    "Business case calculator: scenario, scope and expansion controls, KPI strip with ROI, NPV, payback, IRR and Azure ACR, and editable assumptions",
    real=f"The business-case model v{META['model_version']} is vendored into the app and checked against outputs.json on every run of the smoke test.",
    sim="Every assumption until it is replaced with Contoso purchase-order and media data.",
    sim_label="Illustrative",
)

# ======================================================================================================================
# 15. Adoption path
# ======================================================================================================================
ramp = B["inputs"]["adoption_ramp"]
d.timeline(
    "Adoption is earned in stages: pilot, brand, portfolio, agencies, then optional expansion packs",
    [
        {"name": "Pilot", "when": "Weeks 0-16 (12 measured)", "items": ["One brand, 3 markets, 2-3 campaigns", "Holdout-tested variants", "Baseline from purchase orders"]},
        {"name": "Brand roll-out", "when": "Months 4-9", "items": ["Full brand team, 6 markets", "Guardian, rights, approvals live", "DAM + ad-platform connectors"]},
        {"name": "Portfolio", "when": "Months 9-18", "items": ["All brands, 12 markets", "Half of volume or more in Studio", "Fabric analytics, private networking"]},
        {"name": "Agency network", "when": "Months 12-24", "items": ["Multi-tenant client workspaces", "Guest access + chargeback", "C2PA-conformant signing"]},
        {"name": "Expansion packs", "when": "Months 12-36 · optional", "items": ["Catalog content first (best ROI)", "Data + clean-room platform", "Personalization, generative video"]},
    ],
    takeaway=f"Base ramp: {ramp[0] * 100:.0f}% → {ramp[1] * 100:.0f}% → {ramp[2] * 100:.0f}% of full-adoption volume in Years 1-3; expansion packs are optional and off in Base.",
    source="Source: PRD §11, §13-14; " + SRC_BC_BARE,
    notes=("Adoption is staged so trust is earned. The pilot covers one brand, three markets and two or three campaigns for twelve to sixteen weeks, with a holdout test and baselines from purchase orders. "
           "Then the brand team goes live with Guardian, rights and approvals, followed by the portfolio across twelve markets and, for agency groups, multi-tenant workspaces. "
           "Expansion packs come last and are optional: catalog content first, then the data platform, personalization and generative video, each costed and tested separately and switched off in the Base case. "
           f"The Base case assumes {ramp[0] * 100:.0f}, {ramp[1] * 100:.0f} and {ramp[2] * 100:.0f} percent of full-adoption volume. Can we skip the pilot? We would not."),
)

# ======================================================================================================================
# 16. Risks
# ======================================================================================================================
d.table(
    "Seven risks are designed out with controls you can test",
    ["Risk", "Mitigation", "Features"],
    [
        ["IP / copyright in generated content", "Protected-material checks; no named artists or brands in prompts; licensed assets only via the registry; provenance records inputs", "CS-12, CS-03, CS-14"],
        ["Likeness, voice and deepfakes", "No cloning; consent registry with AI-use flags; prompts naming real people rejected; visible disclosure", "CS-03, CS-09, CS-14"],
        ["Brand-safety incident", "Guardian hard-fails block approval; Content Safety on prompts and outputs; human gates", "CS-12, CS-13"],
        ["Hallucinated or unsubstantiated claims", "Claim-aware generation; per-market claims library with expiry; legal gate; citations", "CS-02, CS-06, CS-12"],
        ["Model drift or model availability", "Pinned deployments; evaluation sets; provider abstraction; ffmpeg compositor instead of a video-model dependency", "CS-08, CS-24"],
        ["Regulatory change", "Rules as data; regulatory packs; counsel review; alignment with the EU Code of Practice", "CS-02, CS-14"],
        ["Benefits not proven", "Holdout test in the pilot; confidence haircuts; break-even at a 56% benefit shortfall", "CS-17, CS-23"],
    ],
    col_weights=[2.6, 5.6, 1.8],
    takeaway="Every mitigation maps to a feature with an acceptance test.",
    source="Source: PRD §15. Break-even haircut from business-case/outputs.json.",
    notes=("The risk register in one table. Copyright and protected material: Content Safety checks, no named artists or brands in prompts, licensed assets through the registry. Likeness and voice: no cloning is offered, "
           "consent is recorded with AI-use flags, and realistic synthetic people carry a disclosure. Brand safety and hallucinated claims are handled by the Guardian, the claims library and the legal gate. "
           "Model drift and availability are handled by pinned deployments, evaluation sets and the VideoProvider abstraction. Regulation changes, so rules are data. The last row is commercial: benefits are unproven until a holdout says otherwise."),
)

# ======================================================================================================================
# 17. KPIs
# ======================================================================================================================
d.kpi_cards(
    "We will hold ourselves to eight measurable KPIs from week one",
    [
        {"value": D(ue["studio_all_in_cost_per_version"]), "label": "KPI-01 Cost per approved version, Year 3 all-in", "sub": f"vs {D(ue['agency_blended_cost_per_baseline_asset'])} agency blend (assumption)"},
        {"value": "≤ 4 weeks", "label": "KPI-02 Brief to approved assets, calendar time", "sub": "Today 6-10 weeks · live run: 7 min machine time"},
        {"value": f"{B['volumes']['approved_versions_by_year'][3]:,.0f}", "label": "KPI-03 Approved versions in Year 3", "sub": "Base ramp · 5,000 today"},
        {"value": "+5%", "label": "KPI-05 ROAS uplift vs holdout at 12 variants", "sub": "Haircut 60% in the case"},
        {"value": "0", "label": "KPI-06 Critical compliance incidents reaching market", "sub": "−50% routine incidents"},
        {"value": "≥ 80%", "label": "KPI-07 First-pass Guardian pass rate by month 3", "sub": "Revision rounds ≤ 1.5"},
        {"value": "100%", "label": "KPI-10 Published assets with a verifiable manifest", "sub": "Rights breaches: 0"},
        {"value": "100%", "label": "KPI-16 Campaigns within their AI budget cap", "sub": "Caps fail closed"},
    ],
    takeaway="Baselines come from your purchase orders in week 1; targets are validated in the pilot.",
    source="Source: PRD §10 (KPI-01 … KPI-20); " + SRC_BC_BARE,
    notes=("These eight KPIs are the pilot scorecard; the full set of twenty is in the PRD. Cost per approved version is the headline; Year-3 all-in is in the low double digits of dollars against an agency blend in the thousands per asset, "
           "using assumed baselines. Cycle time targets four weeks of calendar time versus six to ten today. Uplift is the one we must prove on a holdout. Compliance and provenance are binary promises: zero critical incidents "
           "and a verifiable manifest on every published asset. Budget adherence shows the cost caps work. Baselines are captured from purchase orders and the legal incident register in week one."),
)

# ======================================================================================================================
# 18. The ask
# ======================================================================================================================
s_ask = d.big_statement(
    "The ask",
    "Approve a 12-week, one-brand pilot that turns our assumptions into Contoso's own numbers.",
    sub="Decision needed this quarter. We need a marketing sponsor, a legal and a brand reviewer, and finance access to purchase-order data in week 1.",
    notes=("The ask is small and specific: a twelve-week pilot on one brand, with two or three campaigns in three markets. We need an executive sponsor in marketing, a legal and a brand reviewer to work the gates, "
           "and finance to share purchase-order data in week one so the baselines are yours, not ours. Weeks one and two set the baseline, three and four set up, five to ten produce and test against a holdout, "
           "and eleven and twelve decide. Success is cost per approved asset, cycle time, the Guardian's block rate and uplift against the holdout. At the end you hold your own business case and a go or no-go."),
)
PILOT_PLAN = [
    ("Weeks 1-2", "Baseline", "Purchase orders, rate cards, incident register and cycle times; model re-run"),
    ("Weeks 3-4", "Set up", "Brand kit, claims, rights and roles loaded; gates and connectors configured"),
    ("Weeks 5-10", "Produce and test", "2-3 campaigns in 3 markets through the gates; holdout test on variants"),
    ("Weeks 11-12", "Decide", "Business case re-run on your data; go / no-go for the brand roll-out"),
]
cw_plan = (deckkit.CONTENT_W - 3 * 0.18) / 4
for i_p, (when_p, name_p, body_p) in enumerate(PILOT_PLAN):
    x_p = deckkit.MARGIN + i_p * (cw_plan + 0.18)
    d._rect(s_ask, x_p, 4.5, cw_plan, 1.45, d.t.card, radius=0.08)
    d.text(s_ask, x_p + 0.16, 4.56, cw_plan - 0.32, 1.35,
           [Para(when_p, bold=True, size=12, color=d.t.accent, space_after=1), Para(name_p, bold=True, size=14, space_after=3), Para(body_p, size=11.5)],
           size=11.5, min_size=9.5)
d._takeaway(s_ask, "Success = cost per approved asset, cycle time, Guardian block rate and holdout-tested uplift.")

# ======================================================================================================================
# Azure opportunity (ACR) - separate section for Microsoft & partner leadership
# ======================================================================================================================
d.section(
    "Azure opportunity",
    "For Microsoft & partner leadership - skip for customer-only audiences",
    number="02",
    notes=("This section is for Microsoft and partner leadership and can be hidden for customer-only audiences. It shows the Azure Consumed Revenue the solution implies, built bottom-up from list prices and "
           "explicit unit-consumption assumptions, by service family and year, by customer tier, with pull-through and an illustrative pipeline. Everything is pay-as-you-go list price with no enterprise discount, "
           "retrieved from the Azure Retail Prices API on 17 November 2026. None of this is a forecast or a Microsoft commitment; it is assumption-driven and must be calibrated with the live cost meter."),
)
d.set_section("Azure opportunity · ACR")

fam = acr["by_family"]


def fy(keys: list[str], t: int) -> float:
    return sum(fam[k][t] for k in keys)


groups = {
    "AI models, speech & safety": ["azure_openai_text", "azure_openai_image", "speech_language", "content_safety"],
    "AI Search + Cosmos DB": ["ai_search", "cosmos_db"],
    "Fabric analytics": ["analytics"],
    "Storage, Front Door, compute, messaging": ["storage_delivery", "compute", "messaging"],
    "Monitoring, security, gateway, network": ["monitoring_security_network"],
    "Pull-through (attach)": ["attach_dam_archive", "attach_data_platform", "attach_security_network"],
}
d.chart(
    f"Bottom-up ACR grows from {K(ACR_Y[1])} to {K(ACR_Y[3])} a year per global customer",
    ["Year 1", "Year 2", "Year 3"],
    {g: [fy(k, t) for t in (1, 2, 3)] for g, k in groups.items()},
    kind="stacked",
    number_format='$#,##0,"k"',
    labels=False,
    commentary=[
        f"Year 3: **{K(acr['direct_by_year'][3])}** direct + **{K(acr['attach_by_year'][3])}** pull-through = **{K(ACR_Y[3])}**",
        f"Text models are **{P(fam['azure_openai_text'][3] / ACR_Y[3] * 100)}** of Year-3 ACR (interactive co-creation, Guardian, localisation)",
        f"Fixed platform is about **{P(acr['fixed_platform_by_year'][3] / acr['direct_by_year'][3] * 100)}** of direct ACR; the rest scales with users and versions",
        "List price, pay-as-you-go, swedencentral; EU Data Zone +10% on models",
    ],
    commentary_title="Reading the chart",
    source=f"Source: business-case/outputs.json; Azure Retail Prices API retrieved {META['pricing_retrieved_at']}",
    notes=("This is the bottom-up ACR for one reference customer, in dollars per year. Year one is a pilot and one brand; by Year three the global footprint is in place at 85 percent adoption. "
           f"Year-three consumption is {K(ACR_Y[3])}: {K(acr['direct_by_year'][3])} direct plus {K(acr['attach_by_year'][3])} pull-through. Text models dominate because interactive co-creation and Guardian checks are token-hungry; "
           "image generation, speech and safety are small because unit prices are low. About forty percent is fixed platform: search, Cosmos, Front Door, API Management, Fabric, monitoring. "
           "Every line is units times the retail price, with the units listed in the assumptions file."),
)

d.chart(
    f"ACR per customer runs from {K(tiers['pilot']['acr_run_rate_usd'])} for a pilot to {M(tiers['enterprise_scale']['acr_run_rate_usd'], 2)} at enterprise scale",
    [t["label"].split(" (")[0] for t in acr["tiers"]],
    {"Annual ACR (US$)": [t["acr_run_rate_usd"] for t in acr["tiers"]]},
    kind="column",
    number_format='$#,##0,"k"',
    labels=True,
    commentary=[
        f"Pilot **{K(tiers['pilot']['acr_run_rate_usd'])}**, one brand **{K(tiers['one_brand']['acr_run_rate_usd'])}**, global portfolio **{K(tiers['global_portfolio']['acr_run_rate_usd'])}**, agency network **{M(tiers['agency_network']['acr_run_rate_usd'])}**, enterprise scale **{M(tiers['enterprise_scale']['acr_run_rate_usd'])}**",
        f"{tiers['global_portfolio']['versions_per_year']:,.0f} versions and {tiers['global_portfolio']['users']:,.0f} users at the global tier; {tiers['agency_network']['versions_per_year']:,.0f} at the agency tier; {tiers['enterprise_scale']['versions_per_year']:,.0f} versions, {tiers['enterprise_scale']['users']:,.0f} users and all four expansion levers at enterprise scale",
        f"Azure cost per version: {D(tiers['global_portfolio']['azure_cost_per_version_usd'], 2)} global, {D(tiers['agency_network']['azure_cost_per_version_usd'], 2)} agency (scale dilutes fixed cost)",
    ],
    commentary_title="Steady state, annual",
    source="Source: business-case/outputs.json (tier run-rates at full adoption of the tier scope; enterprise scale is an assumption-driven profile)",
    notes=("Five customer tiers. A pilot consumes about twenty thousand dollars a year, one brand about a hundred thousand, a global portfolio like Contoso about half a million, an agency network running around thirty "
           f"client brands about two million, and an enterprise-scale customer, with catalog content, personalization, generative video and a data platform on top of three times the volume, about {M(tiers['enterprise_scale']['acr_run_rate_usd'], 1)}. "
           "These are steady-state annual run-rates at each tier's scope, using the same engine and footprints. Azure cost per approved version falls as scale rises because fixed platform cost is shared. "
           "The commercial opportunity is breadth, pull-through, agency networks and expansion."),
)

pull = acr["pull_through_ratio"]
d.chart(
    f"Pull-through adds {pull * 100:.0f} cents for every direct Azure dollar: archive, data and security",
    ["Direct: AI models & safety", "Direct: search, Cosmos, analytics", "Direct: delivery, compute, messaging", "Direct: monitoring, security, network",
     "Pull-through: DAM archive", "Pull-through: data platform", "Pull-through: security & network"],
    {"Year-3 ACR (US$)": [fy(groups["AI models, speech & safety"], 3), fy(groups["AI Search + Cosmos DB"], 3) + fam["analytics"][3],
                          fy(groups["Storage, Front Door, compute, messaging"], 3), fam["monitoring_security_network"][3],
                          fam["attach_dam_archive"][3], fam["attach_data_platform"][3], fam["attach_security_network"][3]]},
    kind="doughnut",
    number_format='$#,##0,"k"',
    labels=True,
    commentary=[
        f"Year-3 pull-through **{K(acr['attach_by_year'][3])}** on **{K(acr['direct_by_year'][3])}** direct (ratio **{pull:.2f}**)",
        "DAM archive migration to Blob/ADLS (150 TB assumed at global scale)",
        "Marketing data platform: extra Fabric capacity for measurement and CDP work",
        "Security and network landing zone: Sentinel, firewall, Defender plans",
    ],
    commentary_title="What pulls through",
    source="Source: business-case/outputs.json; pull-through lines are explicit assumptions (archive TB, Fabric CU, ratio of fixed cost)",
    notes=("Beyond the direct footprint the solution pulls other Azure consumption: the customer's legacy asset archive moving into Blob and Data Lake storage, additional Fabric capacity for the marketing data platform "
           "and measurement, and the security and networking landing zone that an enterprise deployment needs. In the Base case that adds about twenty cents for every direct dollar in Year three. "
           "These lines are explicit and separately labelled assumptions, not bottom-up meters, so treat them as a range. Likely question: why is storage small? Because compositor-rendered video is cheap to store."),
)

d.table(
    "The pilot lands small and expands through five consumption stages",
    ["Stage", "Customer scope", "Azure services added", "Annual ACR"],
    [
        ["Land: pilot", f"12 weeks, one brand, {tiers['pilot']['markets']:.0f} markets", "Foundry models, Content Safety, Cosmos DB, Blob, Container Apps", K(tiers["pilot"]["acr_run_rate_usd"])],
        ["Expand: one brand", f"Brand team, {tiers['one_brand']['markets']:.0f} markets, Guardian, rights, approvals", "+ AI Search, API Management, Fabric, private endpoints", K(tiers["one_brand"]["acr_run_rate_usd"])],
        ["Scale: portfolio", f"All brands, {tiers['global_portfolio']['markets']:.0f} markets, {tiers['global_portfolio']['users']:.0f} users", "+ Front Door Premium + WAF, multi-region Cosmos DB, DR, Purview", K(tiers["global_portfolio"]["acr_run_rate_usd"])],
        ["Network: agencies", "About 30 client brands, multi-tenant", "+ tenant isolation, Premium v2 gateway, F64-class analytics", M(tiers["agency_network"]["acr_run_rate_usd"])],
        ["Extend: enterprise scale", f"{tiers['enterprise_scale']['versions_per_year']:,.0f} versions, {tiers['enterprise_scale']['markets']:.0f} markets, {tiers['enterprise_scale']['users']:,.0f} users, four expansion packs", "+ Fabric F256, AI Search S2, larger Cosmos DB and delivery, image and video generation", M(tiers["enterprise_scale"]["acr_run_rate_usd"])],
    ],
    col_weights=[2.2, 3.8, 4.4, 1.3],
    align=["left", "left", "left", "right"],
    font_pt=12.5,
    takeaway="Each stage adds services and users; the customer's value grows faster than Azure consumption.",
    source="Source: business-case/outputs.json (tier run-rates at full adoption of the tier scope); PRD §11 and §13",
    notes=("How the pilot lands and expands. The pilot runs on the demo-style slice: Foundry models, Cosmos DB and Blob, about twenty thousand dollars a year. Adding the brand team brings AI Search, an API gateway "
           "and a small Fabric capacity. The portfolio stage adds Front Door Premium, private networking and a disaster-recovery region. Agency networks add tenant isolation and chargeback. "
           f"Enterprise scale adds catalog content, personalization, generative video and a larger data platform, about {M(tiers['enterprise_scale']['acr_run_rate_usd'], 1)} a year. "
           "The partner role is implementation, integration and change management."),
)

# ----------------------------------------------------------------------------------------------------------------------
# Expansion levers E1-E4: ACR by lever, the path to enterprise scale, lever economics
# ----------------------------------------------------------------------------------------------------------------------
EX = acr["expansion"]
FC = EX["full_expansion_case"]
BL, FL = FC["by_lever"], FC["levers"]
ENT = tiers["enterprise_scale"]
ENT_LV = ENT["expansion"]["by_lever_usd"]
UE_E = EX["enterprise_unit_economics"]
LEVERS = ("e1", "e2", "e3", "e4")
LEVER_SHORT = {"core": "Campaign studio (Release 1)", "e1": "E1 Generative video", "e2": "E2 Catalog content", "e3": "E3 Personalization", "e4": "E4 Data & clean-room"}
LEVER_BENEFIT_Y3 = sum(FL[k]["benefit_year3"] for k in LEVERS)
LEVER_ACR_Y3 = sum(FL[k]["acr_year3"] for k in LEVERS)
INC = FC["incremental_vs_this_scenario"]

d.chart(
    f"Four optional levers roughly double this customer's ACR: {K(ACR_Y[3])} → {K(FC['run_rate_year3'])} a year by Year 3",
    ["Year 1", "Year 2", "Year 3"],
    {LEVER_SHORT[k]: [BL[k][t] for t in (1, 2, 3)] for k in LEVER_SHORT},
    kind="stacked",
    number_format='$#,##0,"k"',
    labels=False,
    commentary=[
        f"Base (levers off): **{K(ACR_Y[1])} → {K(ACR_Y[2])} → {K(ACR_Y[3])}**; with E1-E4 at full scale: **{K(FC['acr_by_year'][1])} → {K(FC['acr_by_year'][2])} → {K(FC['acr_by_year'][3])}**",
        "Year 3 by lever: " + ", ".join(f"E{i} **{K(BL[f'e{i}'][3])}**" for i in (4, 3, 2, 1)),
        f"The levers add **{M(LEVER_BENEFIT_Y3, 2)}** of Year-3 customer benefit and **{SM(INC['npv_usd'])}** of 3-year NPV; each has its own cost, and none is in the Base case",
        f"Honest reading: images and video are cheap per unit ({D(UE_E['catalog_image']['azure_all_in_cost_per_kept_image_usd'], 2)} per kept image, {D(UE_E['generative_video']['azure_cost_per_kept_second_usd'], 2)} per kept video second)",
    ],
    commentary_title="Base vs Base + expansion",
    source=SRC_BC + "; expansion levers E1-E4 at full scale by Year 3 (acr.expansion.full_expansion_case)",
    notes=(f"The same reference customer at the same list prices. The Base case is the Release-1 campaign studio: {K(ACR_Y[1])} rising to {K(ACR_Y[3])} in Year three. Switching on four optional expansion levers at full scale roughly doubles "
           f"Year-three ACR to about {K(FC['run_rate_year3'])}: the data platform adds {K(BL['e4'][3])}, personalization {K(BL['e3'][3])}, catalog content {K(BL['e2'][3])} and generative video {K(BL['e1'][3])}. "
           "Images and video are cheap per unit, so catalog content and video add little Azure consumption even though catalog content has the best return. Each lever carries its own cost and benefit and is off in the Base case."),
)

PATH = EX["enterprise_path"]
PATH_SHORT = {"global_portfolio": "Campaign scale", "breadth": "Enterprise breadth", "e1": "E1 Video", "e2": "E2 Catalog", "e3": "E3 Personalize", "e4": "E4 Data platform"}
wf = d.waterfall(
    f"The path to enterprise scale: {K(PATH[0]['acr_usd'])} → {M(PATH[-1]['acr_usd'], 2)} a year, mostly breadth, personalization and the data platform",
    [(PATH_SHORT[s["id"]], s["acr_usd"] / 1e6) for s in PATH[:-1]],
    number_format="0.00",
    total_label="Enterprise scale",
    commentary=[
        f"Enterprise profile (assumption-driven): **{ENT['versions_per_year']:,.0f}** versions, **{ENT['markets']:.0f}** markets, **{ENT['users']:,.0f}** users, **{ENT['expansion']['lever_params']['e2_skus']:,.0f}** SKUs, personalization at **{ENT['expansion']['lever_params']['e3_multiplier']:.0f}×**, Fabric F**{ENT['expansion']['lever_params']['e4_fabric_cu']:.0f}**",
        f"Levers **{M(sum(ENT_LV.values()), 2)}** + breadth **{M(PATH[1]['acr_usd'], 2)}**: E3 and E4 are **{P((ENT_LV['e3'] + ENT_LV['e4']) / sum(ENT_LV.values()) * 100)}** of lever ACR; E1 and E2 only **{P((ENT_LV['e1'] + ENT_LV['e2']) / sum(ENT_LV.values()) * 100)}**",
        f"Unit costs: **{D(UE_E['generative_video']['azure_cost_per_kept_second_usd'], 2)}** per kept video second · **{D(UE_E['catalog_image']['azure_variable_cost_per_kept_image_usd'], 2)}** / **{D(UE_E['catalog_image']['azure_all_in_cost_per_kept_image_usd'], 2)}** per kept image · **{D(UE_E['personalized_version']['azure_variable_cost_per_version_usd'], 2)}** / **{D(UE_E['personalized_version']['azure_all_in_cost_per_version_usd'], 2)}** per personalised version (variable / all-in)",
        f"An agency network reaches **{M(tiers['agency_network']['acr_run_rate_usd'])}** by multi-tenancy instead",
    ],
    commentary_title="Run-rate, US$M a year",
    source=SRC_BC + "; steady-state tier run-rates (acr.expansion.enterprise_path)",
    notes=(f"How an enterprise-scale customer gets from about {K(PATH[0]['acr_usd'])} to {M(PATH[-1]['acr_usd'], 1)} a year. Breadth comes first: three times the versions, twenty markets and a thousand users on a larger platform add {M(PATH[1]['acr_usd'], 2)}. "
           f"Then the four levers: the data platform {K(ENT_LV['e4'])}, personalization {K(ENT_LV['e3'])}, catalog content {K(ENT_LV['e2'])}, generative video {K(ENT_LV['e1'])}. "
           "The profile is an assumption, not a forecast. Generated media is cheap per unit; consumption comes from data, scale and breadth."),
)
# Two-decimal labels in US$M; small bars get a dark label so they stay legible outside the bar.
for shp in wf.shapes:
    if not getattr(shp, "has_chart", False) or not shp.has_chart:
        continue
    plot = shp.chart.plots[0]
    for pi, step in enumerate(PATH[:-1]):
        small = step["acr_usd"] < 0.15e6
        dl = plot.series[1].points[pi].data_label
        dl.has_text_frame = True
        dl.text_frame.text = f"{step['acr_usd'] / 1e6:.2f}"
        run = dl.text_frame.paragraphs[0].runs[0]
        run.font.size, run.font.bold = Pt(11), True
        run.font.color.rgb = RGBColor(0x1B, 0x1B, 0x3A) if small else RGBColor(0xFF, 0xFF, 0xFF)
    dl = plot.series[3].points[len(PATH) - 1].data_label
    dl.has_text_frame = True
    dl.text_frame.text = f"{PATH[-1]['acr_usd'] / 1e6:.2f}"
    run = dl.text_frame.paragraphs[0].runs[0]
    run.font.size, run.font.bold = Pt(11), True
    run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)

lever_rows = [
    ["E1 Generative video", f"Generated seconds × takes × list price (Sora 2 {D(PRICES['video_sora2_sec']['price'], 2)}, Pro high-res {D(PRICES['video_sora2_pro_hires_sec']['price'], 2)} per second); {D(UE_E['generative_video']['azure_cost_per_kept_second_usd'], 2)} per kept second",
     K(FL["e1"]["acr_year3"]), K(ENT_LV["e1"]), MK(FL["e1"]["benefit_year3"]), SM(FL["e1"]["npv"])],
    ["E2 Catalog content", f"SKUs × markets × images × refresh × attempts; {D(UE_E['catalog_image']['azure_all_in_cost_per_kept_image_usd'], 2)} per kept image vs {D(UE_E['catalog_image']['avoided_baseline_cost_per_image_usd'], 2)} avoided cost",
     K(FL["e2"]["acr_year3"]), K(ENT_LV["e2"]), MK(FL["e2"]["benefit_year3"]), SM(FL["e2"]["npv"])],
    ["E3 Personalization", f"Segment variants ({AS['e3_multiplier']['base']:.0f}× here, {ENT['expansion']['lever_params']['e3_multiplier']:.0f}× at enterprise scale) on the variant engine, Cosmos DB, AI Search, Fabric; {D(UE_E['personalized_version']['azure_all_in_cost_per_version_usd'], 2)} per version",
     K(FL["e3"]["acr_year3"]), K(ENT_LV["e3"]), MK(FL["e3"]["benefit_year3"]), SM(FL["e3"]["npv"])],
    ["E4 Data & clean-room", f"Fabric F{AS['e4_fabric_cu']['base']:.0f} → F{ENT['expansion']['lever_params']['e4_fabric_cu']:.0f}, OneLake {AS['e4_onelake_tb']['base']:.0f} → {ENT['expansion']['lever_params']['e4_onelake_tb']:.0f} TB, Purview, logs",
     K(FL["e4"]["acr_year3"]), K(ENT_LV["e4"]), MK(FL["e4"]["benefit_year3"]), SM(FL["e4"]["npv"])],
    ["All four levers", "Each carries its own integration, run and review cost", K(LEVER_ACR_Y3), MK(sum(ENT_LV.values())), MK(LEVER_BENEFIT_Y3), SM(INC["npv_usd"])],
]
d.table(
    "Catalog content pays back fastest; the data platform and personalization carry the consumption",
    ["Lever", "What drives the Azure bill", "ACR Y3, this customer", "ACR, enterprise scale", "Benefit Y3, this customer", "3-year NPV"],
    lever_rows,
    col_weights=[2.0, 5.2, 1.3, 1.4, 1.4, 1.2],
    align=["left", "left", "right", "right", "right", "right"],
    highlight_rows=[4],
    font_pt=12,
    takeaway="Sell expansion packs in order of proven return, each with its own holdout test and cap; none is in the Base case.",
    source=SRC_BC + "; lever NPV at Base drivers (Upside drivers: " + ", ".join(f"{k.upper()} {SM(U['acr']['expansion']['levers'][k]['npv'])}" for k in ("e1", "e3", "e4"))
           + "); generative-video availability varies by region (sora-2 deprecated in swedencentral)",
    notes=("Lever economics at this customer's scale and at enterprise scale. Catalog content has the best return: about "
           f"{D(UE_E['catalog_image']['azure_all_in_cost_per_kept_image_usd'], 2)} per kept image against {D(UE_E['catalog_image']['avoided_baseline_cost_per_image_usd'], 2)} of avoided photography cost, but a small Azure bill. Generative video is a small Azure line, "
           f"about {D(UE_E['generative_video']['azure_cost_per_kept_second_usd'], 2)} per kept second, because you pay per generated second including rejected takes, and availability varies by region. "
           "Personalization and the Fabric data platform carry the consumption and are roughly break-even within three years at this volume. They are options, sold in order of proven return."),
)

pf = acr["portfolio"]
d.chart(
    f"An illustrative partner pipeline reaches {M(pf['total_by_year'][3], 1)} ACR in Year 3",
    ["Year 1", "Year 2", "Year 3"],
    {ASSUME["tiers"][t]["label"].split(" (")[0]: [pf["acr_by_tier_by_year"][t][y] for y in (1, 2, 3)] for t in ("pilot", "one_brand", "global_portfolio", "agency_network")},
    kind="stacked",
    number_format='$#,##0.0,,"M"',
    labels=False,
    commentary=[
        "New customers Y1/Y2/Y3: pilots " + "/".join(f"{x:g}" for x in pf["new_customers_by_tier"]["pilot"]) + ", one brand " + "/".join(f"{x:g}" for x in pf["new_customers_by_tier"]["one_brand"])
        + ", global " + "/".join(f"{x:g}" for x in pf["new_customers_by_tier"]["global_portfolio"]) + ", agency " + "/".join(f"{x:g}" for x in pf["new_customers_by_tier"]["agency_network"]),
        f"ACR **{M(pf['total_by_year'][1])} → {M(pf['total_by_year'][2])} → {M(pf['total_by_year'][3])}**; cumulative **{M(pf['cumulative_3yr'], 1)}**",
        f"Conservative Year 3 **{M(C['acr']['portfolio']['total_by_year'][3], 1)}**; Upside **{M(U['acr']['portfolio']['total_by_year'][3], 1)}** (adds 1 + 2 enterprise-scale accounts)",
        f"Directional ceiling: {acr['tam']['target_accounts']:,.0f} target accounts + {acr['tam']['agency_networks']:,.0f} agency networks ≈ **{M(acr['tam']['annual_acr_ceiling_usd'], 0)}** a year (**{M(acr['tam']['expansion']['annual_acr_ceiling_with_expansion_usd'], 0)}** with expansion); **{M(acr['tam']['annual_acr_at_penetration_usd'], 0)}** at {acr['tam']['penetration'] * 100:.0f}% penetration",
    ],
    commentary_title="Illustrative, not a forecast",
    source="Source: business-case/outputs.json. Customer counts and account numbers are unsourced assumptions - replace with Microsoft account data.",
    notes=("This is an illustration, not a forecast. A partner-led motion starts eight pilots in year one, sixteen in year two and twenty-four in year three, converts a share to one-brand and global-portfolio deals, "
           f"and adds a couple of agency networks. That yields about {M(pf['total_by_year'][3], 1)} of ACR in Year three; the Upside also adds enterprise-scale accounts. Account counts are directional assumptions: roughly fifteen hundred target accounts plus forty agency networks "
           f"give a ceiling of about {M(acr['tam']['annual_acr_ceiling_usd'], 0)} a year at full penetration. Please replace them with real account data. The three-year pipeline is only about one to two percent of the ceiling."),
)

d.kpi_cards(
    "Customers can afford it: every Azure dollar supports about US$19 of benefit",
    [
        {"value": f"{benefit_per_azure:.0f}×", "label": "Customer benefit per Azure dollar (3-year)", "sub": f"{M(ben['total'], 1)} benefit ÷ {M(sum(ACR_Y), 2)} ACR"},
        {"value": P(roi["azure_share_of_benefit_pct"], 1), "label": "Azure as a share of customer benefit", "sub": "Base, 3 years"},
        {"value": P(roi["azure_share_of_cost_pct"], 1), "label": "Azure as a share of customer cost", "sub": "Licences, integration, change and review dominate"},
        {"value": D(ue["azure_direct_cost_per_version"], 2), "label": "Azure cost per approved version, Year 3", "sub": f"Variable only {D(ue['azure_variable_cost_per_version'], 2)}"},
    ],
    takeaway="Consumption follows adoption: the lever is breadth, pull-through, expansion packs and agency networks, not per-asset intensity.",
    source=SRC_BC + ". Provisioned Throughput is excluded from every scenario; generative video appears only in optional lever E1.",
    notes=("Why customers can afford it, and what it means for Microsoft. Over three years the customer gets about nineteen dollars of benefit for every Azure dollar consumed; Azure is roughly five percent of the benefit and "
           "about thirteen percent of total cost, where licences, integration, change management and human review dominate. The Azure cost per approved version is single-digit dollars. The implication is that ACR is driven by adoption, "
           "breadth and expansion, not by pushing tokens. Provisioned throughput is excluded; generative video is an optional lever priced per generated second, shown on the expansion slides."),
)
d.set_section(None)

# ======================================================================================================================
# Appendix
# ======================================================================================================================
d.section(
    "Appendix",
    "Evidence, assumptions, sensitivity, unit economics, pricing basis, features, product screens, glossary and sources",
    number="03",
    notes=("The appendix holds the backup material: the verification evidence for the live deployment, the assumptions we most need to validate, the sensitivity analysis, cumulative cash flow by scenario, "
           "the bridge from benefits to net benefit, unit economics by asset class, the closed-loop diagram, the pricing basis, the full feature list, the crew in detail, the remaining product screens, "
           "a glossary and the sources. Business-case numbers come from the model outputs; measured evidence comes from the engineering verification report."),
)
d.set_section("Appendix")

d.table(
    "Release 1 is built, tested and live: the evidence",
    ["Check", "Result on the live deployment", "Where to verify"],
    [
        ["Features deployed", "24 of 24 report IMPLEMENTED on /api/features; every row of the FEATURES.md status board is Deployed", "REPORT §1"],
        ["Tests and static analysis", "97 passed in about 45 s · 88% line coverage (domain modules 88-100%) · ruff, mypy, tsc, build, pip-audit and npm audit clean", "REPORT §3"],
        ["Browser journeys", "18 of 18 Playwright journeys pass on the live app; the product screens in this deck come from them", "REPORT §4"],
        ["Live smoke test", "30 of 30 checks with real Azure OpenAI, Content Safety, Speech, Cosmos DB and Blob; the whole run, brief to localized pack included, takes about 7 minutes; about $0.17 of AI spend per full run", "REPORT §5, §8"],
        ["Latency under light load", "p50 554 ms · p95 1,414 ms · p99 2,000 ms, 0 errors (400 requests, concurrency 20, one 1-vCPU replica)", "REPORT §6"],
        ["Cost to run", "About $30 a month idle, about $5 with scale-to-zero (15 s cold start); the $5 daily AI cap fails closed", "REPORT §8"],
        ["Security posture", "Keyless: managed identity, 0 secrets, shared-key and local auth off; governance tags on the resource group and all 14 resources", "REPORT §2, §9"],
        ["Business-case parity", f"The calculator reproduces outputs.json within ±0.5% (model v{META['model_version']}): Base NPV {M(roi['npv'])}, Year-3 ACR {K(ACR_Y[3])}", "REPORT §5 (check 27)"],
    ],
    col_weights=[2.2, 6.9, 1.7],
    align=["left", "left", "left"],
    font_pt=12,
    takeaway="Not in the demo slice: WAF, private networking, a CI pipeline, generative video and certified C2PA signing; expansion levers E1-E4 are modelled, not built.",
    source="Source: " + EVID_SRC + " and app/evidence/. Measured facts about the demo deployment, not business-case numbers.",
    notes=("This is the evidence behind the demo, taken from the engineering verification report. All twenty-four features are deployed; ninety-seven tests pass at 88 percent coverage; eighteen browser journeys "
           "and a thirty-check smoke test pass against the live deployment using real Azure models; a light load test of four hundred requests shows a p95 of 1.4 seconds with no errors on one vCPU. "
           "Idle run cost is about thirty dollars a month. Be candid about the limits on the takeaway line: no WAF, private networking or CI pipeline, no generative video because Sora-2 is deprecated in this region, "
           "provenance is C2PA-style rather than certified, and the expansion levers are modelled, not built."),
)


SHORT_LABELS = {
    "baseline_cost_adapted_video": "Agency + production cost per adapted video asset",
    "baseline_cost_hero_spot": "Agency + production cost per 30 s hero spot",
    "addressable_adapted_video": "Share of adapted-video cost Studio can displace",
    "adoption_y3": "Adoption in Year 3 (share of full-adoption volume)",
    "roas_uplift_pct": "ROAS uplift at 12 variants and full coverage",
    "media_scope_pct_paid": "Share of paid media in scope of testing",
    "confidence_roas": "Confidence factor applied to ROAS uplift",
    "platform_licence_usd_per_year": "Platform licence and support at full scale, per year",
    "implementation_usd": "One-time implementation and integration",
}


def fmt_assumption(key: str) -> list[str]:
    a = AS[key]
    unit = a["unit"]

    def f(v: float) -> str:
        if "fraction" in unit:
            return f"{v * 100:g}%"
        if unit.startswith("USD"):
            return f"${v:,.0f}"
        return f"{v:g}"

    return [SHORT_LABELS.get(key, a["label"]), f(a["base"]), f"{f(a['low'])} - {f(a['high'])}", a["flag"].capitalize()]


d.table(
    "Assumptions to validate first with Contoso data",
    ["Assumption", "Base", "Range", "Basis"],
    [fmt_assumption(k) for k in ("baseline_cost_adapted_video", "baseline_cost_hero_spot", "addressable_adapted_video", "adoption_y3", "roas_uplift_pct", "media_scope_pct_paid",
                                 "confidence_roas", "platform_licence_usd_per_year", "implementation_usd")],
    col_weights=[5.6, 1.3, 2.2, 1.3],
    align=["left", "right", "right", "left"],
    takeaway="Replace each with purchase-order, legal-register and media data in week 1 of the pilot.",
    source=f"Source: business-case/assumptions.json ({len(AS)} assumptions, each with rationale and source)",
    notes=("These are the assumptions that matter most. Agency and production cost per adapted asset and per hero spot, the share of that cost Studio can displace, the Year-three adoption level, the ROAS uplift "
           "at twelve variants, the share of paid media in scope, the confidence haircut on uplift, and the licence and implementation costs. All are flagged as assumptions with a range. "
           f"In the pilot's first week we replace them with purchase orders, agency rate cards, the legal incident register and media data, and re-run the model. The full register of {len(AS)} assumptions is in the business-case folder."),
)

d.tornado(
    "What moves the 3-year NPV: baseline cost, adoption and confidence",
    [(x["label"], x["npv_low"] / 1e6, x["npv_high"] / 1e6) for x in B["sensitivity"][:10]],
    base_value=roi["npv"] / 1e6,
    metric_label="NPV (US$M)",
    number_format="0.0",
    takeaway="Azure unit prices and consumption barely move the answer; Contoso's own cost and adoption do.",
    source=SRC_BC + " (each driver flexed one at a time over its full low/high range)",
    notes=("The tornado flexes one driver at a time across its full low-to-high range and shows the NPV. Agency and production cost per asset swings the answer most, then adoption, then the confidence haircuts, "
           "speed-to-market value, the displaceable share and ROAS uplift. Azure consumption and price are at the bottom: even doubling consumption changes NPV by a few hundred thousand dollars. "
           "So the pilot should spend its effort measuring baselines and adoption, not negotiating unit prices. Note that the scenarios move only the key drivers half-way to their bounds, which is why Conservative is still positive."),
)

cum = lambda r: [x / 1e6 for x in r["roi"]["cumulative"]]  # noqa: E731
d.chart(
    "Cumulative net benefit crosses zero in about 15 months in the Base case",
    ["Year 0", "Year 1", "Year 2", "Year 3"],
    {"Conservative": cum(C), "Base": cum(B), "Upside": cum(U)},
    kind="line",
    number_format='$#,##0.0"M"',
    labels=False,
    commentary=[
        f"Payback: Conservative **{C['roi']['payback_months']:.0f}** months, Base **{roi['payback_months']:.0f}**, Upside (with expansion packs) **{U['roi']['payback_months']:.0f}**",
        f"Year-3 cumulative net benefit: **{M(C['roi']['cumulative'][3], 1)}** / **{M(roi['cumulative'][3], 1)}** / **{M(U['roi']['cumulative'][3], 1)}**",
        f"Year-0 outlay **{M(-B['roi']['net_benefit_by_year'][0], 1)}** (implementation + change)",
        f"Upside without the expansion packs: NPV **{M(U['acr']['expansion']['levers_off_case']['npv'], 2)}**, payback **{U['acr']['expansion']['levers_off_case']['payback_months']:.0f}** months; the packs add NPV but dilute payback",
    ],
    commentary_title="Conservative / Base / Upside",
    source=SRC_BC,
    notes=("Cumulative net benefit by scenario, in millions of dollars, with Year 0 being implementation spend. The Base case turns positive in about fifteen months; Conservative takes about twenty-eight months but still finishes "
           f"above zero within the three-year horizon; Upside pays back in about {U['roi']['payback_months']:.0f} months. Scenarios move only the key value drivers half-way from Base to their bounds, and Upside also switches on the four optional expansion packs: "
           "they add net present value and ACR but dilute payback because their integration costs come first. Moving every assumption to its extreme at once would be a stress test, not a scenario."),
)

WF_LABELS = {"production_adaptation": "Production", "roas_uplift": "ROAS uplift", "speed_to_market": "Speed", "agency_fees": "Agency fees",
             "rework_media_waste": "Rework + waste", "localization": "Localization", "compliance": "Compliance"}
steps = [(WF_LABELS[k], sum(ben["by_category"][k]) / 1e6) for k in WF_LABELS]
oc = cost["other_by_category"]
steps += [
    ("Azure run", -sum(cost["azure_total_by_year"]) / 1e6),
    ("Licence", -sum(oc["platform_licence"]) / 1e6),
    ("Implement + integrate", -(sum(oc["implementation"]) + sum(oc["integration_run"])) / 1e6),
    ("Change mgmt", -sum(oc["change_management"]) / 1e6),
    ("Review", -(sum(oc["review_creative_legal"]) + sum(oc["review_linguist"]) + sum(oc["review_exceptions"])) / 1e6),
    ("Music / stock", -sum(oc["rights_library"]) / 1e6),
]
NET3 = ben["total"] - cost["total"]
d.waterfall(
    f"From {M(ben['total'], 1)} of benefit to {M(NET3, 1)} of net benefit over three years",
    steps,
    number_format='0.0',
    total_label="Net",
    commentary=[f"Benefit {M(ben['total'], 1)} · cost {M(cost['total'], 1)} · net {M(NET3, 1)} (US$M, undiscounted)",
                f"Azure run cost is {P(roi['azure_share_of_cost_pct'], 1)} of total cost"],
    commentary_title="Bridge",
    source=SRC_BC,
    notes=(f"The bridge from gross benefit to net benefit over three years, undiscounted, in millions of dollars. Seven benefit categories add up to {M(ben['total'], 1)}. Costs subtract: the Azure run cost, "
           "which equals the ACR in the same scenario, the platform licence, implementation and integration, change management and training, human review time, and the licensed music and stock library. "
           f"The net is {M(NET3, 1)}. We charge the Studio for the full volume and give no credit for avoided internal review hours, which keeps the case conservative."),
)

rows = []
for c in ("adapted_video", "static_social", "copy_crm", "hero_spot"):
    r = bycls[c]
    rows.append([r["label"].split(" (")[0], D(r["agency_cost_per_asset"]), D(r["studio_all_in_cost_displaced_asset"]), f"{r['saving_pct']:.0f}%",
                 D(r["incremental_version_marginal_cost"], 2)])
rows.append(["Blended, Year 3 (all versions)", f"{D(ue['agency_blended_cost_per_baseline_asset'])} per asset", f"{D(ue['studio_all_in_cost_per_version'])} per version", "n/a",
             f"Azure {D(ue['azure_direct_cost_per_version'], 2)}"])
d.table(
    f"An adapted video costs about {D(bycls['adapted_video']['studio_all_in_cost_displaced_asset'])} all-in instead of {D(bycls['adapted_video']['agency_cost_per_asset'])}",
    ["Asset class", "Agency cost per asset today", "Studio all-in (displaced asset)", "Saving", "Extra version, marginal"],
    rows,
    col_weights=[3.2, 2.4, 2.6, 1.2, 2.0],
    align=["left", "right", "right", "right", "right"],
    highlight_rows=[0, 4],
    font_pt=13,
    takeaway=(f"Validate baseline cost and adoption first: NPV swings {M(sens['agency_cost']['npv_low'], 1)}-{M(sens['agency_cost']['npv_high'], 1)} and "
              f"{M(sens['adoption']['npv_low'], 1)}-{M(sens['adoption']['npv_high'], 1)} across their ranges; Azure prices barely matter."),
    source=SRC_BC + ". Agency costs are assumptions. Measured AI-only cost per approved asset in the demo campaign: $0.042 (" + EVID_SRC + " §5, check 28).",
    notes=("This is the unit economics a sceptical CFO should audit. For each asset class: the agency cost per asset today, which is an assumption we replace with your purchase orders; what the same asset costs "
           "in the Studio including the residual external spend and human review; and the marginal cost of one more version. Hero spots save much less because live-action shoots stay with agencies. "
           f"Blended, a Year-3 approved version costs {D(ue['studio_all_in_cost_per_version'])} all-in, of which Azure is {D(ue['azure_direct_cost_per_version'], 2)}. The two assumptions that move NPV most are baseline cost per asset and adoption."),
)

d.diagram(
    "Closed loop: more variants only pay if allocation learns and stops waste",
    [
        {"id": "v", "x": 0.0, "y": 0.5, "w": 2.3, "h": 1.1, "title": "Variant matrix", "sub": "hook × CTA × visual", "kind": "accent"},
        {"id": "p", "x": 3.3, "y": 0.5, "w": 2.3, "h": 1.1, "title": "Pre-flight scorecard", "sub": "predicted, simulated"},
        {"id": "b", "x": 6.6, "y": 0.5, "w": 2.3, "h": 1.1, "title": "Bandit allocation", "sub": "Thompson sampling"},
        {"id": "f", "x": 9.8, "y": 0.5, "w": 2.3, "h": 1.1, "title": "Performance data", "sub": "CSV or connector"},
        {"id": "i", "x": 9.8, "y": 3.0, "w": 2.3, "h": 1.1, "title": "Insights", "sub": "what works, why"},
        {"id": "k", "x": 6.6, "y": 3.0, "w": 2.3, "h": 1.1, "title": "Brand Brain", "sub": "learnings written back", "kind": "dark"},
        {"id": "n", "x": 3.3, "y": 3.0, "w": 2.3, "h": 1.1, "title": "Next brief", "sub": "strategy cites learnings"},
    ],
    [
        {"from": "v", "to": "p", "label": "rank"},
        {"from": "p", "to": "b", "label": "launch"},
        {"from": "b", "to": "f", "label": "spend"},
        {"from": "f", "to": "i"},
        {"from": "i", "to": "k", "label": "write back"},
        {"from": "k", "to": "n", "label": "retrieve"},
        {"from": "n", "to": "v", "label": "new variants", "dashed": True},
    ],
    takeaway="Insights flow back into the Brand Brain, so every campaign starts smarter. Performance data here is simulated until connected.",
    source="Source: FEATURES.md (CS-16, CS-17, CS-18); PRD §5.4; " + EVID_SRC + " §5 (checks 20-22)",
    notes=("The closed loop is what turns cheap variants into return. The pre-flight scorecard, which is labelled predicted and simulated, ranks twelve variants; the bandit allocates budget and pauses "
           "significant losers; performance data comes in by CSV or a connector; the insight generator writes what works back into the Brand Brain, where the Strategist cites it in the next brief. "
           "In the live smoke test the bandit beat uniform allocation by 17.1 percent on clicks and auto-paused eight losers, against a simulated ad platform. "
           "The business case treats uplift as a hypothesis to be proven on a holdout."),
)

key = [("gpt54mini_in", "gpt-5.4-mini input"), ("gpt54mini_out", "gpt-5.4-mini output"), ("gpt54_in", "gpt-5.4 input"), ("gpt54_out", "gpt-5.4 output"),
       ("image15_img_out", "gpt-image-1.5 image output"), ("tts_hd", "tts-hd voice"), ("cs_text", "Content Safety text records"), ("search_s1_hour", "AI Search S1"),
       ("afd_premium_base_month", "Front Door Premium base fee"), ("fabric_cu_hour", "Fabric capacity")]
def price(v: float) -> str:
    if v >= 100:
        return f"${v:,.0f}"
    s = f"{v:,.4f}".rstrip("0")
    head, _, tail = s.partition(".")
    return f"${head}.{tail.ljust(2, '0')}"


d.table(
    "Pricing basis: Azure Retail Prices API list prices, retrieved 17 Nov 2026",
    ["Meter", "List price", "Unit"],
    [[lbl, price(PRICES[k]["price"]), PRICES[k]["unit"].replace("USD ", "")] for k, lbl in key],
    col_weights=[4.2, 1.6, 3.6],
    align=["left", "right", "left"],
    takeaway="Pay-as-you-go, USD, swedencentral, no EA discount; Data Zone adds 10% on models.",
    source=f"Source: https://prices.azure.com/api/retail/prices ({len(PRICES)} meters; python business-case/refresh_prices.py verifies them)",
    notes=("The pricing basis. Prices come straight from the Azure Retail Prices API, pay-as-you-go in US dollars for Sweden Central, with global meters for Front Door, Translator and Private Link. "
           "There is no enterprise agreement discount, no reservation and no savings plan, so customers with commitments would pay less. Models are priced at Global Standard; EU Data Zone is ten percent higher "
           f"and is used in the Base case. A script in the business-case folder re-queries all {len(PRICES)} meters and reports any change. Video meters used only by the optional generative-video lever are on the next slide."),
)

lp = AS
d.table(
    "Expansion levers: assumptions and price basis to validate before any pack is sold",
    ["Lever", "Key assumptions (Base)", "Price basis (list, swedencentral)", "Validate with"],
    [
        ["E1 Generative video",
         f"{lp['e1_hero_gen_share']['base'] * 100:.0f}% of hero masters ({lp['e1_hero_gen_seconds']['base']:.0f} s kept) and {lp['e1_adapted_gen_share']['base'] * 100:.0f}% of adapted videos ({lp['e1_adapted_gen_seconds']['base']:.0f} s); {lp['e1_hero_takes']['base']:.0f} / {lp['e1_adapted_takes']['base']:.0f} takes per kept second; {lp['e1_displaced_share_hero']['base'] * 100:.0f}% / {lp['e1_displaced_share_adapted']['base'] * 100:.0f}% of residual cost displaced",
         f"Sora 2 {D(PRICES['video_sora2_sec']['price'], 2)} and Pro high-res {D(PRICES['video_sora2_pro_hires_sec']['price'], 2)} per second; partner models {D(PRICES['video_fal_mm_h3_turbo_1080_sec']['price'], 2)}-{D(PRICES['video_fal_ltx25_pro_1080_sec']['price'], 2)} at 1080p. Availability varies by region (sora-2 deprecated in swedencentral)",
         "Agency 3D / VFX / stock quotes; model availability and ACR eligibility"],
        ["E2 Catalog content",
         f"{lp['e2_skus']['base']:,.0f} SKUs × {lp['markets']['base']:.0f} markets × {lp['e2_market_presence']['base'] * 100:.0f}% presence × {lp['e2_images_per_listing']['base']:.0f} images × {lp['e2_refresh_share']['base'] * 100:.0f}% refresh; {lp['e2_attempt_factor']['base']:.1f} attempts; {D(lp['e2_baseline_cost_per_image_usd']['base'])} per image today, {lp['e2_displaced_share']['base'] * 100:.0f}% displaced",
         f"gpt-image-1.5 {D(PRICES['image15_img_out']['price'])} per 1M output tokens; Content Safety images {D(PRICES['cs_image']['price'], 2)} per 1K",
         "PIM extract; photography and retouching rate cards; retailer image specs"],
        ["E3 Personalization",
         f"{lp['e3_multiplier']['base']:.0f} segment variants per approved version; {lp['e3_consumption_factor']['base'] * 100:.0f}% of core consumption per version; +{lp['e3_roas_uplift_pct']['base'] * 100:.0f}% ROAS on in-scope media at {lp['confidence_e3']['base'] * 100:.0f}% confidence",
         "Same meters as the core, plus Cosmos DB RU/s, AI Search units and Fabric capacity",
         "Holdout test per audience segment; consent and audience data"],
        ["E4 Data & clean-room",
         f"Fabric F{lp['e4_fabric_cu']['base']:.0f}, {lp['e4_onelake_tb']['base']:.0f} TB OneLake; +{lp['e4_scope_increase_pct']['base'] * 100:.0f} points of paid media measured; {D(lp['e4_integration_usd']['base'])} integration, {D(lp['e4_ops_usd_per_year']['base'])} a year operations",
         f"Fabric {D(PRICES['fabric_cu_hour']['price'], 2)} per CU-hour; OneLake {D(PRICES['onelake_gb_month']['price'], 3)} per GB-month",
         "CRM / CDP scope; paid-media base; data-team capacity"],
    ],
    col_weights=[1.8, 4.6, 3.4, 2.4],
    align=["left", "left", "left", "left"],
    font_pt=11.5,
    takeaway="Every lever assumption is flagged and ranged; none is a commitment of Microsoft or a partner.",
    source=f"Source: business-case/assumptions.json (group 'expansion', {sum(1 for a in AS.values() if a.get('group') == 'expansion')} assumptions); Azure Retail Prices API; Microsoft Learn (Sora 2 preview, per-second billing)",
    notes=("The assumptions and price basis behind the four expansion levers, to be validated before any pack is sold. Video is billed per generated second, including rejected takes, at list prices from the Retail Prices API; "
           "Sora 2 is a preview model and is deprecated in Sweden Central, so provider and region are chosen per deployment, and partner-model eligibility for consumption credit needs confirming with Microsoft. "
           "Catalog content depends on your SKU count and what you pay per image today. Personalization needs a holdout test per audience. The data platform depends on CRM scope and the media base."),
)

FEATURES = [
    ("CS-01", "Brand Kit & Brand Brain", "P0", "Versioned brand knowledge with citations"),
    ("CS-02", "Claims & Compliance Library", "P0", "Approved and prohibited claims per market"),
    ("CS-03", "Rights & Consent Registry", "P0", "Talent, music, stock: territories, windows, AI consent"),
    ("CS-04", "Brief intake & Briefing agent", "P0", "Completeness score, three clarifying questions"),
    ("CS-05", "Strategy agent", "P0", "Three to five grounded territories"),
    ("CS-06", "Script & Copy agent", "P0", "6/15/30/60 s scripts, claim-aware copy"),
    ("CS-07", "Storyboard & Art Direction agent", "P0", "Consistent frames from a style bible"),
    ("CS-08", "Spot compositor / Video", "P0", "ffmpeg renders behind a VideoProvider"),
    ("CS-09", "Voice & audio agent", "P0", "Voice-over, captions, rights-cleared music"),
    ("CS-10", "Localization agent", "P1", "Transcreation into 8+ languages"),
    ("CS-11", "Format factory & versioning", "P0", "Four aspect ratios, cut-downs, version tree"),
    ("CS-12", "Brand Guardian", "P0", "Multi-check, auto-revise, blocks approval"),
    ("CS-13", "Approval workflow & audit trail", "P0", "Stage gates, roles, hash-chained audit"),
    ("CS-14", "AI disclosure & provenance", "P0", "C2PA-style manifest, labels, evidence pack"),
    ("CS-15", "Budget & cost guardrails", "P0", "Metering, caps, cost per approved asset"),
    ("CS-16", "Pre-flight creative scorecard", "P1", "Predicted scores for variants (simulated)"),
    ("CS-17", "Variant engine & experimentation", "P0", "Thompson sampling, significance, auto-pause"),
    ("CS-18", "Performance ingestion & insights", "P0", "CSV/connector data, insights to the Brand Brain"),
    ("CS-19", "Campaign planner & media-mix hints", "P2", "Illustrative channel split with ranges"),
    ("CS-20", "Studio UI", "P0", "Workspace, approvals; accessible, responsive"),
    ("CS-21", "Asset library / DAM", "P1", "Semantic search, versions, collections"),
    ("CS-22", "Collaboration, roles & integrations", "P1", "Roles, webhooks, campaign pack, REST API"),
    ("CS-23", "ROI & ACR calculator", "P0", "Live ROI and Azure ACR from the shared model"),
    ("CS-24", "Observability, security & IaC", "P0", "OpenTelemetry, keyless, Bicep/azd, smoke tests"),
]
for i in range(0, len(FEATURES), 8):
    chunk = FEATURES[i:i + 8]
    d.table(
        f"Full feature list ({i // 8 + 1} of 3): {chunk[0][0]} to {chunk[-1][0]}",
        ["ID", "Feature", "Priority", "What it does"],
        [list(x) for x in chunk],
        col_weights=[0.9, 3.6, 0.9, 4.6],
        align=["left", "left", "left", "left"],
        takeaway="All 24 are deployed; acceptance criteria, Azure services and KPIs for each feature are in FEATURES.md.",
        source="Source: FEATURES.md (status board: all Deployed); " + EVID_SRC,
        notes=("The complete Release 1 feature list, eight rows per page. Each feature has a priority: P0 is the minimum for the product to be credible, P1 is needed for a customer deployment, P2 may ship as illustrative. "
               "For each one the features document gives the problem it solves, testable acceptance criteria, the target and deployed Azure services, what is simulated, dependencies and the KPIs it moves. "
               "All twenty-four show Deployed on the status board, with evidence from the verification report: tests, the live smoke checks and the screens in this deck."),
    )

d.hub_spoke(
    "The crew in detail: nine specialists around one orchestrator",
    {"title": "Pipeline orchestrator", "sub": "5 stage gates · audit chain"},
    [
        {"title": "Briefing", "sub": "completeness + questions"},
        {"title": "Strategist", "sub": "territories + risk notes"},
        {"title": "Copywriter", "sub": "scripts + channel copy"},
        {"title": "Art Director", "sub": "storyboard + style bible"},
        {"title": "Director / Editor", "sub": "timeline + render"},
        {"title": "Sound Designer", "sub": "VO + music + loudness"},
        {"title": "Localizer", "sub": "transcreation, 8 languages"},
        {"title": "Brand Guardian", "sub": "checks every stage"},
        {"title": "Media Analyst", "sub": "variants + insights"},
    ],
    takeaway="Each agent has an allow-list of tools; the orchestrator owns transitions, gates and metering.",
    source="Source: ARCHITECTURE.md §4",
    notes=("The crew in detail. The orchestrator owns state, gates, retries and metering. Each specialist has a narrow job and an allow-list of tools: the Briefing agent can retrieve and check claims coverage; "
           "the Art Director can call the image model within the style bible; the Director calls the VideoProvider; the Guardian can call claims, rights and Content Safety. Agents never decide stage transitions and never "
           "execute instructions found in retrieved documents. That deterministic spine with generative edges is what makes cost and compliance predictable."),
)

# ----------------------------------------------------------------------------------------------------------------------
# Product screens: the screenshots that are not in the main tour, two per slide, captions written from what is on screen
# ----------------------------------------------------------------------------------------------------------------------
GAL_SRC = "Screenshots: live reference implementation on Azure (swedencentral), synthetic data, fictional brand Northwind Coffee Roasters. Evidence: " + EVID_SRC
GALLERIES = [
    ("Leaders see status and unit cost at a glance; the Briefing agent asks at most three questions",
     [("01-dashboard.png",
       "**CS-20 Dashboard.** Three campaigns with gate progress, 7 spots rendered (4 approved), AI spend today $0.796, $0.042 per approved asset against the $1,850 agency baseline (AI cost only), no open Guardian blocks, rights alerts and a hash-chained activity feed.",
       "Studio dashboard with campaign cards, spend and cost-per-asset tiles, rights alerts and recent activity"),
      ("02-brief-wizard.png",
       "**CS-04 Briefing agent.** The pasted brief is extracted into fields (objective, audience, channels, markets, budget, mandatories); completeness is 75% against the 80% needed, and three questions cover the missing key message, CTA and duration targets.",
       "Brief wizard showing extracted brief fields, a completeness meter and three clarifying questions")],
     "The $0.042 is AI spend only on a draft-quality demo campaign; the business case uses the all-in cost per version.",
     ("Two screens from the live deployment. The dashboard is the CMO view: campaign progress through the five gates, spots rendered, AI spend against the daily cap and cost per approved asset. "
      "The 0.042 dollar figure is AI spend only, on a draft-quality demo campaign; it is not the all-in business-case cost, which adds review, licences and integration. "
      "The brief wizard shows the Briefing agent turning free text into structured fields, scoring completeness and asking at most three clarifying questions. Both screens carry the synthetic-data banner. "
      "Question to expect: can we use our own brief? Yes, paste it or fill the fields.")),
    ("The Brand Brain and the claims library ground every agent in the brand's own rules",
     [("03-brand-brain.png",
       "**CS-01 Brand Brain.** Versioned brand kit for the fictional Northwind Coffee Roasters (palette, typography, voice, forbidden words), 68 indexed passages and 56 learnings; semantic search returns cited passages with relevance scores.",
       "Brand Brain page with the brand kit, colour swatches, forbidden words and a cited semantic search"),
      ("04-claims-library.png",
       "**CS-02 Claims library.** 4 approved, 6 prohibited and 5 needs-substantiation claims plus 5 regulated rule packs; the claim checker flags “cures morning anxiety” and “burns fat” as prohibited and suggests compliant wording.",
       "Claims library with counts of approved, prohibited and needs-substantiation claims and a claim checker returning a BLOCK verdict")],
     "Deterministic rules come first and the model only assists, so every verdict can be explained.",
     ("The Brand Brain holds the versioned brand kit and the ingested guidelines, embedded and retrieved with citations; every agent grounds on it, and learnings from performance data are written back. "
      "In this deployment the brand is the fictional Northwind Coffee Roasters and the brand book is synthetic. The claims library holds approved, prohibited and needs-substantiation claims per market, "
      "with required disclaimers and regulated-category rule packs such as EU health claims. The checker on the right is the function the Guardian calls, so what you see is what is enforced. "
      "Question to expect: who maintains the library? In the demo only the Legal role can edit it.")),
    ("Rights are checked before use, and the storyboard keeps the brand on screen",
     [("05-rights-registry.png",
       "**CS-03 Rights registry.** Music, talent, stock and font entries with territories and windows; expiry alerts (one consent expired 321 days ago, one has 20 days left) and a “Would this use be cleared?” check, the same one the Guardian runs.",
       "Rights registry with expiry alerts, a registry table and a clearance check form"),
      ("06-creative-workspace-storyboard.png",
       "**CS-07 Art Director.** A four-frame, 15 s storyboard from gpt-image-1.5 at draft quality, Guardian PASS · 100; each shot has a purpose (hook, product, proof, brand), a duration and a camera move.",
       "Storyboard tab with four generated keyframes for the Dawn Roast spot")],
     "Out-of-rights use is blocked before approval; hero-quality images need an explicit premium approval.",
     ("The rights registry records music, talent likeness and voice consent, stock and fonts, with territories, windows, channel limits and an AI-consent flag. Expiry alerts go to Teams or Slack, "
      "and the same clearance check runs inside the Guardian, so out-of-rights use is blocked before it reaches approval. The storyboard is generated by the Art Director with gpt-image-1.5 at low quality by default: "
      "hero quality needs an explicit premium approval, which keeps cost visible. Each frame carries its beat, duration and camera move, and the storyboard passes the Guardian before voice and render. "
      "Question to expect: can talent likeness be cloned? No, voice cloning is not offered.")),
    ("Voice-over is timed to each beat, and localization is checked by back-translation",
     [("08-voice-and-music.png",
       "**CS-09 Sound Designer.** Polish voice-over (neural pl-PL-ZofiaNeural): 14.23 s of speech for $0.0031, timed per beat with speed adjustments; two lines are flagged as too long for their beat; SRT captions with 8 cues.",
       "Voice and audio tab with a Polish voice-over table of beats, timings and audio players"),
      ("10-localization.png",
       "**CS-10 Localizer.** Seven target languages are offered besides the English source (DE, FR, ES, IT, PL, PT, NL); German, French and Polish are selected. The German version transcreates the tagline as “Wach langsam auf”, passes the Guardian (100) and QA at a minimum back-translation similarity of 0.799. Latin, Cyrillic and Greek scripts ship; CJK and Arabic need extra fonts.",
       "Localization tab with the German transcreation, back-translation and similarity scores per line")],
     "Lines below the back-translation threshold go to a human reviewer instead of passing silently.",
     ("The Sound Designer turns each script beat into timed voice-over with Azure OpenAI text-to-speech or Azure AI Speech neural voices, flags lines that are too long for their beat and produces SRT captions. "
      "This Polish voice-over cost a third of a cent. The Localizer does transcreation, not literal translation: it enforces the glossary and do-not-translate terms, back-translates every line to English, "
      "scores similarity and sends weak lines to a human reviewer. Each language version gets its own local-market Guardian review. CJK and Arabic need extra caption fonts, which are documented but not shipped.")),
    ("One approved master fans out to formats and cut-downs, and is scored before launch",
     [("09-formats-and-cutdowns.png",
       "**CS-11 Format factory.** Options: ratios 9:16, 1:1 and 4:5, cut-downs of 6, 15 and 30 s (9:16, 1:1 and 6 s selected). The version tree shows the approved master v1 with its 9:16, 1:1 and 6 s derivatives approved and the DE, FR and PL localizations as drafts awaiting approval, all Guardian PASS · 100.",
       "Format factory with aspect-ratio and cut-down options and a version tree of the master and its derivatives"),
      ("11-preflight-scorecard.png",
       "**CS-16 Pre-flight scorecard.** Predicted score 85/100 (heuristics 91, synthetic panel appeal 7/10, 67% would click), labelled SIMULATED; hook 90, brand presence 100, clarity 59, call to action 100, accessibility 100, compliance 100.",
       "Pre-flight scorecard with a predicted score of 85 out of 100, a radar chart and a weighted breakdown")],
     "Scores are predictions from a synthetic panel; real uplift is measured with live tests.",
     ("The format factory reframes the approved master with per-scene focal points and platform safe areas, cuts six, fifteen or thirty second versions by scene priority and re-lays out the overlays and end card. "
      "Every derived version appears in the version tree with its own Guardian result and approval. The pre-flight scorecard predicts how a creative will perform using heuristics and a synthetic audience panel. "
      "It is labelled simulated and is not a measurement; it ranks variants before launch so real budget goes to better candidates, and it must be validated with live tests. "
      "Question to expect: is the 85 a forecast? No, it is a ranking aid.")),
    ("Auto-revise converges to a passing script, and approvals are gated by role and SLA",
     [("14-guardian-auto-revise.png",
       "**CS-12 Guardian after auto-revise.** The same subject now passes (100/100, no findings); the loop log shows iteration 1 was blocked (9 blocks, 1 warning) and 10 fixes were applied: wording replaced, caffeine disclaimer added, brand colour restored, music swapped, talent replaced, stock removed.",
       "Guardian report with verdict PASS and score 100, and the auto-revise loop log listing the applied fixes"),
      ("15-approvals-inbox.png",
       "**CS-13 Approval inbox.** Five requests approved, none pending or overdue; each shows its Guardian result (PASS · 100), required roles (creative director, legal), SLA (48-72 h) and decision comments; a request with open blocking findings cannot be approved.",
       "Approval inbox with counters and approved requests showing Guardian results, roles and SLAs")],
     "Fixes are applied and re-checked automatically; a human still approves each gate.",
     ("Here the Guardian has run auto-revise on the unsafe subject from the earlier slide: ten fixes later it passes with no findings. The log shows each iteration, the rule that fired and the fix applied, "
      "so reviewers can audit what changed. The approval inbox shows the gates that follow: each request carries the Guardian result, the required roles, an SLA and the comments of the approvers. "
      "A request with open blocking findings cannot be approved; only Legal can waive, with a recorded reason. "
      "Question to expect: who approved these? In the demo the roles are self-declared; production uses Entra ID app roles.")),
    ("Gates are ordered and role-bound; every asset carries a manifest that detects tampering",
     [("16-approvals-and-audit-chain.png",
       "**CS-13 Stage gates.** Brief, Concept, Script, Storyboard and Final spot, each with its artifact version, Guardian result (Concept shows WARN · 94), required roles, SLA (24-72 h) and state; earlier gates must be approved first and the Guardian re-runs on every decision.",
       "Approvals and audit tab with the stage-gate table and the final-spot approval request"),
      ("12-provenance-tamper-test.png",
       "**CS-14 Provenance.** Coverage 100%; verification AUTHENTIC on five checks (asset hash, manifest hash, Ed25519 signature, audit-chain anchor, 8 ingredient hashes); the manifest lists generator, models, AI-generated: YES and linked rights. “Run tamper test” shows a modified file or manifest is rejected; the manifest is C2PA-style, not a certified Content Credential.",
       "Provenance tab with a verification result of AUTHENTIC and a manifest summary")],
     "Provenance is signed and tamper-evident today; certified C2PA Content Credentials are a Release 2 item.",
     ("The stage-gate table shows the fixed order of approvals and who must sign each: brand manager for the brief, creative director for concept and storyboard, creative director plus legal for the script "
      "and the final spot, with SLAs from 24 to 72 hours. The Guardian re-runs on every request and decision. The provenance tab shows the signed manifest bound to the file hash: five checks verify, "
      "including the audit-chain anchor, and a tamper test shows that a modified file or manifest fails. The screen says plainly that the format is C2PA-style and not a certified Content Credential. "
      "Question to expect: what is the Release 2 path? CA-issued signing with Key Vault or HSM keys.")),
    ("More versions only pay with learning allocation; the planner shows where spend should go",
     [("17-variants-bandit-experiment.png",
       "**CS-17 Variant engine.** A hook × CTA × visual matrix (3 × 2 × 2 = 12 variants) is built and ranked pre-flight; Thompson sampling then shifts budget against the simulated ad platform. The completed 24-hour run shows leader v03 (P(best) 46%), significant at p = 0.010 against the control, +17.1% clicks versus uniform allocation and 8 of 12 losers auto-paused; the stacked chart shows budget share moving to the winners hour by hour.",
       "Variant engine with a matrix builder for hooks, calls to action and visuals and a list of experiments"),
      ("19-media-planner.png",
       "**CS-19 Media planner.** For a $400,000 budget the optimiser splits spend across YouTube, Meta, TikTok and CTV (LinkedIn and display get none): expected ROAS 0.99× (p10-p90 0.81×-1.19×), revenue $389,556, +16.9% vs a uniform split. Illustrative.",
       "Media planner with a recommended budget split by channel and marginal ROAS chart")],
     "Both screens run on a simulator: ranges and rankings are illustrative until validated with live data.",
     ("The variant engine builds a matrix of hooks, calls to action and visuals, ranks the combinations pre-flight and lets Thompson sampling shift budget to winners hour by hour against a simulated ad platform; "
      "significance is tested and losers are auto-paused. In the live smoke test the leading variant was within 0.3 percent of the simulator's best, eight losers were paused and clicks beat uniform allocation by 17.1 percent. "
      "The media planner uses diminishing-returns curves and Monte-Carlo ranges to suggest a channel split. Both are illustrative until connected to real data and proven against a holdout.")),
    ("The asset library keeps everything searchable, and the cost meter keeps generation capped",
     [("20-asset-library.png",
       "**CS-21 Asset library.** 48 assets (spots, images, voice-overs, captions, campaign packs) in private Blob Storage, served only through the API with Entra RBAC; keyword or semantic search, filters by kind, status and collection; AI-generated assets carry an “AI” badge.",
       "Asset library grid of images, spots, audio files and captions with search and filters"),
      ("21-cost-meter.png",
       "**CS-15 Cost meter.** AI spend today $0.802 of the $5.00 cap (16%), 793 metered calls (35 served from the prompt cache), $0.042 per approved asset; the guard fails closed and has refused 1 call since start; spend is split by service and by feature.",
       "Cost meter with spend against the daily cap, a bar chart by service and spend by feature")],
     "Daily and per-campaign caps fail closed: generation stops with a clear message instead of overspending.",
     ("The asset library holds everything the studio produces or you upload, in private Blob Storage that is served only through the API with Entra RBAC and no public blobs. Search is by keyword or semantic "
      "similarity, with filters; AI-generated assets are badged. The cost meter prices every model call at list price and enforces a daily cap and a per-campaign cap that fail closed; the live smoke test proved a refusal with a clear message. "
      "Premium, hero-quality generation needs an explicit approval. Token prices come from the Azure Retail Prices API, the same source as the business case, so measured and forecast cost can be compared. Prices are list-price estimates; validate against your invoice.")),
    ("Expansion on lifts ACR and NPV in the calculator; roles and integrations are enforced by the API",
     [("22b-roi-expansion-on.png",
       f"**CS-23 Calculator, expansion on.** The four levers at full scale on the Base case: ROI {FC['roi_pct']:.0f}%, NPV {M(FC['npv'])}, payback {FC['payback_months']:.1f} months, IRR {FC['irr_pct']:.0f}%, "
       f"Year-3 ACR {K(FC['run_rate_year3'])}, benefit {M(FC['total_benefit'])} against cost {M(FC['total_cost'])}.",
       "Business case calculator with expansion switched on and the KPI strip recomputed"),
      ("23-team-and-integrations.png",
       "**CS-22 Team & integrations.** Six roles (admin, brand manager, creative director, creative, legal, agency guest) enforced on the API; Teams/Slack-compatible webhooks, OpenAPI at /openapi.json, rate limits of 24 AI-spending calls and 90 writes per minute per IP.",
       "Team and integrations page with the roster of six roles, REST API details and a permissions table")],
     "Production uses Entra ID app roles; the demo's role switcher is self-declared and bounded by the $5 daily AI cap.",
     (f"With expansion switched on, the calculator adds the four optional levers at full scale to the Base case. Year-3 ACR rises from {ACR_Y[3] / 1e3:.0f} to {FC['run_rate_year3'] / 1e3:.0f} thousand dollars and NPV from "
      f"{roi['npv'] / 1e6:.2f} to {FC['npv'] / 1e6:.2f} million, while payback lengthens to about {FC['payback_months']:.0f} months because the integration costs come first. The levers are modelled, not built, and are off in Base. "
      "The team screen shows six roles enforced on every mutating endpoint, webhooks with an SSRF guard, a documented REST API and the rate limits. "
      "Demo identities are self-declared; production uses Entra ID app roles and B2B guests for agencies.")),
    ("Operations show live dependency health, and the feature map shows 24 of 24 implemented",
     [("24-ops-observability.png",
       "**CS-24 Operations.** /readyz reports six live dependencies OK (Cosmos DB, Blob, Azure OpenAI, Content Safety, Speech, ffmpeg) at 14-916 ms; mode AZURE in swedencentral; telemetry via OpenTelemetry to Application Insights (Entra-authenticated); 9 jobs succeeded, 0 failed.",
       "Operations page with dependency health, deployment details, guardrails and the job runner"),
      ("25-feature-map.png",
       "**Feature map.** Rendered live from /api/features: 24 / 24 IMPLEMENTED across Epics A-E; each row shows the CS-ID, priority, status and the API route that serves it.",
       "Feature map listing the Release 1 features by epic with status and API route")],
     "The feature map is generated from the running system, so it cannot drift from what is deployed.",
     ("The operations page shows the live health of every dependency the studio calls: Cosmos DB, Blob Storage, Azure OpenAI, Content Safety, Speech and ffmpeg, each with its latency, plus the deployment mode, "
      "region, telemetry path, guardrails and job runner. Deployment is keyless, with managed identity only. The feature map is rendered from the running application's own registry: twenty-four of twenty-four "
      "implemented, each with its API route. It is the quickest answer to whether what we describe is what is deployed. Question to expect: where is the evidence? In the verification report and the status board.")),
]


def gallery(n: int, title: str, items, takeaway: str, notes: str) -> None:
    """Two screenshots side by side with captions; items = (png name, caption, alt text). Missing PNGs are skipped."""
    found = [(p, cap, alt) for name, cap, alt in items if (p := shot(name)) is not None]
    if not found:
        return
    d.set_section(f"Product screens {n}/{len(GALLERIES)} · live on Azure, synthetic data")
    s = d._new(title, notes=notes)
    top = d._content_top(None, s)
    gap = 0.3
    w = (deckkit.CONTENT_W - gap) / 2
    h = w * 900 / 1600
    for i, (p, cap, alt) in enumerate(found):
        x = deckkit.MARGIN + i * (w + gap)
        d._rect(s, x - 0.05, top - 0.05, w + 0.1, h + 0.1, d.t.line, radius=0.06)
        set_alt(s.shapes.add_picture(str(p), Inches(x), Inches(top), Inches(w), Inches(h)), alt)
        d.text(s, x, top + h + 0.1, w, 6.04 - (top + h + 0.1), [Para(cap, space_after=0)], size=11, min_size=8.5, label="caption")
    d._takeaway(s, takeaway)
    d._source(s, GAL_SRC)
    d.set_section("Appendix")


for gi, (g_title, g_items, g_take, g_notes) in enumerate(GALLERIES, 1):
    gallery(gi, g_title, g_items, g_take, g_notes)

# Any screenshot that engineering adds later and that is not placed above is appended as a plain slide (re-runnable, nothing is dropped silently)
for p in [q for q in screens if q.name not in placed]:
    pretty = re.sub(r"^\d+[a-z]?[-_ ]*", "", p.stem).replace("-", " ").replace("_", " ").strip().title()
    d.set_section("Product screens · live on Azure, synthetic data")
    s_extra = d.screenshot(f"Product screen: {pretty}", p, caption=pretty, takeaway="Real screen from the reference implementation (synthetic data).", source=GAL_SRC,
                           notes=("This is a real screen from the reference implementation running on Azure with synthetic data. Walk through what the user sees, which feature on the status board it belongs to, "
                                  "and which part is simulated. Every screen carries the synthetic-data indicator at the bottom so nobody mistakes the demo for production. "
                                  "Question to expect: is this the production UI? It is the Release 1 UI; enterprise hardening such as Entra sign-in, private networking and a WAF is described in the architecture document as the target."))
    set_alt(next(sh for sh in s_extra.shapes if sh.shape_type == MSO_SHAPE_TYPE.PICTURE), pretty)
    d.set_section("Appendix")

d.table(
    "Glossary",
    ["Term", "Meaning"],
    [
        ["ACR", "Azure Consumed Revenue: what a customer pays Azure for consumption (list price in this model)"],
        ["Brand Brain", "Versioned, retrievable knowledge of brand guidelines, voice, catalogue, personas and learnings"],
        ["Guardian", "Automated multi-check (voice, identity, claims, rights, safety) that blocks approval on failures"],
        ["Stage gate", "Human approval point: brief, concept, script, storyboard, final"],
        ["Provenance manifest", "Signed record of an asset's hashes, models, prompt digests, inputs and approvals (C2PA-style)"],
        ["Transcreation", "Adaptation of meaning, tone and claims for a market rather than literal translation"],
        ["VideoProvider", "Interface behind which the ffmpeg compositor or any video model renders a timeline spec"],
        ["Bandit (Thompson sampling)", "Allocation method that shifts budget to better variants while still exploring"],
    ],
    col_weights=[2.4, 7.6],
    notes=("A short glossary for the terms used in this deck. ACR is Azure Consumed Revenue at list price. The Brand Brain is the grounding knowledge. The Guardian is the automated checker that blocks approval. "
           "Stage gates are the human approval points. A provenance manifest is the signed record of how an asset was made. Transcreation means adapting meaning and claims for a market. VideoProvider is the abstraction "
           "that lets us swap the ffmpeg compositor for a video model. A bandit allocates spend to winners while still exploring. The PRD has the full glossary."),
)

SOURCES = [
    "Gartner, Gartner 2026 CMO Spend Survey Finds CMOs Allocate 15.3% of Marketing Budgets to AI, But Only 30% Are Ready to Scale AI Capabilities, 2026. gartner.com/en/newsroom/press-releases/2026-05-11-...",
    "Gartner, CMO Spend 2026, 2026. https://www.gartner.com/en/articles/cmo-spend",
    "WARC Media, Global advertising spend surges 11.9% to $1.34trn this year amid consumer caution, 2026. https://www.warc.com/",
    "Adobe, Adobe research finds demand for content will grow 5x by 2027, 2025. https://business.adobe.com/blog/71-percent-of-marketers-say-content-demand-to-increase-5x",
    "McKinsey & Company, The State of AI: Global Survey 2025, 2025. https://www.mckinsey.com/capabilities/quantumblack/our-insights/the-state-of-ai",
    "Reuters via Yahoo Finance, Oreo-maker Mondelez to use new generative AI tool to slash marketing costs, 2025. https://ca.finance.yahoo.com/news/oreo-maker-mondelez-generative-ai-005502050.html",
    "Nielsen (NCSolutions), When it comes to advertising effectiveness, what is key?, 2017. https://www.nielsen.com/insights/2017/when-it-comes-to-advertising-effectiveness-what-is-key/",
    "European Commission, Quick Facts: Transparency rules for AI systems (Article 50 AI Act), 2026. https://digital-strategy.ec.europa.eu/en/factpages/quick-facts-transparency-rules-ai-systems",
    "European Commission, Code of Practice on Transparency of AI-generated Content, 2026. https://digital-strategy.ec.europa.eu/en/policies/code-practice-ai-generated-content",
    "European Commission, Guidelines on transparency obligations for providers and deployers of certain AI systems, 2026. https://digital-strategy.ec.europa.eu/en/policies/guidelines-ai-transparency-obligations",
    "EUR-Lex, Directive (EU) 2024/825 empowering consumers for the green transition (summary), 2024. https://eur-lex.europa.eu/legal-content/EN/LSU/?uri=CELEX:32024L0825",
    "European Commission, Consumer protection: enabling sustainable choices and ending greenwashing, 2023. https://cyprus.representation.ec.europa.eu/news/",
    "Microsoft Learn, Content Credentials in Azure OpenAI, 2026. https://learn.microsoft.com/en-us/azure/foundry-classic/openai/concepts/content-credentials",
    "Microsoft Learn, What is Azure AI Content Safety?, 2026. https://learn.microsoft.com/azure/ai-services/content-safety/overview",
    "C2PA, Content Credentials: C2PA Technical Specification v2.4, 2026. https://spec.c2pa.org/specifications/specifications/2.4/specs/C2PA_Specification.html",
    "YouTube Help, Disclosing use of GenAI content, 2026. https://support.google.com/youtube/answer/14328491",
    "Microsoft, Azure Retail Prices API (list prices, USD), retrieved 17 Nov 2026. https://prices.azure.com/api/retail/prices",
    "Microsoft Learn, Azure Well-Architected Framework pillars and AI workloads, 2026. https://learn.microsoft.com/azure/well-architected/pillars",
    "Microsoft Learn, Video generation with Sora 2 (preview): per-second billing, region availability, 2026. https://learn.microsoft.com/azure/foundry/openai/concepts/video-generation",
    "McKinsey & Company, The value of getting personalization right—or wrong—is multiplying, 2021. https://www.mckinsey.com/capabilities/growth-marketing-and-sales/our-insights/the-value-of-getting-personalization-right-or-wrong-is-multiplying",
    "SwarmAI, PRD.md, ARCHITECTURE.md, FEATURES.md and business-case/ (model, assumptions, outputs), 2026.",
    "SwarmAI, REPORT-TEST-AND-DEPLOYMENT.md and app/evidence/ (engineering verification of the live deployment, 17-18 Nov 2026), 2026.",
]
d.sources("Sources", SOURCES, notes=("Sources used in this deck. Market facts come from Gartner, WARC, Adobe, McKinsey, Reuters and Nielsen; regulatory facts from the European Commission and EUR-Lex; Azure facts from Microsoft Learn and the Azure Retail Prices API. "
                                      "Business-case numbers come only from the model outputs, which cite their assumptions. Secondary summaries of platform and likeness rules are listed in the PRD with a flag; "
                                      "please check primary texts before relying on them externally."))
d.set_section(None)

out = d.save(OUT)
n = len(d.prs.slides)
print(f"saved {out} slides={n} screens={len(screens)} warnings={len(d.warnings)}")
bad_notes = []
for i, sl in enumerate(d.prs.slides, 1):
    words = len(sl.notes_slide.notes_text_frame.text.split()) if sl.has_notes_slide else 0
    if not 60 <= words <= 120:
        bad_notes.append((i, words))
if bad_notes:
    print("NOTES outside 60-120 words (slide, words):", bad_notes)
for w in d.warnings:
    print("WARNING:", w)
if d.warnings or bad_notes:
    sys.exit(1)
