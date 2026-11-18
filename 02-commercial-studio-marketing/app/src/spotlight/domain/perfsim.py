"""Performance simulator + ingestion + insight generation (CS-18). Everything seeded and deterministic."""

from __future__ import annotations

import csv
import io
import math
from datetime import date, timedelta
from typing import Any

import numpy as np

from ..i18n import has
from ..i18n import t as tr
from ..util import stable_hash
from .bandit import two_proportion_z

# Hidden "ground truth" effects used by the SIMULATED ad platforms (illustrative multipliers on CTR / CVR).
EFFECTS: dict[str, dict[str, tuple[float, float]]] = {
    "hook": {"Human moment first": (1.22, 1.05), "Product first": (0.86, 1.00), "Question hook": (1.04, 0.97), "Sensory close-up": (1.10, 1.02)},
    "cta": {"Find it near you": (1.00, 1.12), "Try it today": (1.06, 0.94), "Learn more": (0.92, 0.88)},
    "visual": {"Warm kitchen": (1.08, 1.04), "Street at dawn": (0.97, 1.00), "Macro pour": (1.12, 0.98)},
    "segment": {"Early-shift workers": (1.10, 1.06), "Commuters": (1.00, 1.00), "Remote workers": (0.94, 0.96)},
}
PLATFORM_FACTORS = {"meta": (1.00, 1.00, 9.0), "tiktok": (1.18, 0.82, 6.0), "youtube": (0.70, 1.10, 11.0), "linkedin": (0.45, 1.25, 28.0), "google": (0.85, 1.05, 12.0), "ctv": (0.12, 1.05, 24.0), "simulated": (1.0, 1.0, 9.0)}
BASE_CTR, BASE_CVR, AOV = 0.012, 0.045, 14.5  # click rate, click->purchase rate, avg order value (USD)
PLATFORMS = ["meta", "tiktok", "youtube", "linkedin", "google"]
METRIC_COLS = ["impressions", "clicks", "views", "completes", "conversions", "spend", "revenue"]


def true_rates(attrs: dict[str, str], seed: int = 1) -> dict[str, float]:
    ctr, cvr = BASE_CTR, BASE_CVR
    for dim, val in attrs.items():
        e = EFFECTS.get(dim, {}).get(val)
        if e:
            ctr *= e[0]
            cvr *= e[1]
    jitter = np.random.default_rng(int(stable_hash([seed, sorted(attrs.items())])[:8], 16)).normal(1.0, 0.04)
    return {"ctr": round(ctr * jitter, 5), "cvr": round(cvr * jitter, 5)}


def simulate_row(attrs: dict[str, str], impressions: int, platform: str, day: str, variant_id: str, rng: np.random.Generator, seed: int = 1) -> dict[str, Any]:
    ctr_f, cvr_f, cpm = PLATFORM_FACTORS.get(platform, PLATFORM_FACTORS["simulated"])
    tr = true_rates(attrs, seed)
    ctr = min(0.2, tr["ctr"] * ctr_f)
    cvr = min(0.5, tr["cvr"] * cvr_f)
    clicks = int(rng.binomial(impressions, ctr))
    views = int(impressions * (0.38 if platform in {"tiktok", "youtube", "meta"} else 0.2))
    completes = int(rng.binomial(max(views, 1), min(0.9, 0.34 + (attrs.get("hook") == "Human moment first") * 0.08)))
    conv = int(rng.binomial(max(clicks, 1), cvr)) if clicks else 0
    spend = round(impressions * cpm / 1000.0, 2)
    return {"date": day, "platform": platform, "variant_id": variant_id, "impressions": impressions, "clicks": clicks, "views": views, "completes": completes, "conversions": conv, "spend": spend, "revenue": round(conv * AOV, 2), "attrs": attrs}


def generate_history(variants: list[dict[str, Any]], days: int, platforms: list[str], seed: int, end: date | None = None, impressions_per_day: int = 5000) -> list[dict[str, Any]]:
    rng = np.random.default_rng(seed)
    end = end or date(2026, 3, 31)
    rows = []
    for d in range(days):
        day = (end - timedelta(days=days - 1 - d)).isoformat()
        for pl in platforms:
            for v in variants:
                n = int(rng.normal(impressions_per_day, impressions_per_day * 0.08))
                rows.append(simulate_row(v["attrs"], max(500, n), pl, day, v["id"], rng, seed))
    return rows


def derived(m: dict[str, float]) -> dict[str, float | None]:
    imp, clk, views, comp, conv, spend, rev = (m.get(k, 0) for k in METRIC_COLS)
    return {
        "ctr": clk / imp if imp else None,
        "vtr": comp / views if views else None,
        "cvr": conv / clk if clk else None,
        "cpa": spend / conv if conv else None,
        "roas": rev / spend if spend else None,
        "cpm": spend / imp * 1000 if imp else None,
    }


def aggregate(rows: list[dict[str, Any]], key: str | None) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, float]] = {}
    for r in rows:
        k = "all" if key is None else str(r.get(key) if key in r else (r.get("attrs") or {}).get(key, "—"))
        g = groups.setdefault(k, dict.fromkeys(METRIC_COLS, 0.0))
        for c in METRIC_COLS:
            g[c] += float(r.get(c, 0) or 0)
    out = [{"key": k, **{c: round(v, 2) for c, v in g.items()}, **{m: (round(x, 5) if x is not None else None) for m, x in derived(g).items()}} for k, g in groups.items()]
    return sorted(out, key=lambda r: -(r["impressions"]))


