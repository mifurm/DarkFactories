#!/usr/bin/env python3
"""Executive deck for SwarmAI Contact Center ("Concierge") — built with the shared deckkit (python-pptx).

    /Users/michalfu/Dev/SwarmAI/.venv/bin/python deck/build_deck.py

* Every number on a slide comes from business-case/outputs.json (+ assumptions.json) or from a cited source (ids S1…S31 = PRD §20).
* Screenshots are picked up from deck/assets/screens/ (sorted by filename); the script is re-runnable and idempotent.
* FEATURES.md is parsed for the feature names / priorities / status so the deck never drifts from the contract.
* The storyline (main part, Azure-opportunity part, appendix) is the slide order below; speaker notes sit next to each slide.
"""
from __future__ import annotations

import json
import math
import os
import re
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, "/Users/michalfu/Dev/SwarmAI/tools/deckkit")
from lxml import etree  # noqa: E402
from PIL import Image  # noqa: E402
from pptx.enum.chart import XL_LABEL_POSITION, XL_TICK_LABEL_POSITION  # noqa: E402
from pptx.enum.shapes import MSO_SHAPE  # noqa: E402
from pptx.oxml.ns import qn  # noqa: E402
from pptx.util import Inches  # noqa: E402

from deckkit import CONTENT_W, MARGIN, Deck, Para, Theme, rgb, shade, tint  # noqa: E402

OUT_PPTX = Path(os.environ.get("DECK_OUT", HERE / "ContactCenter-Executive-Deck.pptx"))
SCREENS = Path(os.environ.get("DECK_SCREENS_DIR", HERE / "assets" / "screens"))

# ----------------------------------------------------------------------------------------------------------------------
# data: business case, assumptions, features, sources
# ----------------------------------------------------------------------------------------------------------------------
OUT = json.loads((ROOT / "business-case" / "outputs.json").read_text(encoding="utf-8"))
ASM = json.loads((ROOT / "business-case" / "assumptions.json").read_text(encoding="utf-8"))
SC = OUT["scenarios"]
B, CO, UP = SC["base"], SC["conservative"], SC["upside"]
STRESS = OUT["stress"]
A = ASM["assumptions"]
UPRICE = ASM["unit_prices"]
_PD = __import__("datetime").date.fromisoformat(OUT["meta"]["price_date"])
PRICE_SHORT = f"{_PD.day} {_PD.strftime('%b %Y')}"  # 17 Nov 2026
PRICE_LONG = f"{_PD.day} {_PD.strftime('%B %Y')}"  # 17 November 2026
_RT = UPRICE["rt_mini_audio_in"]
GLOBAL_CHEAPER = f"{(1 - _RT['global'] / _RT['datazone']) * 100:.0f}%"  # Global vs Data Zone deployment price
DZ_PREMIUM = f"{(_RT['datazone'] / _RT['global'] - 1) * 100:.0f}%"


def m(x: float, d: int = 1) -> str:
    return f"${x / 1e6:,.{d}f}M"


def neg_m(x: float, d: int = 1) -> str:
    return ("−" if x < 0 else "") + f"${abs(x) / 1e6:,.{d}f}M"


def kk(x: float) -> str:
    return f"${x / 1e3:,.0f}K"


def share(x: float, d: int = 0) -> str:
    return f"{x * 100:.{d}f}%"


pct0 = share  # fraction -> "30%"


def spaced_slashes(name: str) -> str:
    """'Prompt/policy/knowledge' -> 'Prompt / policy / knowledge' so narrow columns wrap at the slash instead of mid-word."""
    return re.sub(r"(?<=\w)/(?=\w)", " / ", name)


def words(text: str) -> int:
    return len(re.findall(r"\S+", text))


R = B["roi"]
BEN, COST, ACR, UE = B["benefits"], B["costs"], B["acr"], B["unit_economics"]
BY_CAT = BEN["by_category"]
BEN_TOT = BEN["total"]
RAMP = B["inputs"]["ramps"]["adoption_ramp"]
cat_total = {k_: sum(v) for k_, v in BY_CAT.items()}
FAM_Y3 = {k_: v[3] for k_, v in ACR["by_family"].items()}
AI_FAMS = ("openai_realtime", "openai_text", "speech", "language", "content_safety", "ai_search")
AI_Y3 = ACR["pull_through"]["ai_services_year3"]
TIERS = ACR["tiers"]
OPP = ACR["opportunity_sizing"]

n = SimpleNamespace(
    npv=m(R["npv"]), roi=f"{R['roi_pct']:.0f}%", irr=f"{R['irr_pct']:.0f}%", payback=f"{R['payback_months']:.1f}",
    payback_gl=f"{R['payback_months_from_go_live']:.1f}", ben3=m(BEN_TOT), cost3=m(COST["total"]),
    acr3=m(ACR["run_rate_year3"], 2), acr_y=[m(x, 2) for x in ACR["by_year"]], acr_3yr=m(ACR["three_year_total"], 2),
    stress_dn=neg_m(STRESS["stacked_downside"]["npv_usd"]), stress_up=neg_m(STRESS["stacked_upside"]["npv_usd"]),
    npv_c=m(CO["roi"]["npv"]), npv_u=m(UP["roi"]["npv"]),
    y0=m(COST["total_by_year"][0]), cum3=m(R["cumulative"][3]),
    ai_all_in=f"${UE['all_in_ai_cost_per_resolved_contact_usd']:.2f}", human_res=f"${UE['human_cost_per_resolved_contact_usd']:.2f}",
    ratio=f"{UE['human_to_ai_cost_ratio_per_resolved_contact']:.1f}×", ai_all_in_c=f"${CO['unit_economics']['all_in_ai_cost_per_resolved_contact_usd']:.2f}",
    ai_all_in_u=f"${UP['unit_economics']['all_in_ai_cost_per_resolved_contact_usd']:.2f}",
    voice_min=f"${UE['azure_cost_per_voice_ai_minute_usd']:.3f}", voice_min_plat=f"${UE['platform_cost_per_voice_ai_minute_usd']:.3f}",
    azure_per_res=f"${UE['total_azure_cost_per_ai_resolved_contact_usd']:.2f}", cpc=f"${UE['human_cost_per_contact_usd']:.2f}",
    ai_share=share(AI_Y3 / ACR["run_rate_year3"]), pull=f"${ACR['pull_through_ratio']:.2f}",
    comms3=m(ACR["communications_outside_azure_by_year"][3], 2), blended=f"{UE['blended_cost_reduction_pct']:.0f}%",
    agents=f"{A['agents']['base']:,.0f}", contacts=f"{A['contacts_per_year']['base'] / 1e6:.0f}M",
    ramp=[share(x) for x in RAMP], seat_yr=f"${OPP['acr_per_seat_per_year_usd']:,.0f}",
    fte=f"{UE['fte_equivalent_released_year3_risk_adjusted']:.0f}",
)


def feature_board() -> list[dict]:
    rows = []
    for line in (ROOT / "FEATURES.md").read_text(encoding="utf-8").splitlines():
        mt = re.match(r"\|\s*(CC-\d\d)\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*(P\d)\s*\|\s*(.+?)\s*\|\s*(.*?)\s*\|\s*$", line)
        if mt:
            rows.append(dict(id=mt[1], name=mt[2], epic=mt[3], prio=mt[4], status=mt[5], evidence=mt[6]))
    assert len(rows) == 24, f"expected 24 features, found {len(rows)}"
    return rows


def prd_sources() -> list[tuple[str, str]]:
    """[(S#, 'Publisher — Title (year). URL')] parsed from PRD §20, in id order."""
    items = []
    for line in (ROOT / "PRD.md").read_text(encoding="utf-8").splitlines():
        mt = re.match(r"\|\s*(S\d+)\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*(\S+)\s*\|\s*(\S+)\s*\|\s*(.*?)\s*\|\s*$", line)
        if mt:
            items.append((mt[1], f"{mt[2]} — {mt[3]} ({mt[4]}). {mt[5]}"))
    items.sort(key=lambda t: int(t[0][1:]))
    return items


FEATURES = feature_board()
EPICS: dict[str, list[dict]] = {}
for f_ in FEATURES:
    EPICS.setdefault(f_["epic"], []).append(f_)
STATUS_COUNTS: dict[str, int] = {}
for f_ in FEATURES:
    STATUS_COUNTS[f_["status"]] = STATUS_COUNTS.get(f_["status"], 0) + 1
HAS_STATUS = any(f_["status"] != "Planned" for f_ in FEATURES)  # an untouched board (all "Planned") is not shown as if it were the product's state
RELEASE = {"P0": "MVP", "P1": "Beta", "P2": "GA"}


class CCDeck(Deck):
    """deckkit.Deck plus slide types the kit does not ship: dual_chart, pillars and reference_list."""

    @staticmethod
    def _no_invert(series, idx: int) -> None:
        """Per-point fills need their own invertIfNegative=0, otherwise LibreOffice mirrors negative bars."""
        dpt = series._element.get_or_add_dPt_for_point(idx)
        if dpt.find(qn("c:invertIfNegative")) is None:
            inv = etree.Element(qn("c:invertIfNegative"))
            inv.set("val", "0")
            dpt.find(qn("c:idx")).addnext(inv)

    def pillars(self, title: str, items: list[dict], takeaway: str | None = None, notes: str | None = None, source: str | None = None):
        """Chevron header per pillar, a card with bullets underneath and a KPI chip at the foot of each card."""
        s = self._new(title, notes=notes)
        top = self._content_top(None, s)
        bottom = 6.0 if takeaway else 6.62
        k_ = len(items)
        gap = 0.1
        w = (CONTENT_W - gap * (k_ - 1)) / k_
        head_h = 0.85
        card_top = top + head_h + 0.2
        card_h = bottom - card_top
        chip_h = 0.66
        for i, it in enumerate(items):
            x = MARGIN + i * (w + gap)
            ch = s.shapes.add_shape(MSO_SHAPE.PENTAGON if i == 0 else MSO_SHAPE.CHEVRON, Inches(x), Inches(top), Inches(w), Inches(head_h))
            ch.adjustments[0] = 0.3
            self._flat(ch, self.t.accent if i % 2 == 0 else shade(self.t.accent, 0.22))
            tx0 = 0.4 if i else 0.16
            self.text(s, x + tx0, top, w - tx0 - 0.3, head_h, [Para(f"{i + 1}  {it['title']}", bold=True, color="FFFFFF", space_after=0)], size=16, min_size=11,
                      color="FFFFFF", anchor="middle", inset=0.02, label=f"pillar {i}")
            self._rect(s, x, card_top, w, card_h, self.t.card, radius=0.08)
            self.text(s, x + 0.15, card_top + 0.12, w - 0.3, card_h - chip_h - 0.4, it["body"], size=15, min_size=10, bullet="•", label=f"pillar body {i}")
            chip = self._rect(s, x + 0.15, card_top + card_h - chip_h - 0.15, w - 0.3, chip_h, tint(self.t.accent, 0.82), radius=0.08)
            self.text(s, x + 0.15, card_top + card_h - chip_h - 0.15, w - 0.3, chip_h, [Para(it["kpi"], bold=True, color=shade(self.t.accent, 0.3), align="center", space_after=0)],
                      size=12.5, min_size=9, anchor="middle", align="center", shape=chip, inset=0.07, label=f"pillar kpi {i}")
        if takeaway:
            self._takeaway(s, takeaway)
        self._source(s, source)
        return s

    def dual_chart(self, title: str, left: dict, right: dict, takeaway: str | None = None, notes: str | None = None, source: str | None = None):
        """Two native charts side by side. Spec keys: heading, categories, series, kind, number_format, legend, labels, colors, point_colors, tornado."""
        s = self._new(title, notes=notes)
        top = self._content_top(None, s)
        bottom = 6.0 if takeaway else 6.62
        gap = 0.45
        w = (CONTENT_W - gap) / 2
        for i, spec in enumerate((left, right)):
            x = MARGIN + i * (w + gap)
            self.text(s, x, top, w, 0.4, [Para(spec["heading"], bold=True, space_after=0)], size=15, min_size=11, label="chart heading")
            ch = self._add_chart(s, x, top + 0.45, w, bottom - top - 0.45, spec["categories"], spec["series"], spec.get("kind", "column"),
                                 spec.get("number_format"), spec.get("legend", False), spec.get("labels", True), spec.get("label_format"),
                                 spec.get("colors"), spec.get("gap_width", 60))
            if spec.get("point_colors"):
                ser = ch.plots[0].series[0]
                for pi, col in enumerate(spec["point_colors"]):
                    ser.points[pi].format.fill.solid()
                    ser.points[pi].format.fill.fore_color.rgb = rgb(col)
                    self._no_invert(ser, pi)
            if spec.get("tornado"):
                dl = ch.plots[0].data_labels
                dl.font.color.rgb = rgb("FFFFFF")
                dl.font.bold = True
                dl.position = XL_LABEL_POSITION.INSIDE_BASE
                ch.category_axis.tick_label_position = XL_TICK_LABEL_POSITION.LOW
        if takeaway:
            self._takeaway(s, takeaway)
        self._source(s, source)
        return s

    @staticmethod
    def stretch_table(s, bottom: float = 5.95) -> None:
        """Let a short table fill the content area (the kit stretches rows by at most 1.5x)."""
        gf = next(sh for sh in s.shapes if sh.has_table)
        total = sum(r.height for r in gf.table.rows)
        target = Inches(bottom) - gf.top
        if total < target:
            k = target / total
            for r in gf.table.rows:
                r.height = int(r.height * k)
            gf.height = int(total * k)

    def triptych(self, title: str, items: list[dict], takeaway: str | None = None, notes: str | None = None, source: str | None = None):
        """Three screenshots side by side, each with a heading above and bullets below. items: {'image', 'heading', 'bullets'}."""
        s = self._new(title, notes=notes)
        top = self._content_top(None, s)
        bottom = 6.0 if takeaway else 6.62
        k_ = len(items)
        gap = 0.3
        w = (CONTENT_W - gap * (k_ - 1)) / k_
        for i, it in enumerate(items):
            x = MARGIN + i * (w + gap)
            self.text(s, x, top, w, 0.42, [Para(it["heading"], bold=True, color=self.t.accent, space_after=0)], size=16, min_size=11, label="triptych heading")
            with Image.open(it["image"]) as im:
                iw, ih = im.size
            ph = w * ih / iw
            y = top + 0.5
            self._rect(s, x - 0.04, y - 0.04, w + 0.08, ph + 0.08, self.t.line, radius=0.06)
            s.shapes.add_picture(str(it["image"]), Inches(x), Inches(y), Inches(w), Inches(ph))
            cap_top = y + ph + 0.12
            self.text(s, x, cap_top, w, bottom - cap_top, it["bullets"], size=13, min_size=9.5, bullet="•", label=f"triptych bullets {i}")
        if takeaway:
            self._takeaway(s, takeaway)
        self._source(s, source)
        return s

    def gallery(self, title: str, items: list[tuple[Path, str]], notes: str | None = None, source: str | None = None, cols: int = 3):
        """A grid of screenshots with one-line captions (appendix). items: [(image path, caption)]."""
        s = self._new(title, notes=notes)
        top = self._content_top(None, s)
        bottom = 6.62
        rows = math.ceil(len(items) / cols)
        gx, gy, cap_h = 0.35, 0.12, 0.62
        cw = (CONTENT_W - gx * (cols - 1)) / cols
        cell_h = (bottom - top - gy * (rows - 1)) / rows
        for idx, (img, cap) in enumerate(items):
            r_, c_ = divmod(idx, cols)
            x = MARGIN + c_ * (cw + gx)
            y = top + r_ * (cell_h + gy)
            with Image.open(img) as im:
                iw, ih = im.size
            pw = min(cw, (cell_h - cap_h) * iw / ih)
            h_ = pw * ih / iw
            self._rect(s, x - 0.03, y - 0.03, pw + 0.06, h_ + 0.06, self.t.line, radius=0.05)
            s.shapes.add_picture(str(img), Inches(x), Inches(y), Inches(pw), Inches(h_))
            self.text(s, x, y + h_ + 0.07, cw, cap_h - 0.05, [Para(cap, color=self.t.muted, space_after=0)], size=10.5, min_size=8, label=f"gallery caption {idx}")
        self._source(s, source)
        return s

    def reference_list(self, title: str, items: list[tuple[str, str]], per_slide: int, notes: list[str]):
        chunks = [items[i: i + per_slide] for i in range(0, len(items), per_slide)]
        for ci, chunk in enumerate(chunks):
            s = self._new(f"{title} ({ci + 1}/{len(chunks)})", notes=notes[ci])
            paras = [Para(f"**{sid}**   {text}", size=11, space_after=5) for sid, text in chunk]
            self.text(s, MARGIN, 1.6, CONTENT_W, 5.1, paras, size=11, min_size=7.5, label="sources")


