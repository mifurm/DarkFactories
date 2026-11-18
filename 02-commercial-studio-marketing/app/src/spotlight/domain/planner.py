"""Illustrative media-mix planner (CS-19): diminishing-returns response curves + marginal-ROAS allocation + uncertainty ranges."""

from __future__ import annotations

import math
from typing import Any

import numpy as np

# Illustrative channel parameters (assumptions — NOT benchmarks): cpm (USD), saturation spend S (USD, 63% of ceiling),
# conversion ceiling A (purchases) for the market, revenue per purchase, addressable audience (millions) for reach.
CHANNELS: dict[str, dict[str, float]] = {
    "youtube": {"cpm": 11.0, "S": 220_000, "A": 21_000, "aov": 14.5, "pop": 42.0},
    "meta": {"cpm": 9.0, "S": 180_000, "A": 19_000, "aov": 14.5, "pop": 55.0},
    "tiktok": {"cpm": 6.0, "S": 120_000, "A": 9_500, "aov": 14.5, "pop": 30.0},
    "ctv": {"cpm": 24.0, "S": 260_000, "A": 14_000, "aov": 14.5, "pop": 35.0},
    "linkedin": {"cpm": 28.0, "S": 60_000, "A": 2_800, "aov": 14.5, "pop": 8.0},
    "display": {"cpm": 4.0, "S": 150_000, "A": 7_000, "aov": 14.5, "pop": 60.0},
}


def response(channel: dict[str, float], spend: float, k_scale: float = 1.0, a_scale: float = 1.0) -> float:
    return channel["A"] * a_scale * (1 - math.exp(-spend / (channel["S"] * k_scale)))


def marginal(channel: dict[str, float], spend: float) -> float:
    return channel["A"] / channel["S"] * math.exp(-spend / channel["S"]) * channel["aov"]


def reach_m(channel: dict[str, float], spend: float) -> float:
    imps_m = spend / channel["cpm"] * 1000 / 1e6
    return channel["pop"] * (1 - math.exp(-imps_m / channel["pop"]))


def allocate(budget: float, channels: list[str], objective: str = "roas", step: float = 0.01, min_share: float = 0.0, max_share: float = 1.0) -> dict[str, float]:
    """Greedy equalisation of marginal return (revenue for roas/conversions, reach for reach) in 1% budget steps."""
    spend = dict.fromkeys(channels, 0.0)
    base = budget * min_share
    for c in channels:
        spend[c] = base
    left = budget - base * len(channels)
    inc = budget * step
    while left > 1e-6:
        d = min(inc, left)
        best, best_gain = None, -1.0
        for c in channels:
            if spend[c] + d > budget * max_share + 1e-6:
                continue
            ch = CHANNELS[c]
            gain = (reach_m(ch, spend[c] + d) - reach_m(ch, spend[c])) / d if objective == "reach" else (response(ch, spend[c] + d) - response(ch, spend[c])) * ch["aov"] / d
            if gain > best_gain:
                best, best_gain = c, gain
        if best is None:
            break
        spend[best] += d
        left -= d
    return spend


def plan(budget: float, channels: list[str] | None = None, objective: str = "roas", seed: int = 7, draws: int = 400, min_share: float = 0.0) -> dict[str, Any]:
    chans = [c for c in (channels or list(CHANNELS)) if c in CHANNELS]
    spend = allocate(budget, chans, objective, min_share=min_share)
    rng = np.random.default_rng(seed)
    k_s = rng.lognormal(0, 0.2, size=(draws, len(chans)))
    a_s = rng.lognormal(0, 0.2, size=(draws, len(chans)))
    rev_draws = np.zeros(draws)
    conv_draws = np.zeros(draws)
    for j, c in enumerate(chans):
        for i in range(draws):
            conv = response(CHANNELS[c], spend[c], k_s[i, j], a_s[i, j])
            conv_draws[i] += conv
            rev_draws[i] += conv * CHANNELS[c]["aov"]
    rows: list[dict[str, Any]] = []
    total_reach = 0.0
    for c in chans:
        ch = CHANNELS[c]
        conv = response(ch, spend[c])
        r = reach_m(ch, spend[c])
        total_reach += r
        rows.append({"channel": c, "spend": round(spend[c], 2), "share": round(spend[c] / budget, 4) if budget else 0, "impressions_m": round(spend[c] / ch["cpm"] * 1000 / 1e6, 2), "reach_m": round(r, 2), "conversions": round(conv), "revenue": round(conv * ch["aov"]), "roas": round(conv * ch["aov"] / spend[c], 2) if spend[c] else None, "marginal_roas": round(marginal(ch, spend[c]), 2), "saturation": round(1 - math.exp(-spend[c] / ch["S"]), 3)})
    def q(a: Any, p: float) -> float:
        return float(np.percentile(a, p))
    return {
        "budget": budget, "objective": objective, "allocation": rows,
        "totals": {"spend": round(budget, 2), "reach_m_upper_bound": round(total_reach, 2), "conversions": round(sum(r["conversions"] for r in rows)), "revenue": round(sum(r["revenue"] for r in rows)), "roas": round(sum(r["revenue"] for r in rows) / budget, 2) if budget else None},
        "ranges": {"roas_p10": round(q(rev_draws / budget, 10), 2), "roas_p50": round(q(rev_draws / budget, 50), 2), "roas_p90": round(q(rev_draws / budget, 90), 2), "conversions_p10": round(q(conv_draws, 10)), "conversions_p90": round(q(conv_draws, 90))},
        "note": "ILLUSTRATIVE: diminishing-returns curves with assumed parameters; calibrate with your own performance data (CS-18) before using for decisions.",
        "assumptions": {c: CHANNELS[c] for c in chans},
    }


def uniform_baseline(budget: float, channels: list[str]) -> float:
    each = budget / len(channels)
    return sum(response(CHANNELS[c], each) * CHANNELS[c]["aov"] for c in channels)
