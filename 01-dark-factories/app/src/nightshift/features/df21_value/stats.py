"""Small statistics helpers (no scipy): Student-t CDF/quantile via the regularised incomplete beta function."""

from __future__ import annotations

import math


def _betacf(a: float, b: float, x: float) -> float:
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > 1e-30 else 1e-30)
    h = d
    for m in range(1, 200):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > 1e-30 else 1e-30)
        c = 1.0 + aa / c
        c = c if abs(c) > 1e-30 else 1e-30
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > 1e-30 else 1e-30)
        c = 1.0 + aa / c
        c = c if abs(c) > 1e-30 else 1e-30
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 3e-12:
            break
    return h


def betainc(a: float, b: float, x: float) -> float:
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    bt = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1.0 - x))
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1.0 - x) / b


def t_cdf(t: float, df: float) -> float:
    x = df / (df + t * t)
    p = 0.5 * betainc(df / 2.0, 0.5, x)
    return 1.0 - p if t > 0 else p


def t_ppf(p: float, df: float) -> float:
    lo, hi = -50.0, 50.0
    for _ in range(100):
        mid = (lo + hi) / 2
        if t_cdf(mid, df) < p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def paired_summary(diffs: list[float], conf: float = 0.95) -> dict[str, float | int | bool]:
    """Mean of paired differences with a two-sided CI and a one-sided p-value for H0: mean <= 0."""
    n = len(diffs)
    if n == 0:
        return {
            "n": 0,
            "mean": 0.0,
            "sd": 0.0,
            "se": 0.0,
            "ci_low": 0.0,
            "ci_high": 0.0,
            "p_one_sided": 1.0,
            "t": 0.0,
            "significant": False,
        }
    mean = sum(diffs) / n
    if n < 2:
        return {
            "n": n,
            "mean": mean,
            "sd": 0.0,
            "se": 0.0,
            "ci_low": mean,
            "ci_high": mean,
            "p_one_sided": 0.5,
            "t": 0.0,
            "significant": False,
        }
    var = sum((d - mean) ** 2 for d in diffs) / (n - 1)
    sd = math.sqrt(var)
    se = sd / math.sqrt(n)
    tcrit = t_ppf(1 - (1 - conf) / 2, n - 1)
    if se < 1e-12:
        t = float("inf") if mean > 0 else 0.0
        p = 0.0 if mean > 0 else 1.0
    else:
        t = mean / se
        p = 1.0 - t_cdf(t, n - 1)
    return {
        "n": n,
        "mean": mean,
        "sd": sd,
        "se": se,
        "ci_low": mean - tcrit * se,
        "ci_high": mean + tcrit * se,
        "p_one_sided": p,
        "t": t if math.isfinite(t) else 1e9,
        "significant": bool(mean - tcrit * se > 0),
    }
