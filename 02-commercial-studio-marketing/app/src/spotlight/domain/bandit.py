"""Multi-armed bandit (Thompson sampling), significance testing and a seeded experiment simulator (CS-17)."""

from __future__ import annotations

import math
from typing import Any

import numpy as np


def two_proportion_z(x1: int, n1: int, x2: int, n2: int) -> tuple[float, float]:
    """Pooled two-proportion z-test. Returns (z, two-sided p). z > 0 means arm 1 converts better than arm 2."""
    if n1 <= 0 or n2 <= 0:
        return 0.0, 1.0
    p1, p2 = x1 / n1, x2 / n2
    p = (x1 + x2) / (n1 + n2)
    se = math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2))
    if se == 0:
        return 0.0, 1.0
    z = (p1 - p2) / se
    pval = math.erfc(abs(z) / math.sqrt(2))
    return z, pval


def prob_best(alpha: np.ndarray, beta: np.ndarray, rng: np.random.Generator, draws: int = 4000) -> np.ndarray:
    """P(arm is best) under Beta posteriors (Monte-Carlo)."""
    samples = rng.beta(alpha[None, :], beta[None, :], size=(draws, len(alpha)))
    wins = np.bincount(samples.argmax(axis=1), minlength=len(alpha))
    return wins / draws


def thompson_allocation(alpha: np.ndarray, beta: np.ndarray, rng: np.random.Generator, active: np.ndarray | None = None, draws: int = 2000, floor: float = 0.02) -> np.ndarray:
    """Budget shares = probability each (active) arm is best, with a small exploration floor."""
    n = len(alpha)
    act = np.ones(n, dtype=bool) if active is None else active
    share = np.zeros(n)
    idx = np.where(act)[0]
    if len(idx) == 0:
        return share
    p = prob_best(alpha[idx], beta[idx], rng, draws)
    p = np.maximum(p, floor)
    share[idx] = p / p.sum()
    return share


def simulate(
    true_rates: list[float],
    hours: int = 24,
    impressions_per_hour: int = 20000,
    strategy: str = "thompson",
    seed: int = 1,
    floor: float = 0.02,
) -> dict[str, Any]:
    """Run an allocation strategy against fixed true click-through rates; returns cumulative reward and the final posterior."""
    rng = np.random.default_rng(seed)
    k = len(true_rates)
    rates = np.array(true_rates)
    alpha, beta = np.ones(k), np.ones(k)
    reward = 0.0
    pulls = np.zeros(k)
    for _ in range(hours):
        share = thompson_allocation(alpha, beta, rng, floor=floor) if strategy == "thompson" else np.full(k, 1.0 / k)
        n = rng.multinomial(impressions_per_hour, share)
        clicks = rng.binomial(n, rates)
        alpha += clicks
        beta += n - clicks
        reward += float(clicks.sum())
        pulls += n
    best = int(np.argmax(rates))
    post_mean = alpha / (alpha + beta)
    return {"reward": reward, "pulls": pulls.tolist(), "best_arm": best, "chosen": int(np.argmax(pulls)), "posterior_best": int(np.argmax(post_mean)), "optimal_reward": float(rates[best] * hours * impressions_per_hour)}


def auto_pause_candidates(arms: list[dict[str, Any]], p_best: np.ndarray, min_impressions: int = 3000, p_threshold: float = 0.01, alpha: float = 0.01) -> list[str]:
    """Pause arms that are very unlikely to be best AND significantly worse than the current leader."""
    live = [i for i, a in enumerate(arms) if a["status"] == "active"]
    if len(live) <= 2:
        return []
    leader = max(live, key=lambda i: arms[i]["clicks"] / max(arms[i]["impressions"], 1))
    out = []
    for i in live:
        if i == leader or arms[i]["impressions"] < min_impressions:
            continue
        z, p = two_proportion_z(arms[leader]["clicks"], arms[leader]["impressions"], arms[i]["clicks"], arms[i]["impressions"])
        if p_best[i] < p_threshold and z > 0 and p < alpha:
            out.append(arms[i]["id"])
    return out