# ----------------------------------------------------------------------------------------------------------------------
# screenshots (engineering fills deck/assets/screens/; the deck picks them by keyword so file numbering can change)
# ----------------------------------------------------------------------------------------------------------------------
# A screenshot that is internally inconsistent is skipped until the file changes (file name -> SHA-1 of the rejected capture, so a re-capture is picked up automatically).
SCREEN_SKIP_SHA1: dict[str, str] = {}

# (keywords in the file name, one-line caption for the appendix gallery) — first match wins, so specific keywords come first.
GALLERY_CAPTIONS = [
    (("supervisor",), "Supervisor console: live queues, SLA clocks and sentiment heat; take over, whisper, approve"),
    (("calculator",), "ROI and ACR calculator: reproduces the business case from the same model (NPV, payback, ACR by family)"),
    (("dashboard", "cx-"), "CX metrics on synthetic history; AI cost here is metered Azure usage only (business case: all-in cost per resolved contact)"),
    (("telephony", "adapters"), "Telephony adapters (simulated): SIP to Realtime by default, Teams Phone, legacy ACS; PSTN not provisioned"),
    (("voice-call", "voice"), "Call us (web voice): realtime model, keypad for card digits, per-turn latency (measured p95 above the 800 ms target)"),
    (("studio", "kb-admin", "knowledge"), "Knowledge admin: versioned documents, publish and roll back, injection quarantine"),
    (("feature-map", "features"), "Feature map: 24 of 24 Release 1 features, each with an API and a UI surface"),
    (("outbound", "proactive"), "Proactive outreach: consent, opt-out, quiet hours and caps; delivery simulated"),
    (("security", "rbac"), "Security and RBAC: seven roles, default-deny permission matrix, access audit"),
    (("observability", "finops"), "Observability and FinOps: latency SLOs with burn rates; voice p95 shown as burning, as measured"),
    (("routing", "escalation"), "Routing and escalation: Job-Router-style queues and rules, triggers that fire once"),
    (("customer-360", "crm"), "Customer 360 and CRM layer: timeline, orders, connector contract tests, PII masked by role"),
    (("rollout", "llmops"), "Prompt, policy and knowledge versions: evaluation gate, canary, promote, roll back"),
    (("compliance", "guard"), "Compliance guard: card, IBAN, e-mail and phone redaction; injection and output guards"),
    (("ci-gate",), "Release gate: a deliberately broken prompt is blocked (policy 0.98 against a required 1.00, two scenarios regressed)"),
    (("eval", "harness"), "Evaluation and simulation harness: the selected run passes 42 of 42; the run list shows the live model's run-to-run variation"),
    (("qa", "quality"), "QA workbench: 100% of conversations scored with evidence"),
    (("voc", "insight"), "Voice-of-customer insights: clusters and emerging-issue alerts"),
    (("wfm", "forecast"), "Workforce forecast and Erlang-C staffing with an AI-containment what-if"),
]


def sha1(path: Path) -> str:
    import hashlib

    return hashlib.sha1(path.read_bytes()).hexdigest()