REQUIRED_COLS = {"date", "impressions", "clicks"}
ALIASES = {"variant": "variant_id", "creative": "variant_id", "creative_id": "variant_id", "ad": "variant_id", "cost": "spend", "purchases": "conversions", "orders": "conversions", "video_views": "views", "completed_views": "completes", "imps": "impressions"}


def parse_csv(text: str, max_rows: int = 20000) -> tuple[list[dict[str, Any]], list[str]]:
    """Validate + normalise an ad-platform export. Returns (rows, errors); bad rows are reported, not silently dropped."""
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        return [], ["empty file"]
    cols = {ALIASES.get(c.strip().lower(), c.strip().lower()): c for c in reader.fieldnames}
    missing = REQUIRED_COLS - set(cols)
    if missing:
        return [], [f"missing required column(s): {', '.join(sorted(missing))}"]
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    for i, raw in enumerate(reader, start=2):
        if len(rows) >= max_rows:
            errors.append(f"row limit {max_rows} reached; remaining rows ignored")
            break
        try:
            d = date.fromisoformat(str(raw[cols["date"]]).strip()[:10])
            row: dict[str, Any] = {"date": d.isoformat(), "platform": (raw.get(cols.get("platform", ""), "") or "csv").strip().lower()[:24] or "csv", "variant_id": (raw.get(cols.get("variant_id", ""), "") or "unassigned").strip()[:64]}
            for c in METRIC_COLS:
                v = raw.get(cols.get(c, ""), "") if c in cols else ""
                num = float(str(v).replace(",", "").replace("$", "").strip() or 0)
                if num < 0 or math.isnan(num):
                    raise ValueError(f"negative or invalid {c}")
                row[c] = int(num) if c not in {"spend", "revenue"} else round(num, 2)
            if row["clicks"] > row["impressions"]:
                raise ValueError("clicks exceed impressions")
            rows.append(row)
        except Exception as exc:
            errors.append(f"row {i}: {exc}")
            if len(errors) >= 25:
                errors.append("… more errors suppressed")
                break
    return rows, errors


def insights_from_rows(rows: list[dict[str, Any]], dims: list[str] | None = None, min_impressions: int = 20000) -> list[dict[str, Any]]:
    """'What works' statements: for each creative/audience dimension compare the best value against the rest (z-test on CTR and CVR)."""
    dims = dims or ["hook", "cta", "visual", "segment", "platform", "aspect"]
    out: list[dict[str, Any]] = []
    for dim in dims:
        agg = [a for a in aggregate(rows, dim) if a["key"] not in {"—", "all"} and a["impressions"] >= min_impressions]
        if len(agg) < 2:
            continue
        for metric, num, den, label in (("ctr", "clicks", "impressions", "click-through rate"), ("cvr", "conversions", "clicks", "conversion rate")):
            ranked = sorted([a for a in agg if a[den] > 0], key=lambda a: -(a[num] / a[den]))
            if len(ranked) < 2:
                continue
            top, rest = ranked[0], ranked[1:]
            rest_x = sum(a[num] for a in rest)
            rest_n = sum(a[den] for a in rest)
            if rest_n == 0 or rest_x == 0:
                continue
            z, p = two_proportion_z(int(top[num]), int(top[den]), int(rest_x), int(rest_n))
            lift = (top[num] / top[den]) / (rest_x / rest_n) - 1
            if z > 0 and p < 0.05 and lift >= 0.05:
                out.append({
                    "dimension": dim, "winner": top["key"], "metric": metric, "lift_pct": round(lift * 100, 1), "p_value": float(f"{p:.3g}"), "n": int(top[den] + rest_n),
                    "statement": f"{dim.capitalize()} “{top['key']}” lifts {label} by {lift * 100:.0f}% vs the other {dim} options (p={p:.2g}, n={int(top[den] + rest_n):,}).",
                    "confidence": round(min(0.99, 1 - p), 3),
                })
    return sorted(out, key=lambda r: (-r["lift_pct"]))


def render_statement(evidence: dict[str, Any], lang: str = "en") -> str | None:
    """The insight sentence for a stored learning's structured evidence, in ``lang`` (None when the evidence is not an insight)."""
    try:
        dim, winner, metric = str(evidence["dimension"]), str(evidence["winner"]), str(evidence["metric"])
        lift, p, n = float(evidence["lift_pct"]), float(evidence["p_value"]), int(evidence["n"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (has(f"insight.dim.{dim}.nom", lang) and has(f"insight.metric.{metric}", lang)):
        return None
    shown = tr(f"attr.{winner}", lang) if has(f"attr.{winner}", lang) else winner
    return tr("insight.statement", lang, nom=tr(f"insight.dim.{dim}.nom", lang), winner=shown, metric=tr(f"insight.metric.{metric}", lang), lift=lift, opts=tr(f"insight.dim.{dim}.opts", lang), p=p, n=n)


def localize_learning(doc: dict[str, Any], lang: str) -> dict[str, Any]:
    """A learning (Brand Brain) with its statement rendered in ``lang`` when it was derived from structured insight evidence."""
    if lang == "en":
        return doc
    text = render_statement(doc.get("evidence") or {}, lang)
    return {**doc, "statement": text, "statement_en": doc["statement"], "lang": lang} if text else doc