def app_crop(im):
    """Drop the dark navigation sidebar, the top status bar and the footer line of an app screenshot (widget and call pages have none).
    Returns the cropped image and the (x, y) pixel offset of the crop, so that markers given against the full screenshot can be remapped."""
    w, h = im.size
    if sum(im.getpixel((20, h // 2))[:3]) < 200:
        x0, y0 = round(w * 256 / 1600), round(h * 48 / 900)
        return im.crop((x0, y0, w, round(h * 872 / 900))), (x0, y0)
    return im, (0, 0)


def prepare(image: Path, scratch: Path, crop: bool = False, markers: list[tuple[float, float]] | None = None) -> Path:
    """Optionally crop the app chrome and draw numbered badges (fractions of the FULL screenshot's width/height) so numbered callouts have a referent."""
    if not crop and not markers:
        return image
    from PIL import Image, ImageDraw, ImageFont

    im = Image.open(image).convert("RGB")
    full_w, full_h = im.size
    ox = oy = 0
    if crop:
        im, (ox, oy) = app_crop(im)
    if markers:
        dr = ImageDraw.Draw(im)
        r = max(14, int(im.width * 0.0145))
        try:
            font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", int(r * 1.15))
        except OSError:
            font = ImageFont.load_default()
        for i, (fx, fy) in enumerate(markers, 1):
            cx, cy = int(fx * full_w) - ox, int(fy * full_h) - oy
            dr.ellipse([cx - r, cy - r, cx + r, cy + r], fill="#" + Theme.contact_center().accent, outline="white", width=3)
            dr.text((cx, cy), str(i), fill="white", font=font, anchor="mm")
    out = scratch / (("c-" if crop else "m-") + image.name)
    im.save(out)
    return out


def caption_for(path: Path) -> str:
    low = path.name.lower()
    for keys, cap in GALLERY_CAPTIONS:
        if any(k_ in low for k_ in keys):
            return cap
    return re.sub(r"^\d+[a-z]?[-_ ]*", "", path.stem).replace("-", " ").replace("_", " ").strip().capitalize()


class Shots:
    """The screenshots found in deck/assets/screens/, sorted by file name, minus any known-bad capture."""

    def __init__(self) -> None:
        files = sorted(p for p in SCREENS.iterdir() if p.suffix.lower() in (".png", ".jpg", ".jpeg")) if SCREENS.exists() else []
        self.skipped = [p for p in files if SCREEN_SKIP_SHA1.get(p.name) == sha1(p)]
        self.all = [p for p in files if p not in self.skipped]
        self.used: set[Path] = set()

    def pick(self, *keywords: str) -> Path | None:
        for p in self.all:
            if p not in self.used and any(k_ in p.name.lower() for k_ in keywords):
                self.used.add(p)
                return p
        return None

    def rest(self) -> list[Path]:
        return [p for p in self.all if p not in self.used]


# Evidence quoted from REPORT-TEST-AND-DEPLOYMENT.md; the build fails loudly if the report no longer says so. The build id is read from the report, never typed here.
EVIDENCE_CHECKS = ["212 passed", "27 passed", "85 %", "21 / 21", "42 / 42", "40–42 / 42", "1.6 / 1.9 s", "1.3 / 1.6 s", "0.34 s", "1.13 s", "1.82 s",
                   "≈ US$28 / month", "44 attacks", "6.4 s"]


def report_text() -> str:
    path = ROOT / "REPORT-TEST-AND-DEPLOYMENT.md"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def report_builds() -> tuple[str, str] | None:
    """(final build, build the measurements were taken on) from the report's 'Final build' row."""
    mt = re.search(r"Final build \|\s*`(\d{8}-\d{6})`(?:\s*=\s*`(\d{8}-\d{6})`)?", report_text())
    return (mt.group(1), mt.group(2) or mt.group(1)) if mt else None


def evidence_drift() -> list[str]:
    txt = report_text()
    if not txt:
        return ["REPORT-TEST-AND-DEPLOYMENT.md is missing: evidence figures cannot be verified"]
    out = [f"REPORT-TEST-AND-DEPLOYMENT.md no longer contains {frag!r}: update the evidence slide" for frag in EVIDENCE_CHECKS if frag not in txt]
    return out + ([] if report_builds() else ["REPORT-TEST-AND-DEPLOYMENT.md no longer names the final build id"])


# ----------------------------------------------------------------------------------------------------------------------
# the deck
# ----------------------------------------------------------------------------------------------------------------------
def build(scratch: Path) -> CCDeck:
    d = CCDeck(Theme.contact_center(), footer="SwarmAI · Contact Center (Concierge) · Illustrative — validate with customer data",
               title="SwarmAI Contact Center (Concierge) — Executive deck")
    bad = d.t.bad
    for drift in evidence_drift():
        d._warn(drift)

    # screenshots are picked by keyword; whatever the main story does not use goes to the appendix gallery
    shots = Shots()
    chat_img = shots.pick("customer-widget", "widget")
    console_img = shots.pick("agent-console", "handoff")
    qa_img, voc_img, wfm_img = shots.pick("qa-workbench", "qa"), shots.pick("voc"), shots.pick("wfm")
    have_customers = bool(chat_img and console_img)
    have_quality = bool(qa_img and voc_img and wfm_img)
    build_id, measured_id = report_builds() or ("unknown", "unknown")
    shot_source = "Source: live screenshot of the reference implementation on Azure, 18 Nov 2026 (synthetic Contoso Home data)"
    all_deployed = HAS_STATUS and all(f_["status"].startswith("Deployed") for f_ in FEATURES)

    # ====================================================== MAIN STORY ==================================================
    # 1 · title
    d.title_slide(
        "Every conversation answered, resolved and learned from",
        "An AI-first contact center on Azure,\u00a0with\u00a0people\u00a0as\u00a0the\u00a0expertise\u00a0layer",
        tagline="SWARMAI · CONTACT CENTER (CONCIERGE)",
        meta="Executive briefing · November 2026 · Reference customer Contoso Home Retail (fictional)",
        notes=(f"Thank you for your time. Today's message is simple: an AI-first contact center should resolve contacts, not merely deflect them, "
               f"and it should make the people around it better. We will show how a swarm of specialised agents works, what guards it, what it looks like, "
               f"how it runs on Azure, and what it returns for a fictional reference customer, Contoso Home Retail, with {n.agents} agents and about "
               f"{n.contacts} contacts a year. Every number comes from a transparent list-price model; treat the figures as illustrative until validated "
               f"with your data. The product is a working reference implementation; telephony is simulated and web voice is the live channel."))

    # 2 · executive summary
    d.bullets(
        f"Approve a six-month pilot: the base case returns {n.npv} NPV and pays back in {n.payback} months",
        [
            "**The ask** — a 6-month build and pilot: 3 months of integration, then 50 seats on selected queues with a holdout",
            "**The product** — AI agents resolve Tier-1 voice and chat contacts; people take the rest with full context and a copilot; 100% of conversations are scored"
            + ("; all 24 Release 1 features are deployed and tested on Azure" if all_deployed else ""),
            f"**The case** — Contoso Home Retail ({n.agents} agents, {n.contacts} contacts a year): {n.ben3} risk-adjusted benefits against {n.cost3} total cost over three years",
            "**The gates** — verified resolution ≥ 15%, CSAT at or above the human baseline, zero PII or card-data leaks, Azure cost per resolved contact under $2",
            f"**The caveat** — with every uncertain driver at its unfavourable bound, NPV is {n.stress_dn}: the pilot replaces assumptions with data",
        ],
        side_title="Base case, three years",
        side_items=[f"NPV **{n.npv}** at a 10% discount rate", f"ROI **{n.roi}** · IRR **{n.irr}**",
                    f"Payback **{n.payback} months** from project start ({n.payback_gl} after go-live)", f"Year-3 Azure consumption **{n.acr3}**",
                    f"Cost per resolved contact: AI **{n.ai_all_in}** vs human **{n.human_res}**"],
        takeaway="Start small, measure verified outcomes, expand queue by queue.",
        source="Source: business-case/outputs.json (Base scenario, Azure list prices, illustrative); pilot gates from PRD §10.3.",
        notes=(f"Here is the whole story on one page. The ask is a six-month build and pilot: three months of integration and knowledge preparation, then "
               f"fifty seats on selected queues with a holdout group. For Contoso Home Retail the base case returns {n.npv} of net present value and pays "
               f"back in about {n.payback} months from project start, with {n.acr3} a year of Azure consumption at maturity. We do not ask you to take that "
               f"on faith: the pilot has hard go or no-go gates on verified outcomes. And be clear about the downside: with every uncertain driver at its "
               f"unfavourable bound at once, NPV is {n.stress_dn}. That is why we validate with your data first."))

    # 3 · why now
    d.kpi_cards(
        "Why now: AI can finally resolve, customers are wary, and disclosure rules are live",
        [
            {"value": "14%", "label": "of issues are fully resolved in self-service", "sub": "Gartner customer survey, 2024 [S3]"},
            {"value": "+15%", "label": "issues resolved per hour with generative-AI assistance", "sub": "5,172 support agents, QJE 2025 [S6]"},
            {"value": "80%", "label": "of common service issues resolved autonomously by 2029 (prediction)", "sub": "Gartner, March 2025 [S1]"},
            {"value": "64%", "label": "of customers would rather companies did not use AI for service", "sub": "Gartner survey of 5,728 customers, 2024 [S2]", "color": bad},
            {"value": "1–3%", "label": "of interactions typically reviewed by manual QA", "sub": "Vendor-reported, RingCentral [S8]"},
            {"value": "2 Aug 2026", "label": "EU AI Act Article 50 transparency duties apply", "sub": "European Commission [S11]"},
        ],
        takeaway="So we design for resolution, disclosure and an always-available human — not deflection.",
        source="Sources: Gartner (2024, 2025); Brynjolfsson, Li and Raymond, QJE 2025; RingCentral; European Commission. Predictions and surveys, not guarantees. Full list in the appendix.",
        notes=("Three forces meet. First, AI has moved from assisting to resolving: Gartner predicts autonomous resolution of eighty percent of common service "
               "issues by 2029, and a field study of more than five thousand agents measured fifteen percent more issues resolved per hour. Second, today's "
               "self-service rarely resolves: only fourteen percent of issues are fully resolved there, and manual QA sees one to three percent of "
               "conversations. Third, customers are wary: sixty-four percent would rather companies did not use AI, and EU transparency rules apply from "
               "August 2026. So the winning design resolves, discloses, and always offers a human. These are analyst predictions and surveys, not guarantees."))

    # 4 · vision
    d.pillars(
        "The vision: every conversation answered, resolved and learned from",
        [
            {"title": "Answered", "body": ["Instant, in the customer's language", "Voice and chat share one memory", "Disclosure and a human option built in"],
             "kpi": "Voice turn p95 < 800 ms (design target)"},
            {"title": "Resolved", "body": ["Agents that act: orders, returns, refunds, appointments", "Inside policy limits", "Outcome verified in your systems"],
             "kpi": f"{pct0(A['ai_containment_pct']['base'])} verified resolution at maturity (base case)"},
            {"title": "Learned from", "body": ["Every conversation scored", "Root causes mined from the voice of the customer", "Forecasts that include AI"],
             "kpi": "100% scored, against 1–3% by hand"},
            {"title": "Improved safely", "body": ["Every prompt, policy or knowledge change is tested", "Canary, then promote or roll back", "Audit trail for everything"],
             "kpi": "100% of changes pass the gate"},
        ],
        takeaway="Resolve, not deflect: success is a verified outcome, with a human always one request away.",
        source="Verified resolution = outcome confirmed in the system of record, no repeat contact on the same intent within 7 days (PRD §6.5). Targets from PRD §10.1.",
        notes=("Our vision is that every conversation is answered, resolved and learned from. Answered means instant, in the customer's language, on voice or "
               "chat. Resolved means an agent that can actually act: look up the order, issue the refund, book the pickup, inside policy limits, rather than "
               "a bot that sends a link. Learned from means every conversation is scored, mined for root causes and fed into forecasting. And improved "
               "safely means no prompt, policy or knowledge change reaches a customer without passing an evaluation gate. Our definition of success is "
               "verified resolution: the outcome is confirmed in your system of record, with no repeat contact within seven days."))

    # 5 · the swarm
    d.hub_spoke(
        "A swarm of specialist agents, with a deterministic policy engine in charge of actions",
        {"title": "Resolution agent", "sub": "owns the conversation"},
        [
            {"title": "Greeter and router", "sub": "language · intent · risk"},
            {"title": "Authentication", "sub": "OTP · consent · disclosure"},
            {"title": "Knowledge", "sub": "grounded, cited answers"},
            {"title": "Action + policy engine", "sub": "caps · audit · idempotency"},
            {"title": "Escalation and handoff", "sub": "context package"},
            {"title": "Quality (QA)", "sub": "scores 100% with evidence"},
            {"title": "Insights and WFM", "sub": "VoC · forecast · staffing"},
            {"title": "Simulator", "sub": "synthetic customers"},
        ],
        takeaway="Human + AI continuum: L0 AI-resolved → L1 AI with approval → L2 human with copilot → L3 expert swarm.",
        source="Source: PRD §6.2–6.3; ARCHITECTURE.md §5.",
        notes=("Rather than one giant prompt, Concierge uses a swarm of specialists. The Resolution agent owns the conversation and calls a greeter and router, "
               "an authentication agent, a knowledge agent with citations, and an action agent whose tools run behind a deterministic policy engine. Behind "
               "the front line sit escalation, quality, insights, workforce planning and a simulator that plays difficult customers. The principle is that "
               "models propose and code disposes: refunds, identity and consent are enforced by the policy engine, never by a prompt. Humans are a continuum: "
               "AI-resolved, AI with approval, human with copilot, and expert swarm. Customers can always ask for a person."))

    # 6–7 · two customers: the golden journeys on live screenshots (the text comparison is the fallback and otherwise lives in the appendix)
    journeys_left = ["Damaged sofa, reported in German: the AI answers at once, discloses itself and asks for recording consent",
                     "One-time code to the phone on file (verification level L1)",
                     "Order found; damage-in-transit policy cited from the knowledge base",
                     "Refund inside the €750 autonomous cap; pickup booked; confirmation sent",
                     "Outcome verified in the order system; wrap-up and QA score with evidence"]
    journeys_right = ["Angry customer, legal threat: negative sentiment and legal-threat flag detected on the first turn",
                      "AI tries once, then escalates on the customer's explicit request",
                      "Human sees summary, steps tried and sentiment trajectory before the first word",
                      "Agent Assist suggests a policy-cited goodwill credit within the agent's authority",
                      "Supervisor watches live; wrap-up is pre-filled for one click"]

    def journeys_slide(title_: str) -> None:
        d.two_column(
            title_, "Customer 1 · resolved by the AI in 3 minutes", journeys_left, "Customer 2 · warm handoff to a human, full context", journeys_right,
            takeaway="The same guardrails serve both: resolve what can be resolved, hand over what needs a person.",
            source="Source: PRD §7.1–7.2 (golden journeys GJ-1 and GJ-2); synthetic Contoso Home data.",
            notes=("Two journeys from the demo. On the left, a German-speaking customer reports a damaged sofa. The AI discloses itself, verifies a one-time "
                   "code, finds the order, cites the damage-in-transit policy, issues a refund within the 750-euro cap, books the pickup and confirms, in about "
                   "three minutes and verified in the order system. On the right, an angry customer threatens legal action. The AI tries once, then escalates; "
                   "the human sees the summary, steps tried and sentiment before saying a word, and Agent Assist suggests a policy-cited goodwill credit. Same "
                   "platform, same guardrails, two very different outcomes, both scored automatically afterwards."))

    if have_customers:
        d.screenshot(
            "Customer 1: a damaged sofa, reported in German, is resolved end to end by the AI",
            prepare(chat_img, scratch, markers=[(0.575, 0.345), (0.375, 0.48), (0.575, 0.60), (0.822, 0.09)]),
            caption="Customer widget, German journey: disclosure, one-time code, policy citation, refund executed (synthetic data)",
            callouts=["Replies in the customer's language and cites the damage-in-transit policy [K1]",
                      "Tool chips show each action taken: slot lookup, pickup booking, refund",
                      "The €379 refund is inside the autonomous cap, and is read back and confirmed before it runs",
                      "Verified level L1 after a one-time code (simulated SMS, top right); disclosure and consent came first"],
            takeaway="Acceptance target: end to end in ≤ 3 minutes with no human, and the outcome verified in the order system.",
            source=f"{shot_source}; PRD §7.1, golden journey GJ-1.",
            notes=("This is the first golden journey, captured from the live deployment. A customer writes in German that the sofa arrived damaged. The AI answers in "
                   "German, cites the damage-in-transit policy from the knowledge base, books the pickup and, after the customer confirms, issues the refund of 379 "
                   "euros through a policy-guarded tool. Identity was verified with a one-time code first; the code arrives on a simulated phone because SMS "
                   "delivery is not provisioned. The acceptance target is under three minutes without a human, with the refund verified in the order system. "
                   "Every action is audited and scored afterwards."))
        d.screenshot(
            "Customer 2: an angry legal threat reaches a human who already knows the whole story",
            prepare(console_img, scratch, crop=True, markers=[(0.746, 0.30), (0.945, 0.731), (0.737, 0.598), (0.737, 0.86)]),
            caption="Human-agent console after a warm handoff: context package, risk flags, reply drafts (synthetic data)",
            callouts=["Context package: why the customer is here, risk flags, what the assistant already did, a suggested resolution",
                      "Risk flags from the first turn: angry (−0.89) and legal threat; routed to Escalations at priority 115",
                      "The customer is told a colleague already sees the conversation, so nothing is repeated",
                      "AI-composed reply drafts in different tones; every message still passes the output guard"],
            takeaway="Handoff quality is a KPI: a complete package, a re-ask rate under 5% and a fast first human response (KPI-09).",
            source=f"{shot_source}; PRD §7.2, golden journey GJ-2.",
            notes=("This is the second golden journey. The customer is angry, mentions a lawyer, and has called three times about an installation that never happened. "
                   "Sentiment and a legal-threat flag are raised on the first turn, the AI offers a human, and the contact is routed to the escalations queue with high "
                   "priority. The agent accepts and sees a context package before typing a word, while the customer is told that a colleague can already see the "
                   "conversation. Agent Assist offers reply drafts, and every message passes the output guard. We measure this as escalation quality: package "
                   "completeness, re-ask rate and time to first human response."))
    else:
        journeys_slide("Two customers, one platform: resolved in three minutes, or handed over without repeating a word")

    # 7 · trust model
    d.architecture(
        "Trust is engineered in layers: the model proposes, code disposes, every change is gated",
        [
            {"name": "Identity and consent", "items": [{"title": "AI disclosure first", "sub": "every channel"}, {"title": "OTP / KBA + step-up", "sub": "before account data"},
                                                         {"title": "Recording consent", "sub": "with a decline path"}]},
            {"name": "Policy engine", "items": [{"title": "Tool allow-lists", "sub": "per agent"}, {"title": "Caps · windows · eligibility", "sub": "per action"},
                                                {"title": "Read-back confirmation", "sub": "before writes"}, {"title": "Idempotency + audit", "sub": "append-only"}]},
            {"name": "Guards", "items": [{"title": "PII and card redaction", "sub": "before model and storage"}, {"title": "Prompt Shields", "sub": "user text and documents"},
                                         {"title": "Grounded and cited", "sub": "or 'I don't know'"}, {"title": "Payment hand-off", "sub": "card data never enters"}]},
            {"name": "Release gate", "items": [{"title": "Evaluation harness", "sub": "synthetic customers"}, {"title": "Red-team pack", "sub": "100% must-pass"},
                                               {"title": "Canary + rollback", "sub": "metric guards"}]},
            {"name": "Human oversight", "items": [{"title": "Supervisor take-over", "sub": "whisper · approve"}, {"title": "100% auto-QA", "sub": "evidence-linked"},
                                                  {"title": "Human on request", "sub": "any time"}]},
        ],
        source="Source: PRD §6.4; ARCHITECTURE.md §9–10. A successful prompt injection can embarrass a model; it cannot exceed the policy engine's caps.",
        notes=("Executives ask the same question first: how do we know it is safe? The answer is defence in depth. Identity and consent come first: "
               "disclosure, one-time codes, recording consent with a decline path. Second, the policy engine enforces allow-lists, monetary caps, eligibility "
               "windows, read-back confirmation, idempotency and an append-only audit. Third, guards redact personal and card data, check prompts and "
               "documents for injection attacks, and require grounded, cited answers. Fourth, every change passes an evaluation harness and a red-team pack "
               "before a canary rollout. Finally, supervisors can take over and quality scoring covers every conversation."))

    # 9 · capability map
    n_p = {p_: sum(1 for f_ in FEATURES if f_["prio"] == p_) for p_ in ("P0", "P1", "P2")}
    prio_line = f"{n_p['P0']} P0 features form the MVP, {n_p['P1']} P1 features join in the Beta and {n_p['P2']} P2 feature arrives at GA."
    d.capability_map(
        ("Release 1 scope: all 24 features in five epics are deployed and tested on Azure" if all_deployed
         else "Release 1 scope: 24 features in five epics, from the first greeting to continuous improvement"),
        [{"name": epic, "items": [f"{f_['id']} {spaced_slashes(f_['name'])}" for f_ in feats]} for epic, feats in EPICS.items()],
        takeaway=(f"Verified on the final build: live smoke 21 of 21, evaluation harness 42 of 42, 212 unit/API and 27 browser tests. Priorities: {n_p['P0']}\u00a0P0 (MVP), {n_p['P1']}\u00a0P1 (Beta), {n_p['P2']}\u00a0P2 (GA)."
                  if all_deployed else prio_line),
        source=(f"Source: FEATURES.md (status board and acceptance criteria); REPORT-TEST-AND-DEPLOYMENT.md §1, final build {build_id}." if HAS_STATUS
                else "Source: FEATURES.md (24 features with acceptance criteria)."),
        notes=("This is the Release 1 scope: twenty-four features in five epics. Epic A is the conversational agents: chat, realtime voice, grounded answers, "
               "transactional tools, and identity, consent and disclosure. Epic B covers routing and the human side: smart routing, warm handoff, Agent "
               "Assist and auto wrap-up. Epic C is quality, compliance and insight, including one hundred percent auto-QA. Epic D is operations and LLMOps: "
               "forecasting, supervisor console, the evaluation harness, staged rollout and proactive outreach. Epic E is the platform: multilingual, CRM "
               "integration, security, FinOps, infrastructure as code and the Agent Studio. "
               + ("All twenty-four are deployed and tested on Azure; the evidence is in the appendix. P0 is the MVP, P1 the beta, P2 general availability."
                  if all_deployed else "Each feature has testable acceptance criteria and a tracked status.")))

    # 10 · quality at 100 % (live screenshots of QA, VoC, WFM and the release gate; the pillars are the fallback until screenshots exist)
    qa_total = cat_total["qa_quality"]
    gate_img = shots.pick("ci-gate")
    quality_takeaway = f"Manual QA sees 1–3% of interactions [S8]; auto-QA scores all of them — worth {m(qa_total)} over three years in the base case."
    quality_notes = (f"Quality is where AI changes the economics beyond containment. Manual QA typically samples one to three percent of interactions; auto-QA scores "
                     f"every conversation, human and AI, against your rubric with evidence turns, and analysts calibrate instead of listening. Voice-of-customer "
                     f"analytics clusters topics and flags emerging issues, such as a carrier causing damaged deliveries, within a day rather than weeks. Workforce "
                     f"planning accounts for AI containment, with a what-if slider. Finally, the evaluation harness blocks any release that regresses policy or safety "
                     f"scores. In the base case, quality and learning are worth {m(qa_total)} of risk-adjusted benefit over three years.")
    if have_quality:
        tour = [
            {"image": prepare(qa_img, scratch, crop=True), "heading": "Score every conversation",
             "bullets": ["AI and human conversations scored on a 7-dimension rubric, with evidence turns", "Compliance auto-fail; analysts calibrate (KPI-08: 100% coverage)"]},
            {"image": prepare(voc_img, scratch, crop=True), "heading": "Hear the customer",
             "bullets": ["Emerging issue found: damage on arrival at 7.7× baseline, 82% from one carrier", "Topic clusters and Pareto by volume and cost (KPI-17)"]},
            {"image": prepare(wfm_img, scratch, crop=True), "heading": "Plan the work",
             "bullets": ["Interval forecast and Erlang-C staffing with an AI-containment what-if", "Schedule checked by simulation: 83% service level against an 80% target (KPI-15)"]},
        ]
        if gate_img:
            tour.append({"image": prepare(gate_img, scratch, crop=True), "heading": "Release safely",
                         "bullets": ["A deliberately broken prompt is blocked: policy 0.98 against a required 1.00, 2 scenarios regressed", "Synthetic customers and a red-team pack gate every change (KPI-16)"]})
        d.triptych(
            ("Quality at 100%: every conversation is scored, mined and planned for, and every release is gated" if gate_img
             else "Quality at 100%: every conversation is scored, mined for root causes and planned for"),
            tour,
            takeaway=quality_takeaway,
            source=f"{shot_source}; synthetic history. QA benefit from outputs.json (base, risk-adjusted). Features CC-10, CC-12, CC-14" + (", CC-16." if gate_img else "."),
            notes=quality_notes)
    else:
        d.pillars(
            "Quality at 100%: every conversation is scored, mined, planned for and tested",
            [
                {"title": "Score 100%", "body": ["Rubric scores with evidence turns", "Calibrated against human QA", "Coaching and prompt fixes"], "kpi": "KPI-08: 100% coverage, ≥ 85% agreement"},
                {"title": "Hear the customer", "body": ["Topics and root causes clustered", "Emerging-issue alerts, e.g. one carrier's damage claims", "Evidence one click away"], "kpi": "KPI-17: issue detected in < 24 h (target)"},
                {"title": "Plan the work", "body": ["Interval forecast per queue", "Erlang-C staffing including AI containment", "What-if: containment against headcount"], "kpi": "KPI-15: daily forecast error ≤ 8% (target)"},
                {"title": "Release safely", "body": ["Synthetic customers, incl. angry and prompt-injecting", "Regression and red-team gate", "Canary and rollback"], "kpi": "KPI-16: 100% of releases gated"},
            ],
            takeaway=quality_takeaway,
            source=f"Source: PRD §6, §10; QA and quality benefit from outputs.json (base, risk-adjusted: {m(qa_total)} over 3 years). Features CC-10, 12, 14, 16, 17.",
            notes=quality_notes)

    # 10b · the same product in a second language: live screenshots of the Polish UI (deck/assets/screens-pl/, captured on the deployed app)
    pl_dir = HERE / "assets" / "screens-pl"
    pl_widget, pl_console, pl_voc = (pl_dir / n_ for n_ in ("01-customer-widget-resolved.png", "02-agent-console-handoff.png", "05-voc-insights.png"))
    if all(p_.exists() for p_ in (pl_widget, pl_console, pl_voc)):
        from PIL import Image

        widget_crop = scratch / "pl-widget.png"  # the widget sits in the middle of a 1600x900 capture: keep the chat and the simulated phone, drop the empty margins
        Image.open(pl_widget).convert("RGB").crop((300, 95, 1300, 735)).save(widget_crop)
        d.triptych(
            "Polish is a first-class language: the customer, the agent and the analyst all work in Polish",
            [
                {"image": widget_crop, "heading": "Customer widget",
                 "bullets": ["Formal Polish, AI disclosure first; the refund of 1 599,00 zł is read back and confirmed", "Real tool calls on Azure; caps checked in EUR at a fixed demo rate (1 EUR = 4.30 PLN)"]},
                {"image": prepare(pl_console, scratch, crop=True), "heading": "Human-agent console",
                 "bullets": ["Legal threat caught with and without diacritics; warm handoff with a Polish context package", "PESEL, NIP, REGON and bank-account numbers redacted with checksum validation"]},
                {"image": prepare(pl_voc, scratch, crop=True), "heading": "Voice of customer",
                 "bullets": ["Topic summaries and the emerging-issue alert in Polish", "Queues in Europe/Warsaw time with Polish public holidays"]},
            ],
            takeaway="Evaluated, not just translated: a 31-scenario Polish pack scores 93.5% on the real model with policy and safety at 1.00, and the live smoke test passes 31 of 31 checks.",
            source=f"{shot_source}, Polish interface; REPORT-TEST-AND-DEPLOYMENT.md §14. Legal wording is demo content, not legal advice.",
            notes=("Polish is available end to end in the reference implementation, not only as translated labels. The customer chats in formal Polish; the assistant discloses that it is an AI, "
                   "reads the refund back in zloty and asks for confirmation before it acts. The agent console shows the same warm handoff with a Polish context package, and the voice-of-customer "
                   "analytics are summarised in Polish. Behind it are fifty Polish knowledge articles, redaction of Polish personal identifiers with checksum validation, and a thirty-one-scenario "
                   "evaluation pack: ninety-three percent on the real model, with policy and safety at one hundred percent. The euro-based caps use a fixed demo exchange rate, and the legal wording "
                   "is demo content, not legal advice."))

    # 11 · Azure reference architecture
    d.architecture(
        "Azure reference architecture: voice and chat on one policy-guarded core",
        [
            {"name": "Channels and voice path", "items": [{"title": "Web and app chat", "sub": "widget · webhooks"}, {"title": "Browser voice", "sub": "WebSocket · 24 kHz audio"},
                                                           {"title": "Phone", "sub": "SIP trunk or SBC → Realtime SIP"}, {"title": "Human handoff", "sub": "SIP REFER · queue API"}]},
            {"name": "Conversation plane", "items": [{"title": "Agent swarm runtime", "sub": "Container Apps"}, {"title": "Policy engine", "sub": "tool gateway · audit"},
                                                      {"title": "Guard layer", "sub": "PII · Prompt Shields"}, {"title": "Routing and consoles", "sub": "agent · supervisor"}]},
            {"name": "AI services", "items": [{"title": "Azure OpenAI Realtime", "sub": "2.1 and 2.1-mini"}, {"title": "GPT-5.4 family", "sub": "chat · reasoning · nano"},
                                              {"title": "Speech · Language", "sub": "Content Safety"}, {"title": "AI Search", "sub": "hybrid + semantic"}]},
            {"name": "Data and analytics", "items": [{"title": "Cosmos DB", "sub": "state · memory · audit"}, {"title": "Blob / ADLS", "sub": "recordings · transcripts"},
                                                      {"title": "Event Hubs → Fabric", "sub": "real-time intelligence"}, {"title": "OneLake · Power BI", "sub": "CX · QA · WFM views"}]},
            {"name": "Integration", "items": [{"title": "API Management", "sub": "gateway · limits"}, {"title": "Dynamics 365 · Dataverse", "sub": "CRM · cases"},
                                              {"title": "Salesforce · ServiceNow", "sub": "connectors"}, {"title": "CCaaS · telephony", "sub": "Genesys · NICE · Teams"}]},
        ],
        side={"name": "Cross-cutting", "items": ["Entra ID · External ID", "Key Vault · Purview · Defender", "Monitor · App Insights", "Bicep · azd · policy"]},
        source="Source: ARCHITECTURE.md §4–7; Microsoft Learn (Realtime API via SIP). Voice design budget p95 < 800 ms, measured in the pilot. PSTN is not provisioned in the demo.",
        notes=("This is the Azure reference architecture. Customers arrive by browser, app, chat, messaging or phone. For phone, a SIP trunk or session border "
               "controller routes calls straight into the Azure OpenAI Realtime endpoint, which calls our webhook; there is no media server of our own. The "
               "conversation plane on Container Apps runs the agent swarm, the policy engine and the guard layer. AI services are Azure OpenAI in Foundry, "
               "Speech, Language, Content Safety and AI Search; state and audit live in Cosmos DB, recordings in Blob storage, and events flow through Event "
               "Hubs into Fabric. Connectors reach Dynamics, Salesforce, ServiceNow or your contact-center suite through API Management."))

    # 11 · responsible AI, security, compliance
    d.table(
        "Responsible AI by design: each obligation maps to a tested control, not a policy slide",
        ["Topic", "Rule or expectation", "Concierge control"],
        [
            ["AI disclosure", "EU AI Act Art. 50: people must be told they are interacting with an AI system, from 2 Aug 2026 [S11][S26]", "Disclosure is the first turn on every channel; logged and tested per channel"],
            ["Emotion inference", "AI Act Art. 5(1)(f): no emotion inference from biometric data in the workplace [S26][S28][S29]", "Coaching and QA use text signals only; no acoustic emotion scoring of staff"],
            ["Worker monitoring", "AI Act Annex III: AI that evaluates workers can be high-risk [S26]", "Calibrated, evidence-linked QA with human review; works-council consultation"],
            ["Personal data", "GDPR: lawful basis, minimisation, retention, access and erasure [S27]", "Redaction, allow-listed context, retention classes, EU data zone, access audit"],
            ["Payments", "PCI DSS: keep card data out of scope [S13]", "Card data never reaches the model, logs or transcripts: keypad or hosted-page hand-off"],
            ["Recording consent", "Varies by country and US state", "Consent captured with text version and time; decline honoured downstream"],
            ["Outbound AI voices", "FCC 24-17: AI voices need prior express consent under the TCPA [S12]", "Consent gating, quiet hours, suppression lists (simulated in the demo)"],
            ["Accessibility", "WCAG 2.1 AA [S25]", "Keyboard and screen-reader support, captions, transcripts"],
        ],
        col_weights=[1.25, 3.4, 3.6], align=["left", "left", "left"],
        takeaway="Security: keyless managed identities, least-privilege roles, private endpoints in the target, STRIDE threat model.",
        source="Design checklist, not legal advice: validate with counsel per market. Certifications belong to the operator and the underlying Azure services. PRD §16; ARCHITECTURE.md §10.",
        notes=("Each obligation maps to a control we can test, not a policy slide. The EU AI Act's transparency rule means the AI discloses itself first on every "
               "channel. Because the Act prohibits inferring employees' emotions from biometric data, coaching and QA use text signals only. GDPR drives "
               "minimisation, redaction, retention classes and EU data-zone processing. Card data never reaches the model, logs or transcripts: payment is "
               "handed off by keypad or hosted page, which shrinks PCI scope. Recording consent is captured with a decline path. This is a design checklist, "
               "not legal advice; your counsel should validate each market before go-live."))

    # 13 · ROI A — where the value comes from, and when it turns into cash
    cat_order = ["ai_containment", "aht_reduction", "qa_quality", "attrition", "abandonment_csat_retention", "peak_resilience", "compliance_risk", "multilingual"]
    short = {"ai_containment": "AI containment", "aht_reduction": "AHT reduction", "qa_quality": "QA and quality", "attrition": "Attrition and hiring",
             "abandonment_csat_retention": "Abandonment, CSAT, retention", "peak_resilience": "Peak resilience", "compliance_risk": "Compliance risk",
             "multilingual": "Multilingual"}
    other_keys = ["peak_resilience", "compliance_risk", "multilingual"]
    conf = BEN["confidence_factors"]
    by_year = BEN["total_by_year"]
    cum = [x / 1e6 for x in R["cumulative"]]
    benefit_series = {short[c]: [BY_CAT[c][i] / 1e6 for i in (1, 2, 3)] for c in cat_order if c not in other_keys}
    benefit_series["Other: peak, compliance, multilingual"] = [sum(BY_CAT[c][i] for c in other_keys) / 1e6 for i in (1, 2, 3)]
    pal = d.t.palette
    d.dual_chart(
        f"Benefits ramp from {m(by_year[1])} to {m(by_year[3])} a year, and cumulative net benefit turns positive in Year 1",
        left=dict(heading="Risk-adjusted benefits by category, $M per year", categories=[f"Year {i} · {m(by_year[i])}" for i in (1, 2, 3)], series=benefit_series,
                  kind="stacked", number_format='$#,##0"M"', legend=True, labels=False, colors=[pal[0], pal[1], pal[2], pal[3], pal[4], pal[7]]),
        right=dict(heading="Cumulative net benefit at year-end, $M", categories=["Year 0 (build + pilot)", "Year 1", "Year 2", "Year 3"],
                   series={"Cumulative net benefit": cum}, kind="column", number_format='$#,##0.0"M";-$#,##0.0"M"',
                   point_colors=[bad if v < 0 else d.t.good for v in cum]),
        takeaway=f"Base case: NPV {n.npv} · ROI {n.roi} · IRR {n.irr} · payback {n.payback} months from project start ({n.payback_gl} after go-live).",
        source=(f"Source: business-case/outputs.json, Base scenario. Benefits are risk-adjusted (confidence {min(conf.values()):.1f}–{max(conf.values()):.1f}) and net of all costs on the right; "
                "year totals in the axis labels. Illustrative, validate with customer data."),
        notes=(f"Here is where the value comes from, risk-adjusted. Benefits ramp from {m(by_year[1])} in Year 1 to {m(by_year[3])} in Year 3, following adoption: "
               f"{n.ramp[0]} of contacts AI-first in Year 1, {n.ramp[1]} in Year 2, {n.ramp[2]} in Year 3. AI containment is {share(cat_total['ai_containment'] / BEN_TOT)} of "
               f"the total and handle-time reduction another {share(cat_total['aht_reduction'] / BEN_TOT)}. Every category carries a confidence factor between "
               f"{min(conf.values()):.1f} and {max(conf.values()):.1f}. On the right, the up-front investment of {n.y0} is recovered during Year 1: cumulative net benefit "
               f"turns positive after {n.payback} months from project start, {n.payback_gl} after go-live, and reaches {n.cum3} by Year 3. Eighty percent of loaded cost "
               f"is assumed cashable; we flag that for validation."))

    # 14 · ROI B — what moves NPV, and the unit economics a sceptical CFO can audit
    sens = {s_["assumption"]: s_ for s_ in B["sensitivity"]}

    def drv(key: str, label: str) -> tuple[str, float, float]:
        return label, sens[key]["npv_at_low"] / 1e6, sens[key]["npv_at_high"] / 1e6

    def lh(key: str, f=lambda v: f"{v:g}") -> str:
        return f"{f(A[key]['low'])}–{f(A[key]['high'])}"

    # (assumption key, short label for the main slide, label with the tested range for the appendix)
    DRIVERS = [
        ("ai_containment_pct", "AI verified resolution", f"AI verified resolution ({lh('ai_containment_pct', lambda v: f'{v * 100:.0f}%')})"),
        ("agents", "Agents in scope", f"Agents in scope ({lh('agents', lambda v: f'{v:,.0f}')})"),
        ("loaded_cost_per_agent_usd", "Loaded cost per agent", f"Loaded cost per agent ({lh('loaded_cost_per_agent_usd', lambda v: f'${v / 1e3:.0f}K')})"),
        ("aht_reduction_pct", "AHT reduction", f"AHT reduction ({lh('aht_reduction_pct', lambda v: f'{v * 100:.0f}%')})"),
        ("variable_cost_share", "Cashable share of cost", f"Cashable share of cost ({lh('variable_cost_share', lambda v: f'{v * 100:.0f}%')})"),
        ("adoption_ramp", "Adoption ramp", f"Adoption ramp (Year 3: {A['adoption_ramp']['low'][2] * 100:.0f}–{A['adoption_ramp']['high'][2] * 100:.0f}%)"),
        ("tier1_aht_factor", "Handle time of contained contacts", f"Handle time of contained contacts ({lh('tier1_aht_factor', lambda v: f'{v:.2f}×')} average)"),
        ("confidence_containment", "Confidence in containment", f"Confidence in containment savings ({lh('confidence_containment', lambda v: f'{v:.2f}')})"),
        ("azure_usage_multiplier", "Azure consumption", f"Azure consumption ({lh('azure_usage_multiplier', lambda v: f'{v:g}×')})"),
    ]
    drivers = [drv(key, full) for key, _, full in DRIVERS]
    ranked = sorted(DRIVERS, key=lambda t: abs(sens[t[0]]["npv_at_high"] - sens[t[0]]["npv_at_low"]), reverse=True)
    azure_row = [t for t in ranked if t[0] == "azure_usage_multiplier"]
    if ranked[-1][0] != "azure_usage_multiplier" or [t[0] for t in ranked[:4]] != ["ai_containment_pct", "agents", "loaded_cost_per_agent_usd", "aht_reduction_pct"]:
        d._warn("sensitivity ranking changed: the wording about the biggest and smallest NPV drivers (slides ROI-B and the full tornado) must be updated")
    shown = [t for t in ranked if t[0] != "azure_usage_multiplier"][:6] + azure_row  # the Azure row is always shown: the CFO's first question
    base_npv_m = R["npv"] / 1e6
    swing_lo = [min(sens[t[0]]["npv_at_low"], sens[t[0]]["npv_at_high"]) / 1e6 - base_npv_m for t in shown]
    swing_hi = [max(sens[t[0]]["npv_at_low"], sens[t[0]]["npv_at_high"]) / 1e6 - base_npv_m for t in shown]
    worst_single_npv = min(min(sens[key]["npv_at_low"], sens[key]["npv_at_high"]) for key, _, _ in DRIVERS)
    ai_cost_all_in = {"Human baseline": UE["human_cost_per_resolved_contact_usd"], "AI, conservative": CO["unit_economics"]["all_in_ai_cost_per_resolved_contact_usd"],
                      "AI, base": UE["all_in_ai_cost_per_resolved_contact_usd"], "AI, upside": UP["unit_economics"]["all_in_ai_cost_per_resolved_contact_usd"]}
    d.dual_chart(
        (f"Varied one at a time, no driver turns NPV negative (worst: {m(worst_single_npv)}), and AI costs {n.ratio} less per resolved contact" if worst_single_npv > 0
         else f"Resolution, headcount and cost per agent move NPV most; AI costs {n.ratio} less per resolved contact"),
        left=dict(heading=f"Change in three-year NPV versus the {n.npv} base, $M", categories=[t[1] for t in shown],
                  series={"Downside": swing_lo, "Upside": swing_hi}, kind="stacked_bar", number_format="+0.0;-0.0", legend=True, labels=True,
                  colors=[bad, d.t.good], tornado=True, gap_width=45),
        right=dict(heading="Cost per verified-resolved contact, $ (Year 3)", categories=list(ai_cost_all_in), series={"Cost per resolved contact": list(ai_cost_all_in.values())},
                   kind="bar", number_format="$0.00", point_colors=[d.t.muted, d.t.accent, d.t.accent, d.t.accent]),
        takeaway=f"Scenario NPV: conservative {n.npv_c} · base {n.npv} · upside {n.npv_u}. Stacked worst case, every driver at its bound: {n.stress_dn}.",
        source="Source: business-case/outputs.json; ranges for all nine drivers in the appendix. All-in AI cost includes Azure, communications, licences, AI operations, support and amortised one-off costs.",
        notes=(f"How sure are we? On the left, each driver is moved alone between its low and high bound. The biggest swings come from business assumptions of ours: the verified "
               f"resolution rate, agents in scope, loaded cost per agent and handle-time reduction. Azure consumption matters least: from 0.7 to 1.5 times, NPV stays between "
               f"{m(sens['azure_usage_multiplier']['npv_at_high'], 0)} and {m(sens['azure_usage_multiplier']['npv_at_low'], 0)}. With every uncertain driver at its worst bound at "
               f"once, NPV is {n.stress_dn}: a stress test, not a forecast. On the right, a verified-resolved contact costs {n.ai_all_in} all-in with AI against {n.human_res} "
               f"with a human, grossed up for 12% repeat contacts."))

    # 16 · adoption path
    d.timeline(
        "Adoption path: validate, pilot with a holdout, then expand queue by queue",
        [
            {"name": "Discover", "when": "Weeks 0–4", "items": ["Validate volumes, cost per contact, Tier-1 share", "Pick pilot queues and the telephony path", "Re-run the business case on your data"]},
            {"name": "Build and integrate", "when": "Months 1–3", "items": ["Connectors, knowledge, policies, tools", "Evaluation set and security review", "SIP or CCaaS integration"]},
            {"name": "Pilot", "when": "Months 4–6", "items": ["50 seats, selected queues, holdout group", "Agent Assist and 100% QA on", "Go/no-go gates on verified outcomes"]},
            {"name": "Expand", "when": "Year 1", "items": [f"AI-first share ≈ {n.ramp[0]} of contacts", "Queue by queue, weekly releases", "Second region for voice"]},
            {"name": "Scale", "when": "Years 2–3", "items": [f"AI-first share {n.ramp[1]} → {n.ramp[2]}", "Analytics at scale, next business unit", f"≈ {n.fte} FTE-equivalents released (risk-adjusted)"]},
        ],
        takeaway="Each step is gated on verified outcomes, so exposure grows only as proof does.",
        source="Source: PRD §13–14; adoption ramp and FTE-equivalents from outputs.json. Capacity is released through attrition, hiring freezes and redeployment, not layoffs.",
        notes=(f"Adoption is staged and gated. Discovery takes three to four weeks to validate volumes, cost per contact, the Tier-1 share and the telephony path. "
               f"Three months of build and integration follow: connectors, knowledge ingestion, policies and tools, the evaluation set and the security review. "
               f"Then a three-month pilot with fifty seats and a holdout on selected queues. If the gates are met, we expand queue by queue: the AI-first share "
               f"grows from {n.ramp[0]} in Year 1 to {n.ramp[1]} and then {n.ramp[2]}, with weekly releases through the evaluation gate. Exposure grows only as proof does."))

    # 17 · risks
    d.table(
        "The top risks are known, and each has a tested control",
        ["Risk", "L / I", "Mitigation (features)"],
        [
            ["Hallucinated facts or policy", "M / H", "Citations required, groundedness check, 'don't know → escalate', evaluation gate with seeded fabrications, 100% QA (CC-03, 10, 16)"],
            ["Prompt injection or jailbreak: user text, documents, tool results", "M / H", "Prompt Shields, untrusted-content handling, tool allow-lists, policy engine outside the model, red-team pack (CC-11, 04, 16)"],
            ["PII or card-data leakage", "L / H", "Redaction before model and storage, payment hand-off, role-based access and audit, private endpoints in the target (CC-05, 11, 21)"],
            ["Wrong financial action", "L / H", "Caps and approvals, idempotency, read-back confirmation, step-up authentication, anomaly alerts (CC-04, 05, 15)"],
            ["Customer rejection; false containment", "M / H", "Disclosure, human on request, holdout and CSAT gates, containment gap published next to verified resolution (CC-05, 06, 13)"],
            ["Regulatory non-compliance: AI Act, GDPR, TCPA, PCI, recording laws", "M / H", "Controls mapped per market, DPIA, consent evidence, EU data zone, counsel review (CC-05, 11, 18, 21)"],
            ["Platform volatility: ACS retirement, model versions", "H / M", "Provider-neutral adapters, pinned model versions, harness re-run on every model swap (CC-16, 17)"],
            ["Voice quality, latency and realtime quota", "M / H", "In-region realtime over SIP, fallback pipeline, per-language evaluation, quota plan, p95 alerts (CC-02, 19, 22)"],
        ],
        col_weights=[3.0, 0.7, 6.4], align=["left", "center", "left"],
        source="L = likelihood, I = impact (H/M/L). Eight of 17 risks in PRD §15 shown; the customer-rejection case follows Klarna's published 2025 experience [S10].",
        notes=("We list seventeen risks in the product requirements document; these are the ones executives ask about. Hallucination is handled with citations, "
               "groundedness checks and an explicit 'I don't know, escalate'. Prompt injection is handled by Prompt Shields plus a policy engine that sits "
               "outside the model, so even a successful attack cannot exceed the caps. Data leakage is handled by redaction and the payment hand-off. Customer "
               "rejection is real, since sixty-four percent prefer no AI, so we disclose, always offer a human and hold CSAT as a gate. Platform volatility, "
               "such as the retirement of Azure Communication Services, is handled by provider-neutral adapters."))

    # 18 · KPIs
    d.table(
        "KPIs we hold ourselves to: measured on verified outcomes, with the gap published",
        ["KPI", "What it measures", "Target"],
        [
            ["Verified AI resolution (KPI-01)", "AI-first contacts closed with a verified outcome and no 7-day re-contact", "≥ 15% in the pilot; 30% at maturity (base case)"],
            ["Containment gap (KPI-02)", "Containment minus verified resolution: false containment", "≤ 5 points, published weekly"],
            ["Cost per resolved contact (KPI-07)", "Loaded human cost plus metered Azure cost, AI against human", f"AI {n.ai_all_in} vs human {n.human_res} (Year 3); pilot gate: Azure cost < $2"],
            ["Handle time (KPI-03)", "Talk or chat time plus wrap-up on human-handled contacts", "−12% on assisted contacts"],
            ["CSAT (KPI-06)", "Surveyed and predicted satisfaction", "AI-resolved CSAT at or above the human baseline"],
            ["QA coverage (KPI-08)", "Share of conversations scored; agreement with human QA", "100%; ≥ 85% within ±1 band"],
            ["Escalation quality (KPI-09)", "Handoffs with a complete context package; customer re-ask rate", "≥ 90% complete; re-ask < 5%"],
            ["Voice turn latency (KPI-10)", "End of customer speech to first agent audio", "p95 < 800 ms on the production path"],
            ["Safety and compliance (KPI-12)", "Disclosure rate; PII or card leaks; policy-violating tool calls; red-team pass", "100% · 0 · 0 · 100%"],
        ],
        col_weights=[2.5, 4.4, 3.4], align=["left", "left", "left"],
        source="Source: PRD §10.1 and §10.3 (targets are illustrative; baselines to be replaced with customer data); cost figures from outputs.json.",
        notes=("These are the numbers we will hold ourselves to. The first is verified resolution: AI-first contacts closed with the outcome confirmed in your "
               "system of record and no repeat within seven days. The gap between containment and verified resolution is published, never hidden. Cost per "
               "resolved contact, handle time, CSAT, QA coverage and agreement, escalation quality and voice latency follow, with compliance counters that "
               "must be zero or one hundred percent. In the pilot, a holdout group keeps humans first so that CSAT, handle time and cost are compared like "
               "for like. Targets are illustrative; we replace baselines with your data."))

    # 19 · the ask
    d.big_statement(
        "The ask: a six-month build and pilot, with hard gates, decided on your data",
        "Approve a 6-month build and pilot — 3 months to integrate, 3 months with 50 seats — and scale only if the gates are met.",
        sub=f"Base-case up-front investment {n.y0} (implementation, change management, contingency, pilot consumption). Decision requested this quarter.",
        bullets=[
            "**Sponsor and reviewers:** COO as sponsor; CFO and CISO review the gates",
            "**Your data, in 30 days:** volumes by queue and channel, real cost per contact, handle time, attrition, QA coverage, abandonment, overflow",
            "**Then:** validated business case → pilot queues → telephony path (SIP trunk, Teams Phone, Dynamics 365 or existing CCaaS)",
            "**Gates at month 6:** verified resolution, CSAT, safety and cost per resolved contact, on pilot volumes",
        ],
        notes=(f"The ask is a decision on a six-month build and pilot. For the base case, the up-front investment is {n.y0}, covering implementation, change "
               f"management, contingency and pilot consumption. We need an executive sponsor in operations, the CFO and CISO as gate reviewers, and a data "
               f"request: contact volumes by queue and channel, real cost per contact, handle-time and wrap-up data, attrition, QA coverage, abandonment and "
               f"overflow. In the next thirty days we validate the business case with your numbers, select pilot queues and decide the telephony path. Scaling "
               f"happens only if the pilot gates on verified resolution, CSAT, safety and cost are met."))

    # ================================================== AZURE OPPORTUNITY ===============================================
    d.section(
        "Azure opportunity", "For Microsoft and partner leadership — skip for customer-only audiences", number="02",
        notes=("This section is for Microsoft and partner leadership; skip it for customer-only audiences. It sizes the Azure consumption the solution generates, "
               "built bottom-up from list prices, by seat tier, and shows how a pilot lands and expands. The figures are modelled, not forecasts or commitments, "
               "and they carry the same assumptions as the customer business case. Communications are treated as a customer cost outside Azure by default, "
               "because Azure Communication Services is being retired as a standalone offering. Nothing here implies a Microsoft roadmap commitment, and every "
               f"number traces to an Azure list price retrieved on {PRICE_LONG}."))
    d.set_section("Azure opportunity · ACR")

    fam = ACR["by_family"]
    groups = {
        "Realtime audio (Azure OpenAI)": ("openai_realtime",), "Chat, reasoning, embeddings": ("openai_text",), "Speech (STT / TTS)": ("speech",),
        "AI Search": ("ai_search",), "Safety and language": ("content_safety", "language"), "Data and analytics": ("analytics", "cosmos", "storage"),
        "Platform": ("compute", "networking", "monitoring_security"),
    }
    top3 = FAM_Y3["openai_realtime"] + FAM_Y3["openai_text"] + FAM_Y3["speech"]
    seats = f"{A['agents']['base']:,.0f}"
    d.chart(
        f"Bottom-up, one {seats}-seat customer consumes {n.acr3} of Azure a year by Year 3",
        [f"Year {i}{' (pilot)' if i == 0 else ''} · {m(ACR['by_year'][i], 2)}" for i in range(4)],
        {g: [sum(fam[k_][i] for k_ in keys) / 1e6 for i in range(4)] for g, keys in groups.items()},
        kind="stacked", number_format='$#,##0.0"M"', labels=False,
        commentary=[
            f"Year 3 total **{n.acr3}**; AI models and services are **{n.ai_share}**",
            f"Largest lines: realtime audio **{kk(FAM_Y3['openai_realtime'])}**, chat and reasoning tokens **{kk(FAM_Y3['openai_text'])}**, streaming speech-to-text **{kk(FAM_Y3['speech'])}** ({share(top3 / ACR['run_rate_year3'])} together)",
            "Each line is units × Azure list price; every unit price traces to an API row",
            f"Communications ({n.comms3} in Year 3) are billed outside Azure by default",
        ],
        commentary_title="Year 3 at a glance",
        source=f"Source: business-case/outputs.json (ACR, Base); Azure Retail Prices API retrieved {PRICE_SHORT}, swedencentral, USD, pay-as-you-go, no EA discount. Modelled, not a forecast.",
        notes=(f"This is the bottom-up consumption for one {seats}-seat customer. Each line is units times Azure list price: for example realtime audio tokens per minute "
               f"multiplied by AI voice minutes and the model mix. The pilot year is {kk(ACR['by_year'][0])}; Year 1 is {n.acr_y[1]}; Year 2 {n.acr_y[2]}; Year 3 {n.acr_y[3]}. "
               f"The three biggest families, realtime audio, chat and reasoning tokens, and streaming speech-to-text for human-handled calls, are together "
               f"{share(top3 / ACR['run_rate_year3'])} of Year 3. AI models and services are {n.ai_share} of the total. Prices come from the Azure Retail Prices API, "
               f"retrieved {PRICE_LONG}, Sweden Central, pay-as-you-go, with no enterprise discount."))

    def usd_auto(x: float) -> str:
        return m(x, 2) if x >= 1e6 else kk(x)

    tiers_slide = d.table(
        f"Consumption scales with seats: {kk(TIERS[0]['annual_acr_usd'])} for a pilot to {m(TIERS[3]['annual_acr_usd'])} for 10,000 seats",
        ["Tier", "Seats", "Contacts / year", "Azure / year", "$ per seat-month", "Azure $ per AI-resolved contact", "Peak concurrent voice", "Regions", "Comms outside Azure / year"],
        [[t["name"], f"{t['seats']:,.0f}", f"{t['contacts_per_year'] / 1e6:,.1f}M", usd_auto(t["annual_acr_usd"]), f"${t['acr_per_seat_per_month_usd']:,.0f}",
          f"${t['azure_cost_per_ai_resolved_contact_usd']:.2f}", f"{t['sizing']['peak_concurrent_voice_sessions']:,.0f}", str(t["sizing"]["regions"]),
          usd_auto(t["communications_outside_azure_usd"])] for t in TIERS],
        col_weights=[2.7, 0.8, 1.1, 1.2, 1.1, 1.6, 1.2, 0.95, 1.5], align=["left", "right", "right", "right", "right", "right", "right", "right", "right"], highlight_rows=[2],
        takeaway=(f"Price per seat falls from ${TIERS[0]['acr_per_seat_per_month_usd']:.0f} to ${TIERS[3]['acr_per_seat_per_month_usd']:.0f} a month, and Azure cost per AI-resolved contact from "
                  f"${TIERS[0]['azure_cost_per_ai_resolved_contact_usd']:.2f} to ${TIERS[3]['azure_cost_per_ai_resolved_contact_usd']:.2f}, as fixed platform items amortise."),
        source="Source: business-case/outputs.json (ACR by seat tier, steady state, Base). Peak concurrent voice sessions drive realtime quota requests per region. Modelled, not a forecast.",
        notes=(f"Consumption by seat tier at steady state. A 50-seat pilot consumes about {kk(TIERS[0]['annual_acr_usd'])}, a 500-seat department {m(TIERS[1]['annual_acr_usd'], 2)}, "
               f"our 1,500-seat reference customer {m(TIERS[2]['annual_acr_usd'], 2)}, and a 10,000-seat enterprise {m(TIERS[3]['annual_acr_usd'])} a year. Per seat per month the "
               f"price falls from ${TIERS[0]['acr_per_seat_per_month_usd']:.0f} to ${TIERS[3]['acr_per_seat_per_month_usd']:.0f} because fixed platform items, such as search replicas, "
               f"Fabric capacity, Front Door and observability, amortise. Capacity follows: roughly {TIERS[2]['sizing']['peak_concurrent_voice_sessions']:.0f} concurrent voice sessions "
               f"at the reference peak and about {TIERS[3]['sizing']['peak_concurrent_voice_sessions']:,.0f} at enterprise scale, which drives realtime quota requests per region."))
    d.stretch_table(tiers_slide)

    v3 = B["volumes"]["ai_resolved_contacts"][3] / 1e6
    d.kpi_cards(
        "ACR is AI-dominated and robust: it does not depend on the AI succeeding",
        [
            {"value": n.voice_min, "label": "Azure cost per AI voice minute", "sub": f"{n.voice_min_plat} incl. telephony legs at proxy rates"},
            {"value": n.azure_per_res, "label": "Azure cost per AI-resolved contact", "sub": f"all Azure consumption ÷ {v3:.2f}M AI-resolved contacts (Year 3)"},
            {"value": n.ai_share, "label": "of Year-3 ACR is AI models and services", "sub": f"{m(AI_Y3, 2)} of {n.acr3}"},
            {"value": n.pull, "label": "pull-through per $1 of AI spend", "sub": "data, analytics, compute, networking, security"},
            {"value": f"${CO['acr']['run_rate_year3'] / 1e6:.2f}–{UP['acr']['run_rate_year3'] / 1e6:.2f}M", "label": "Year-3 ACR across the three scenarios", "sub": "better containment moves spend from STT to realtime"},
            {"value": n.comms3, "label": "communications outside Azure (Year 3)", "sub": "SIP / CPaaS and messaging; ACS retiring 30 Sep 2028 [S16]"},
        ],
        takeaway="Pull-through beyond AI is small in this slice; the larger attach sits in the customer's data estate and business applications, not quantified here.",
        source="Source: business-case/outputs.json (unit economics, ACR, pull-through; Conservative, Base, Upside). Pull-through = Azure-billed spend outside AI models and services per $1 of AI spend.",
        notes=(f"Three points for Microsoft and partner leaders. First, unit costs: Azure spends about {n.voice_min} per AI voice minute and {n.azure_per_res} per AI-resolved "
               f"contact. Second, ACR is dominated by AI models and services, {n.ai_share}; the pull-through to data, compute, networking and security is {n.pull} per dollar "
               f"of AI, which is small in this slice, while the larger attach sits in the customer's data estate and business applications, which we have not quantified. "
               f"Third, ACR barely moves with AI success: {m(CO['acr']['run_rate_year3'], 2)}, {n.acr3} and {m(UP['acr']['run_rate_year3'], 2)} across scenarios, because higher "
               f"containment shifts spend from transcription of human calls to realtime AI minutes."))

    d.timeline(
        f"The pilot lands at {kk(ACR['by_year'][0])} and expands queue by queue to {n.acr3} a year",
        [
            {"name": "Land", "when": "Year 0 · 6 months", "items": ["50-seat pilot in one region", f"Azure ≈ {kk(ACR['by_year'][0])}", "Foundry models, Speech, Cosmos DB, Container Apps"]},
            {"name": "Expand", "when": "Year 1", "items": [f"AI-first ≈ {n.ramp[0]} of contacts", f"ACR {n.acr_y[1]}", "Agent Assist and 100% QA; second region, Search, Fabric"]},
            {"name": "Scale", "when": "Year 2", "items": [f"AI-first ≈ {n.ramp[1]}", f"ACR {n.acr_y[2]}", "Multi-region voice; analytics at scale"]},
            {"name": "Steady state", "when": "Year 3", "items": [f"AI-first ≈ {n.ramp[2]}", f"ACR {n.acr_y[3]}", f"≈ ${TIERS[2]['acr_per_seat_per_month_usd']:.0f} per seat per month"]},
            {"name": "Replicate", "when": "Next business units", "items": [f"500 seats ≈ {m(TIERS[1]['annual_acr_usd'], 2)} a year", f"10,000 seats ≈ {m(TIERS[3]['annual_acr_usd'])} a year", "Same reference architecture"]},
        ],
        takeaway="Expansion is gated on verified outcomes, so consumption follows proven value.",
        source="Source: business-case/outputs.json (ACR by year, Base; ACR by seat tier); adoption ramp from the model. Modelled, not a forecast.",
        notes=(f"This is how the opportunity lands and expands. A fifty-seat pilot in one region consumes about {kk(ACR['by_year'][0])} in the pilot year and uses Foundry "
               f"models, Speech, Cosmos DB and Container Apps. If the gates are met, the first queues go AI-first and consumption grows to {n.acr_y[1]} in Year 1, with "
               f"Agent Assist and QA at one hundred percent, a second region, Search and Fabric. Year 2 reaches {n.acr_y[2]} and Year 3 {n.acr_y[3]} at {n.ramp[2]} AI-first. "
               f"The pattern then repeats for the next business unit; a 10,000-seat enterprise is about {m(TIERS[3]['annual_acr_usd'])} a year. Expansion is tied to verified "
               f"outcomes, so consumption follows proven value."))

    pen = OPP["scenarios"]
    d.chart(
        f"Illustrative opportunity: ${pen[0]['annual_acr_usd'] / 1e9:.1f}–{pen[-1]['annual_acr_usd'] / 1e9:.1f}B of annual Azure consumption at 2–10% penetration",
        [f"{p_['penetration'] * 100:.0f}% of addressable seats · {p_['seats'] / 1e3:,.0f}K seats" for p_ in pen],
        {"Annual Azure consumption ($M)": [p_["annual_acr_usd"] / 1e6 for p_ in pen]},
        kind="column", number_format='$#,##0"M"',
        commentary=[
            f"**{OPP['global_contact_center_agents'] / 1e6:.0f}M** contact-center agents worldwide (Gartner, 2022 [S5])",
            f"**{share(OPP['addressable_share'])}** addressable by an AI-first service: an **assumption**",
            f"**{n.seat_yr}** of Azure consumption per seat per year (reference tier, modelled)",
            "Penetration of 2%, 5% and 10% are scenarios, **not a forecast**; test addressable share, penetration and per-seat consumption first",
        ],
        commentary_title="How it is built",
        source="Source: business-case/outputs.json (opportunity sizing); Gartner (2022, syndicated copy) [S5]. Assumption-driven and illustrative; no Microsoft or partner commitment is implied.",
        notes=(f"A sizing aid, clearly labelled as assumption-driven. Gartner estimated about seventeen million contact-center agents worldwide in 2022. We assume "
               f"{share(OPP['addressable_share'])} are addressable by an AI-first service; that is an assumption. We apply the reference tier's consumption of about {n.seat_yr} "
               f"per seat per year. At two, five and ten percent penetration of addressable seats, that is roughly {m(pen[0]['annual_acr_usd'], 0)}, {m(pen[1]['annual_acr_usd'], 0)} and "
               f"{m(pen[2]['annual_acr_usd'], 0)} of annual Azure consumption. This is not a forecast and not a commitment by anyone; it shows the order of magnitude and which "
               f"assumptions to test: addressable share, penetration and per-seat consumption."))

    d.table(
        "Concierge complements Microsoft's contact-center stack and the CCaaS suites customers already run",
        ["Offering", "What it is (per Microsoft documentation)", "How Concierge relates"],
        [
            ["Dynamics 365 Contact Center", "Copilot-first contact-center application: omnichannel routing, AI agents, quality evaluation, Teams collaboration [S20]", "Complement or alternative; Concierge adds a voice-native realtime path, a standalone evaluation harness and 100% QA depth"],
            ["Copilot Studio", "Low-code agent builder, including voice-enabled agents [S20]", "Agents can be tools or front ends behind the same policy engine"],
            ["Azure OpenAI Realtime, Foundry, Speech, Voice Live", "Speech-to-speech models over SIP, WebRTC and WebSocket; integrated voice API [S17][S18][S19]", "The building blocks Concierge consumes; Voice Live SIP is in public preview [S31]"],
            ["Teams Phone Extensibility", "Teams Phone numbers and calling for CCaaS ISVs through Call Automation [S21]", "One of the production telephony paths behind the adapter"],
            ["Azure Communication Services", "Retired as a standalone offering on 30 Sep 2028; existing tenants only going forward [S16]", "Supported through the adapter for existing tenants, not relied on"],
            ["CCaaS suites (Genesys, NICE, Five9, Cisco, others)", "Full contact-center suites with their own AI roadmaps [S24]", "Interoperate over SIP and APIs: AI-first layer in front, suite stays"],
        ],
        col_weights=[2.1, 4.3, 4.3], align=["left", "left", "left"],
        source="Source: PRD §12; Microsoft Learn pages cited. Capabilities change quickly — verify with each vendor. No Microsoft roadmap commitment is implied.",
        notes=("How does Concierge fit with what Microsoft and partners already offer? Dynamics 365 Contact Center is a Copilot-first contact-center application; for customers "
               "standardising on Dynamics it is the shortest path, and Concierge can complement it with a voice-native realtime path and deeper quality and evaluation tooling. "
               "Copilot Studio agents can be tools or front ends behind the same policy engine. Azure OpenAI Realtime, Foundry and Speech are the building blocks we consume. "
               "Teams Phone Extensibility is one production telephony option. CCaaS suites keep their role; we interoperate over SIP and APIs. Capabilities change quickly, so "
               "verify each with the vendor before comparing."))

    # ========================================================= APPENDIX =================================================
    d.set_section(None)
    d.section(
        "Appendix", "Assumptions · value drivers · sensitivity · cost build-up · feature list · pricing basis · voice path · evidence · screens · glossary · sources", number="A",
        notes=("Appendix. These slides answer the detailed questions that finance, architecture and security colleagues raise: the assumptions that carry the business "
               "case, the value drivers and the full sensitivity, how scenarios are defined, the full feature list, the pricing basis, the note on communications and the "
               "Azure Communication Services retirement, the voice path with its latency budget, the evidence from the live deployment, more product screens, a glossary "
               "and the sources. Skip it in the room and leave it in the pack. Everything here is consistent with the requirements, architecture and business-case folders."))
    d.set_section("Appendix")

    def rng(key: str, f) -> str:
        return f"{f(A[key]['low'])}–{f(A[key]['high'])}"

    def typ(key: str) -> str:
        return "Customer input" if A[key]["flag"] == "customer_input" else "Assumption"

    ar = A["adoption_ramp"]
    d.table(
        "Ten assumptions carry the business case; each is flagged for validation with customer data",
        ["Assumption", "Type", "Base", "Range tested", "Why it matters"],
        [
            ["Agents (seats) in scope", typ("agents"), f"{A['agents']['base']:,.0f}", rng("agents", lambda v: f"{v:,.0f}"), "Sets the cost base"],
            ["Contacts per year", typ("contacts_per_year"), f"{A['contacts_per_year']['base'] / 1e6:.0f}M", rng("contacts_per_year", lambda v: f"{v / 1e6:.1f}M"), "Voice minutes and Azure consumption"],
            ["Loaded cost per agent", typ("loaded_cost_per_agent_usd"), f"${A['loaded_cost_per_agent_usd']['base'] / 1e3:.0f}K", rng("loaded_cost_per_agent_usd", lambda v: f"${v / 1e3:.0f}K"), "Value of every minute saved"],
            ["Cashable share of loaded cost", typ("variable_cost_share"), pct0(A["variable_cost_share"]["base"]), rng("variable_cost_share", pct0), "How much of the saving becomes cash"],
            ["AI verified resolution at maturity", typ("ai_containment_pct"), pct0(A["ai_containment_pct"]["base"]), rng("ai_containment_pct", pct0), "The headline driver; measured in the pilot"],
            ["AHT reduction on human-handled contacts", typ("aht_reduction_pct"), pct0(A["aht_reduction_pct"]["base"]), rng("aht_reduction_pct", pct0), "Agent Assist and auto wrap-up value"],
            ["AI-first share, Years 1 / 2 / 3", typ("adoption_ramp"), " / ".join(pct0(v) for v in ar["base"]),
             " / ".join(pct0(v) for v in ar["low"]) + " to " + " / ".join(pct0(v) for v in ar["high"]), "Pace of roll-out"],
            ["Agent attrition", typ("attrition_rate"), pct0(A["attrition_rate"]["base"]), rng("attrition_rate", pct0), "Hiring and training avoidance"],
            ["Manual QA coverage today", typ("qa_coverage_baseline"), pct0(A["qa_coverage_baseline"]["base"]), rng("qa_coverage_baseline", pct0), "QA effort and quality baseline"],
            ["Discount rate", typ("discount_rate"), pct0(A["discount_rate"]["base"]), rng("discount_rate", pct0), "NPV"],
        ],
        col_weights=[3.2, 1.4, 1.5, 2.6, 3.0], align=["left", "left", "right", "right", "left"],
        source=f"Source: business-case/assumptions.json ({len(A)} assumptions, each with low / base / high, rationale and source). Customer inputs are facts the customer can supply; assumptions are tested in the pilot.",
        notes=("The business case rests on a short list of assumptions. Those marked customer input, such as agents, contacts, attrition and QA coverage, are facts you can "
               "supply within a day. Those marked assumption, such as verified resolution, handle-time reduction, loaded cost, the cashable share and the ramps, are where "
               "the pilot earns its keep. The table shows the base value and the range we tested; the tornado earlier shows the NPV swing. The first conversation with your "
               "finance team should be about the three biggest: resolution rate, agents and cost per agent, and the share of cost that is genuinely cashable."))

    how = {
        "ai_containment": f"Verified AI resolutions avoid human handling ({pct0(A['ai_containment_pct']['base'])} at maturity)",
        "aht_reduction": f"Agent Assist and auto wrap-up cut handle time by {pct0(A['aht_reduction_pct']['base'])}",
        "qa_quality": "Fewer manual QA hours and fewer repeat contacts",
        "attrition": "Less repetitive work: fewer hires and trainings",
        "abandonment_csat_retention": "Recovered abandoned calls and lower churn",
        "peak_resilience": "AI absorbs overflow that was outsourced at a premium",
        "compliance_risk": "100% monitoring and redaction reduce incidents",
        "multilingual": "Small-language queues served without extra hiring",
    }
    two_core = cat_total["ai_containment"] + cat_total["aht_reduction"]
    d.table(
        f"Eight value drivers, each risk-adjusted: containment and handle time make up {share(two_core / BEN_TOT)} of the {n.ben3}",
        ["Value driver", "How it creates value", "Year 1", "Year 2", "Year 3", "3 years", "Confidence"],
        [[short[c], how[c], *[m(BY_CAT[c][i], 2) for i in (1, 2, 3)], m(cat_total[c], 2), f"{conf[c]:.1f}"] for c in cat_order]
        + [["Total, risk-adjusted", "", *[m(by_year[i], 2) for i in (1, 2, 3)], m(BEN_TOT, 2), ""]],
        col_weights=[2.6, 4.2, 1.0, 1.0, 1.0, 1.05, 1.25], align=["left", "left", "right", "right", "right", "right", "right"], highlight_rows=[len(cat_order)],
        takeaway="The confidence factors are the most subjective numbers in the model: challenge them first.",
        source="Source: business-case/outputs.json (Base, US$ millions) and PRD §11.1. Confidence factors multiply gross benefits. Excluded: cross-sell and upsell, outbound campaigns, wage inflation, licence discounts.",
        notes=(f"The eight value drivers behind the benefit total, risk-adjusted. AI containment is the largest at {m(cat_total['ai_containment'])} over three years and handle-time "
               f"reduction follows at {m(cat_total['aht_reduction'])}; the other six drivers together add {m(BEN_TOT - two_core)}. The confidence factor multiplies the gross benefit: "
               f"{conf['ai_containment']:.1f} for the two core drivers, down to {min(conf.values()):.1f} for revenue effects and compliance risk, which are the hardest to attribute. "
               f"Cross-sell, outbound campaigns, wage inflation and licence discounts are excluded on purpose. Finance should challenge the confidence factors first: they are "
               f"the most subjective numbers in the model."))

    d.tornado(
        "Full sensitivity: nine drivers, each moved alone between its low and high bound",
        drivers, base_value=R["npv"] / 1e6, number_format="+0.0;-0.0", metric_label="NPV",
        subtitle=f"Change in three-year NPV versus the base case of {n.npv}, one driver at a time (US$ millions); the tested range is in brackets",
        takeaway=(f"No single driver pushes NPV below {m(worst_single_npv)}; only the stacked worst case turns negative ({n.stress_dn})." if worst_single_npv > 0
                  else f"Scenario NPV: conservative {n.npv_c} · base {n.npv} · upside {n.npv_u}. Stacked worst case: {n.stress_dn}."),
        source="Source: business-case/outputs.json (sensitivity on NPV; scenario and stress results). Stress tests are not forecasts.",
        notes=(f"The full tornado, with the tested ranges in brackets. Each bar moves one driver between its low and high bound while everything else stays at base. The widest "
               f"bars are our own business assumptions: verified resolution, agents in scope and loaded cost per agent. Azure consumption, varied from 0.7 to 1.5 times, moves "
               f"NPV between {m(sens['azure_usage_multiplier']['npv_at_high'], 0)} and {m(sens['azure_usage_multiplier']['npv_at_low'], 0)}, the smallest swing of the nine. "
               f"Scenarios: conservative {n.npv_c}, base {n.npv}, upside {n.npv_u}. If every uncertain driver sits at its worst bound at once, NPV is {n.stress_dn}; that is a "
               f"stress test, not a forecast, and it is why the pilot measures verified resolution first."))

    d.bullets(
        "How the numbers are built: one model, one assumptions file, one outputs file",
        [
            "**One source of numbers** — a pure-Python model reads assumptions.json and writes outputs.json; every slide quotes it",
            f"**Scenarios** — conservative and upside move each uncertain outcome and cost assumption {share(OUT['meta']['scenario_blend'])} of the way to its low or high bound; customer facts, usage drivers and prices stay at base",
            f"**Stress tests** — every uncertain driver at its bound at once: NPV {n.stress_dn} (downside) and {n.stress_up} (upside); not forecasts",
            f"**Risk adjustment** — each benefit category is multiplied by a confidence factor ({min(conf.values()):.1f}–{max(conf.values()):.1f}); only the variable share of loaded cost counts as cash",
            "**Payback** — measured from project start, including the 6-month build and pilot; costs spread evenly, benefits ramp inside each year",
            "**Excluded** — cross-sell and upsell revenue, outbound campaigns, wage inflation, tool consolidation, any licence discount",
        ],
        side_title="Price basis",
        side_items=[f"Azure Retail Prices API, retrieved {PRICE_SHORT}", "Sweden Central (West Europe where noted)", "USD, pay-as-you-go, no EA discount", "Azure OpenAI at EU Data Zone Standard rates"],
        size=16,
        source="Source: business-case/README.md and model.py (deterministic; unit tests assert that outputs.json is reproducible).",
        notes=(f"How the numbers are built. A pure-Python model reads one assumptions file and produces one outputs file; every slide quotes that file. Conservative and upside "
               f"move each uncertain outcome and cost assumption {share(OUT['meta']['scenario_blend'])} of the way to its low or high bound; customer facts, usage drivers and prices "
               f"stay at base. The stacked stress puts every uncertain driver at its bound together. Benefits are multiplied by confidence factors and only the variable share "
               f"of cost is treated as cash. Payback is measured from project start, including the six-month build and pilot. Automated tests protect the model."))

    oc = COST["other_by_category"]
    cost_rows = [
        ("Implementation, integration and pilot (one-time)", oc["implementation_integration"]),
        ("Change management and training (one-time)", oc["change_management"]),
        ("Contingency on one-time costs", oc["contingency"]),
        ("AI operations team: LLMOps, knowledge, evaluation", oc["ai_operations_team"]),
        ("Third-party licences, SBC and telephony interop", oc["licences_and_telephony_interop"]),
        ("Solution support and maintenance", oc["support_and_maintenance"]),
        ("Communications outside Azure: SIP / CPaaS, messaging", oc["communications_outside_azure"]),
        ("Azure consumption (ACR)", COST["azure_total_by_year"]),
    ]
    one_off = sum(oc["implementation_integration"]) + sum(oc["change_management"])
    d.table(
        f"Where the {n.cost3} goes: Azure is {share(sum(COST['azure_total_by_year']) / COST['total'])}, the rest is integration, people and carriers",
        ["Cost element", "Year 0", "Year 1", "Year 2", "Year 3", "3-year total"],
        [[lab_, *[m(v, 2) if v else "—" for v in vals], m(sum(vals), 2)] for lab_, vals in cost_rows]
        + [["Total cost", *[m(v, 2) for v in COST["total_by_year"]], m(COST["total"], 2)]],
        col_weights=[4.6, 1.1, 1.1, 1.1, 1.1, 1.4], align=["left", "right", "right", "right", "right", "right"], highlight_rows=[len(cost_rows)],
        takeaway=f"Conservative by construction: {share(sum(oc['contingency']) / one_off)} contingency on one-off costs, a standing AI operations team and communications at list price.",
        source="Source: business-case/outputs.json (costs, Base, US$ millions). One-off costs fall in Year 0; Azure consumption is the ACR model at list price.",
        notes=(f"A CFO will ask where the money goes. Of the {n.cost3} three-year cost, Azure consumption is {m(sum(COST['azure_total_by_year']))}. One-off implementation, integration and change "
               f"management are {m(one_off)}, with a {share(sum(oc['contingency']) / one_off)} contingency on top. The AI operations team, which owns knowledge, prompts, evaluation and "
               f"release, is {m(sum(oc['ai_operations_team']))}. Licences, support and communications, such as the SIP trunk and messaging providers, make up the rest. Communications are "
               f"carrier costs outside Azure in this model. Everything is priced at list, and nothing assumes a discount."))

    for ci in range(3):
        chunk = FEATURES[ci * 8: (ci + 1) * 8]
        titles = ["Feature list (1 of 3): conversational agents, identity and routing (CC-01 to CC-08)",
                  "Feature list (2 of 3): wrap-up, quality, insight, planning and evaluation (CC-09 to CC-16)",
                  "Feature list (3 of 3): rollout, outreach, platform and Studio (CC-17 to CC-24)"]
        notes_f = [
            ("The full Release 1 feature list, part one: the conversational agents and the routing and handoff features. Priority P0 means part of the minimum viable product; "
             "P1 arrives in the beta; the single P2 feature arrives at general availability. Delivery status is tracked on the feature board in the repository, which engineering "
             "updates as each feature is implemented, tested and deployed. Each feature has testable acceptance criteria in the features document, traceable to a product requirement "
             "and a KPI, so you can ask for the evidence behind any line."),
            ("The full Release 1 feature list, part two: auto wrap-up, auto-QA, the compliance guard, voice of customer, the CX and ROI view, forecasting, the supervisor "
             "console and the evaluation harness. Notice that most of the quality and learning loop is P0, because it is what makes the AI auditable. Priorities map to "
             "releases: P0 to the MVP, P1 to the beta, P2 to general availability. Delivery status for every feature is tracked on the feature board in the repository, "
             "next to the acceptance criteria and the evidence."),
            ("The full Release 1 feature list, part three: staged rollout, proactive outreach, multilingual and accessibility, the CRM integration layer, security and RBAC, "
             "observability and FinOps, infrastructure as code and the Agent Studio. These are mostly P1 platform features that turn a demo into something operable. "
             "Outbound is the only P2 feature and is deliberately a thin, consent-first slice. Delivery status is tracked on the feature board in the repository; the report "
             "there holds the test and deployment evidence."),
        ]
        d.table(
            titles[ci], ["ID", "Feature", "Epic", "Priority", "Release"] + (["Status"] if HAS_STATUS else []),
            [[f_["id"], f_["name"], f_["epic"], f_["prio"], RELEASE[f_["prio"]]] + ([f_["status"]] if HAS_STATUS else []) for f_ in chunk],
            col_weights=[0.8, 3.7, 3.1, 0.8, 0.8] + ([1.2] if HAS_STATUS else []), align=["left", "left", "left", "center", "center"] + (["left"] if HAS_STATUS else []),
            source="Source: FEATURES.md" + (" status board (read at deck build)" if HAS_STATUS else "") + ". P0 = MVP, P1 = Beta, P2 = GA (PRD §14).", notes=notes_f[ci])

    def P(key: str, zone: str = "datazone") -> float:
        v = UPRICE[key]
        return v[zone] if zone in v else v["value"]

    full_share = A["rt_full_model_share"]["base"]
    d.table(
        "Pricing basis: Azure list prices from the Retail Prices API, EU Data Zone rates for Azure OpenAI",
        ["Service", "Meter", "List price (USD)", "Used for"],
        [
            ["Azure OpenAI gpt-realtime-2.1-mini", "audio in / out, per 1M tokens", f"${P('rt_mini_audio_in'):.2f} / ${P('rt_mini_audio_out'):.2f}", f"Voice agent, {pct0(1 - full_share)} of AI voice minutes"],
            ["Azure OpenAI gpt-realtime-2.1", "audio in / out, per 1M tokens", f"${P('rt_full_audio_in'):.2f} / ${P('rt_full_audio_out'):.2f}", f"Voice agent, {pct0(full_share)} of minutes (hard cases)"],
            ["Azure OpenAI gpt-5.4-mini", "input / cached / output, per 1M tokens", f"${P('chat_mini_in'):.3f} / ${P('chat_mini_cached'):.4f} / ${P('chat_mini_out'):.2f}", "Chat, Agent Assist, wrap-up, QA"],
            ["Azure OpenAI gpt-5.4", "input / output, per 1M tokens", f"${P('chat_full_in'):.2f} / ${P('chat_full_out'):.2f}", "Borderline QA, reasoning, evaluation judges"],
            ["Azure AI Speech", "streaming STT per audio hour (+ diarization add-on)", f"${P('stt_hour'):.2f} (+${P('stt_enhanced_hour'):.2f})", "Transcription of human-handled calls"],
            ["Azure AI Content Safety", "per 1,000 text records", f"${P('content_safety_per_1k'):.3f}", "Prompt Shields, moderation, groundedness"],
            ["Azure AI Search (S1)", "per unit-hour · semantic ranker per 1,000 queries", f"${P('search_s1_hour'):.3f} · ${P('search_semantic_per_1k'):.2f}", "Hybrid retrieval, replicas per region"],
            ["Microsoft Fabric", "per capacity-unit hour", f"${P('fabric_cu_hour'):.2f}", "Real-Time Intelligence analytics"],
            ["Front Door Premium", "base fee per month", f"${P('fd_premium_base_month'):,.0f}", "Global entry and WAF"],
            ["Container Apps", "per vCPU-second (active)", f"${P('aca_vcpu_second'):.6f}", "Conversation plane"],
        ],
        col_weights=[2.9, 3.4, 2.4, 3.2], align=["left", "left", "right", "left"],
        source=f"Source: business-case/pricing_snapshot.json (exact API rows) and assumptions.json; retrieved {PRICE_SHORT}. Global deployments are about {GLOBAL_CHEAPER} cheaper but give up EU data-zone processing.",
        notes=(f"Pricing basis. Every Azure unit price is a list price taken from the Azure Retail Prices API on {PRICE_LONG}, for Sweden Central or West Europe, in US "
               f"dollars, pay-as-you-go, with no enterprise discount. Azure OpenAI uses EU data-zone rates, which are about {DZ_PREMIUM} above global deployment rates. The "
               "table shows the main meters. Realtime audio tokens are estimated at roughly ten input and twenty output tokens per second of speech, with cached re-reads "
               "of the growing context on every response. A price-refresh script diffs the stored snapshot against the live API, so drift is visible and the model can be "
               "re-run on the day of a customer decision."))

    d.bullets(
        "Telephony and messaging stay pluggable because Azure Communication Services is being retired",
        [
            "**23 Sep 2026** — Microsoft announced that Azure Communication Services is retired as a standalone offering on **30 Sep 2028** [S16]",
            "**What goes** — Direct Routing, Direct Offer numbers, SMS, Email, Chat, WhatsApp and Job Router; Call Automation stays for Teams-aligned scenarios",
            "**What arrived** — Azure OpenAI Realtime accepts SIP calls directly (East US 2, France Central, Sweden Central) [S17]",
            "**Our design** — telephony, channels and routing sit behind adapters: SIP trunk or SBC by default, Teams Phone, Dynamics 365 or an existing CCaaS as options",
            f"**Our model** — communications are priced at ACS list rates as a proxy and counted as a customer cost ({n.comms3} in Year 3), not as Azure consumption",
        ],
        side_title="Model treatment",
        side_items=[f"Communications, Year 3: **{n.comms3}**", "Counted as ACR: **0%** by default", f"Voice minute: **{n.voice_min}** Azure · **{n.voice_min_plat}** with comms",
                    f"Tenant already on ACS: billing 100% through Azure adds {n.comms3} to Year-3 ACR; customer NPV unchanged"],
        size=16,
        source="Source: Microsoft Learn, ACS retirement and breaking-changes guide; Realtime API via SIP [S16][S17]; business-case/outputs.json. Re-verify before any production decision.",
        notes=("A platform note that matters for the telephony path. Microsoft announced on 23 September 2026 that Azure Communication Services is retired as a standalone "
               "offering on 30 September 2028: direct routing, direct-offer numbers, SMS, e-mail, chat, WhatsApp and Job Router go away, and call automation remains only for "
               "Teams-aligned scenarios. Meanwhile Azure OpenAI Realtime accepts SIP calls directly. So Concierge keeps telephony and messaging behind adapters. The model "
               "prices communications at ACS list rates as a proxy, treats them as a customer cost, and counts none of it as Azure consumption unless the tenant already "
               "runs on ACS, in which case the setting can be switched without changing the customer's NPV."))

    d.diagram(
        "Voice path: SIP trunk to Azure OpenAI Realtime, with a design budget under 800 ms at p95",
        [
            {"id": "caller", "x": 0.0, "y": 0.4, "w": 1.9, "h": 1.0, "title": "Caller", "sub": "phone or mobile", "kind": "ghost"},
            {"id": "sbc", "x": 3.3, "y": 0.4, "w": 2.3, "h": 1.0, "title": "SIP trunk or SBC", "sub": "carrier or customer"},
            {"id": "rt", "x": 7.1, "y": 0.4, "w": 2.3, "h": 1.0, "title": "Azure OpenAI Realtime", "sub": "SIP endpoint · Sweden or France Central", "kind": "dark"},
            {"id": "human", "x": 10.5, "y": 0.4, "w": 1.6, "h": 1.0, "title": "Human agent", "sub": "CCaaS · Teams · PBX", "kind": "ghost"},
            {"id": "bo", "x": 0.0, "y": 2.9, "w": 1.9, "h": 1.0, "title": "Back office", "sub": "orders · CRM · payments", "kind": "ghost"},
            {"id": "policy", "x": 3.3, "y": 2.9, "w": 2.3, "h": 1.0, "title": "Policy engine + tools", "sub": "caps · audit"},
            {"id": "ctrl", "x": 7.1, "y": 2.9, "w": 2.3, "h": 1.0, "title": "Voice control service", "sub": "webhook · accept · telemetry", "kind": "accent"},
            {"id": "web", "x": 10.5, "y": 2.9, "w": 1.6, "h": 1.0, "title": "Browser voice", "sub": "demo live channel", "kind": "ghost"},
        ],
        [
            {"from": "caller", "to": "sbc", "label": "PSTN"},
            {"from": "sbc", "to": "rt", "label": "SIP over TLS"},
            {"from": "rt", "to": "human", "label": "REFER", "dashed": True},
            {"from": "rt", "to": "ctrl", "label": "webhook + WebSocket by call ID", "bidir": True},
            {"from": "ctrl", "to": "policy", "label": "tool calls"},
            {"from": "policy", "to": "bo", "label": "connectors"},
            {"from": "ctrl", "to": "web", "label": "WebSocket", "bidir": True, "dashed": True},
        ],
        takeaway="Measured in the demo, with typed turns from a laptop: first audio 0.34 s in the smoke test, p50 1.1 s and p95 1.8 s over 3 calls. The 800 ms p95 budget is the phone-path target, measured in the pilot.",
        source="Source: REPORT-TEST-AND-DEPLOYMENT.md (live latency table); ARCHITECTURE.md §7 design budget in ms, p50/p95: carrier 30/60, network 10/20, end-of-turn 200/300, model 200/300, return 40/80. PSTN is not provisioned.",
        notes=("The voice path in one picture. The caller reaches a SIP trunk or session border controller, which routes the call over TLS to the Azure OpenAI Realtime "
               "endpoint. Azure calls our webhook; the voice control service accepts the call and opens a WebSocket by call ID for tools, transcripts and telemetry. Tool "
               "calls pass through the policy engine, and a SIP REFER hands the caller to a human. The under-800-millisecond budget is a design target for the phone path, "
               "to be measured in the pilot. The demo uses browser voice, and it measured a first audio of 0.34 seconds in the smoke test and 1.1 seconds at the median "
               "over three calls."))

    d.capability_map(
        "The reference implementation is real where it matters and honest where it simulates",
        [
            {"name": "Real on Azure in the demo slice", "color": d.t.good, "items": [
                "Azure OpenAI chat, reasoning and Realtime voice", "Speech, Language and Content Safety (Prompt Shields)", "Cosmos DB for state, audit and configuration",
                "Blob storage, Application Insights, Log Analytics", "Container Apps, keyless managed identity, Bicep and azd"]},
            {"name": "Simulated, and labelled as such in the UI", "color": d.t.accent3, "items": [
                "PSTN telephony and SIP: a simulator behind the adapter", "SMS, WhatsApp and e-mail delivery: an outbox panel", "Back office: mock orders, returns, refunds and CRM",
                "Payment provider and one-time-code delivery", "Customers, knowledge base and history are synthetic"]},
            {"name": "Target architecture only, not deployed in the demo", "color": "7A8CA3", "items": [
                "Front Door, WAF, private endpoints, no public access", "Multi-region active/active voice and disaster recovery", "AI Search, Event Hubs and Fabric analytics",
                "Entra External ID, Key Vault, Purview, Defender", "SIP trunk into the Realtime SIP endpoint for phone calls"]},
        ],
        takeaway="The pilot's first job is to replace the simulated and target-only pieces with the customer's own systems and measure them.",
        source="Source: ARCHITECTURE.md §21 (implemented vs target); infra/resources.bicep; REPORT-TEST-AND-DEPLOYMENT.md holds the verified deployment and test evidence.",
        notes=("Honesty about scope matters, so here is what the reference implementation is. On Azure, for real: the chat, reasoning and realtime voice models, speech, language "
               "and content-safety services, Cosmos DB, storage, monitoring and Container Apps, all reached with managed identity and no keys. Simulated, and labelled in the "
               "interface: phone-network telephony, SMS, WhatsApp and e-mail delivery, the back-office systems, the payment provider and all customer data. Target only: the edge "
               "and private-network landing zone, multi-region voice, search, analytics and the identity and security services. The pilot's first job is to swap the simulated "
               "pieces for your systems and measure the result."))

    # evidence from the live deployment (REPORT-TEST-AND-DEPLOYMENT.md §1; EVIDENCE_CHECKS fails the build if the report stops saying so)
    d.table(
        "Verified, not just demoed: 24 of 24 features deployed, 21 of 21 live checks and 42 of 42 evaluation scenarios passed",
        ["Area", "Result (Azure Container Apps, Sweden Central)", "How it was measured"],
        [
            ["Release 1 scope", "24 of 24 features deployed, each with an API and a screen", "FEATURES.md status board"],
            ["Automated tests", "212 unit and API tests and 27 browser tests (accessibility scans of 14 routes); 85% line coverage of domain logic", "pytest · Playwright · axe-core WCAG A/AA"],
            ["Live smoke test", "21 of 21 checks pass against the Azure deployment, including voice, handoff and the ROI calculator", "Scripted, against the live URL"],
            ["Evaluation harness", "42 of 42 scenarios on real models (run-to-run 40–42); 44-attack red-team pack; the release gate fails for four deliberately broken configurations", "gpt-5.4-mini; resolution, accuracy, policy, safety"],
            ["Business-case parity", f"In-app calculator reproduces outputs.json within 0.5%: NPV {n.npv}, ROI {n.roi}, Year-3 ACR {n.acr3}", "Smoke check 19"],
            ["Latency, from a laptop", "Chat turn p50 / p95 1.6 / 1.9 s; first token 1.3 / 1.6 s; voice first audio 0.34 s (smoke), p50 1.1 s, p95 1.8 s", "12 chat turns, 3 voice calls: small samples"],
            ["Known gaps", "First-token objective burns on turns with tool calls (p95 6.4 s); voice p95 is above the 800 ms phone-path target; PSTN is simulated", "Observability and FinOps screen"],
            ["Idle cost", "About US$28 a month (one always-on replica ≈ $22, container registry ≈ $5, other < $1); tokens extra, capped by a daily budget guard", "Retail Prices API estimate"],
        ],
        col_weights=[1.7, 6.6, 3.2], align=["left", "left", "left"],
        takeaway="Small samples from a laptop: the pilot repeats every measurement on your traffic, your knowledge base and your telephony path.",
        source=(f"Source: REPORT-TEST-AND-DEPLOYMENT.md §1 (final build {build_id}" + (f"; measured on {measured_id}, identical Python code" if measured_id != build_id else "")
                + "); FEATURES.md status board; business-case/outputs.json."),
        notes=("Engineering evidence from the live deployment, taken from the test and deployment report. All twenty-four Release 1 features are deployed. The automated suite "
               "has 212 unit and API tests and 27 browser tests, including accessibility scans, with 85 percent line coverage on domain logic. A live smoke test passes 21 of 21 "
               "checks, and the evaluation harness passes 42 of 42 scenarios on real models, although run-to-run variation is 40 to 42. We are open about the gaps: the "
               "first-token objective burns on tool-using turns, voice p95 is above the phone-path target, and PSTN is simulated. Samples are small; the pilot measures on your traffic."))

    if have_customers:
        journeys_slide("The two golden journeys step by step: resolved by the AI, or handed to a person with the full context")

    d.table(
        "Concierge sits beside the suites and CRMs customers already run; it does not ask them to rip and replace",
        ["Category", "Examples", "Typical strengths", "Where Concierge differs or complements"],
        [
            ["CCaaS suites with built-in AI", "Genesys Cloud, NICE CXone (closed its Cognigy acquisition on 8 Sep 2025 [S24]), Five9, Talkdesk, Cisco Webex Contact Center, Amazon Connect",
             "Carrier-grade telephony, ACD and WFM; integrated AI roadmaps", "Sits beside the suite over SIP and APIs; runs in the customer's Azure tenant"],
            ["CRM-centred suites", "Salesforce Service Cloud and Agentforce, ServiceNow Customer Service, Zendesk", "Workflow and data gravity", "Integrates through CRM adapters and the same policy-guarded tools"],
            ["AI-native agent platforms", "Sierra, Decagon, PolyAI, Parloa, Kore.ai, Cognigy", "Fast conversational automation",
             "Verified-resolution measurement, human + AI continuum, 100% QA, an open evaluation gate, tenant-owned data"],
            ["Outsourcers (BPO)", "Many", "Elastic human capacity", "Reduces overflow and its premium cost (the peak-resilience benefit)"],
            ["Build it yourself on Foundry", "—", "Maximum flexibility", "A tested accelerator: 24 features, evaluation harness, FinOps and infrastructure as code included"],
        ],
        col_weights=[2.0, 4.0, 2.6, 3.9], align=["left", "left", "left", "left"],
        source="Source: PRD §12.2; NiCE press release [S24]. Factual positioning, not a ranking; capabilities change quickly, so verify each vendor before any comparison.",
        notes=("A question every executive asks: how is this different from what we already run, or from the AI-native start-ups? Contact-center suites bring carrier-grade telephony, "
               "routing and workforce management, and Concierge sits beside them over SIP and APIs rather than replacing them. CRM suites bring workflow and data, and we integrate "
               "through adapters and the same policy-guarded tools. AI-native platforms are strong at fast automation; our emphasis is verified resolution, the human and AI continuum, "
               "full quality scoring, an open evaluation gate and tenant-owned data. This is factual positioning, not a ranking, and capabilities change quickly."))

    d.table(
        "Glossary: the terms that matter most in this deck",
        ["Term", "Meaning"],
        [
            ["Verified resolution vs containment", "Containment = no human touched the contact. Verified resolution = the outcome is confirmed in the system of record with no repeat contact in 7 days"],
            ["ACR", "Azure consumed revenue: Azure-billed consumption attributable to the solution, at list price in this document"],
            ["AHT / ACW", "Average handle time (talk or chat time plus wrap-up) · after-call work"],
            ["Policy engine", "Deterministic service that authorises every tool call: allow-lists, caps, eligibility, confirmation, idempotency, audit"],
            ["Context package", "Summary, intent, steps tried, sentiment trajectory, suggested resolution and citations handed to a human"],
            ["RAG", "Retrieval-augmented generation: answers grounded in retrieved knowledge, with citations"],
            ["Prompt Shields", "Azure AI Content Safety feature that detects user-prompt attacks and document attacks"],
            ["Realtime API", "Azure OpenAI speech-to-speech API over WebSocket, WebRTC or SIP"],
            ["SBC / SIP / REFER", "Session border controller · Session Initiation Protocol · SIP call-transfer request"],
            ["Data Zone", "Deployment type that keeps model processing inside a geography such as the EU"],
            ["CCaaS · WFM · VoC", "Contact center as a service · workforce management · voice-of-customer analytics"],
        ],
        col_weights=[2.6, 8.4], align=["left", "left"],
        source="Source: PRD §19 (full glossary).",
        notes=("A short glossary for readers outside contact-center operations or outside Azure. Two definitions matter most for this deck. Containment means no human touched "
               "the contact. Verified resolution means the outcome is confirmed in the system of record with no repeat contact within seven days. We report both, and the gap "
               "between them, because deflection that does not resolve only moves cost and frustration to a later call. ACR is Azure consumed revenue: Azure-billed "
               "consumption attributable to the solution, at list price in this document. The other terms are there so that nobody has to ask in the room."))

    rest = shots.rest()
    if rest:
        k_slides = math.ceil(len(rest) / 6)
        per = math.ceil(len(rest) / k_slides)
        for gi in range(k_slides):
            chunk = rest[gi * per: (gi + 1) * per]
            caps = [caption_for(p_) for p_ in chunk]
            d.gallery(
                f"Live screens from the reference implementation ({gi + 1} of {k_slides}): synthetic Contoso data, real Azure services",
                list(zip([prepare(p_, scratch, crop=True) for p_ in chunk], caps)),
                source=f"{shot_source}. PSTN telephony and SMS, WhatsApp and e-mail delivery are simulated and labelled as such in the interface.",
                notes=(f"More screens from the live reference implementation, part {gi + 1} of {k_slides}: {', '.join(re.split(r'[:;]', c_, maxsplit=1)[0] for c_ in caps)}. "
                       "All screens were captured from the deployed Azure environment with synthetic Contoso Home data. Phone-network telephony and message delivery are "
                       "simulated and labelled as such in the interface. Each screen belongs to a feature in the Release 1 contract, so any of them can be opened live in a "
                       "demo. Metrics on the dashboards are demo history, not the business case, which is the model in the business-case folder."))
    d.screens_found, d.screens_skipped = len(shots.all), [p_.name for p_ in shots.skipped]

    srcs = prd_sources()
    d.reference_list(
        "Sources", srcs, per_slide=11,
        notes=[
            ("Sources, part one, with the same S-numbers as the product requirements document. Market and benchmark numbers are cited only where the wording was verified "
             "against the original page; secondary and vendor sources are flagged. Anything else in the deck is either computed by the business-case model or labelled as an "
             "assumption. Gartner figures are analyst surveys and predictions, not guarantees, and some are cited through syndicated copies of the original press releases."),
            ("Sources, part two: the Quarterly Journal of Economics field study, the attrition and QA benchmarks, the Klarna case, and the regulatory sources: the European "
             "Commission's transparency page, the FCC ruling and the PCI Security Standards Council supplement. Regulatory statements are design inputs, not legal advice; "
             "validate each market with counsel. Vendor and secondary sources are flagged in the title so that readers can weigh them accordingly."),
            ("Sources, part three: market sizing, the Microsoft Learn pages for the Azure services and the retirement of Azure Communication Services, the Azure Retail Prices "
             f"API, and the legal texts. Microsoft Learn pages were read on {PRICE_LONG} and describe documented behaviour; features marked as preview are not production "
             "commitments, and nothing here implies a Microsoft roadmap commitment. Pricing was retrieved from the API on the same day."),
        ][: (len(srcs) + 10) // 11])
    return d


def main() -> int:
    with tempfile.TemporaryDirectory(dir=HERE, prefix=".annot-") as scratch:  # project-local scratch for annotated screenshots, removed on exit
        d = build(Path(scratch))
        out = d.save(OUT_PPTX)
    problems = []
    for i, slide in enumerate(d.prs.slides, 1):
        text = slide.notes_slide.notes_text_frame.text if slide.has_notes_slide else ""
        w = words(text)
        if not 60 <= w <= 120:
            problems.append(f"slide {i}: speaker notes have {w} words (house standard 60–120)")
    print(f"saved {out} · {len(d.prs.slides)} slides · screenshots used: {d.screens_found}"
          + (f" (skipped as inconsistent: {', '.join(d.screens_skipped)})" if d.screens_skipped else "") + f" · deckkit warnings: {len(d.warnings)}")
    for w_ in d.warnings:
        print("  WARN ", w_)
    for p_ in problems:
        print("  NOTES", p_)
    return 1 if (d.warnings or problems) else 0


if __name__ == "__main__":
    sys.exit(main())
