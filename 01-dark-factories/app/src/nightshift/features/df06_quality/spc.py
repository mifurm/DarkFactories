"""Statistical process control primitives (DF-06): X-bar/R charts, Cpk, Western Electric rules, EWMA drift."""

from __future__ import annotations

from typing import Any

import numpy as np

# control-chart constants by subgroup size n
A2 = {2: 1.880, 3: 1.023, 4: 0.729, 5: 0.577, 6: 0.483, 7: 0.419, 8: 0.373, 9: 0.337, 10: 0.308}
D3 = {2: 0.0, 3: 0.0, 4: 0.0, 5: 0.0, 6: 0.0, 7: 0.076, 8: 0.136, 9: 0.184, 10: 0.223}
D4 = {2: 3.267, 3: 2.574, 4: 2.282, 5: 2.114, 6: 2.004, 7: 1.924, 8: 1.864, 9: 1.816, 10: 1.777}
D2 = {2: 1.128, 3: 1.693, 4: 2.059, 5: 2.326, 6: 2.534, 7: 2.704, 8: 2.847, 9: 2.970, 10: 3.078}


def subgroups(x: np.ndarray, n: int = 5) -> np.ndarray:
    m = len(x) // n
    return x[: m * n].reshape(m, n) if m else np.empty((0, n))


def xbar_r(sg: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    return sg.mean(axis=1), sg.max(axis=1) - sg.min(axis=1)


def limits(xbar: np.ndarray, r: np.ndarray, n: int = 5) -> dict[str, float]:
    """Phase-I limits estimated from the data itself (centre line, R-bar)."""
    xbb, rbar = float(xbar.mean()), float(r.mean())
    return {
        "center": xbb,
        "ucl": xbb + A2[n] * rbar,
        "lcl": xbb - A2[n] * rbar,
        "rbar": rbar,
        "ucl_r": D4[n] * rbar,
        "lcl_r": D3[n] * rbar,
        "sigma_hat": rbar / D2[n],
    }


def control_plan_limits(nominal: float, sigma: float, n: int = 5) -> dict[str, float]:
    """Phase-II limits from the control plan (known nominal and within-subgroup sigma)."""
    se = sigma / np.sqrt(n)
    rbar = D2[n] * sigma
    return {
        "center": nominal,
        "ucl": nominal + 3 * se,
        "lcl": nominal - 3 * se,
        "rbar": rbar,
        "ucl_r": D4[n] * rbar,
        "lcl_r": D3[n] * rbar,
        "sigma_hat": sigma,
    }


def cpk(mean: float, sigma_hat: float, lsl: float, usl: float) -> float:
    if sigma_hat <= 0:
        return float("inf")
    return min(usl - mean, mean - lsl) / (3.0 * sigma_hat)


def western_electric(means: np.ndarray, center: float, sigma_mean: float) -> list[dict[str, Any]]:
    """Return rule violations for the LAST point of the series (rules 1-4)."""
    out: list[dict[str, Any]] = []
    if len(means) == 0 or sigma_mean <= 0:
        return out
    z = (means - center) / sigma_mean
    i = len(z) - 1
    if abs(z[i]) > 3:
        out.append({"rule": 1, "detail": "1 point beyond 3 sigma", "index": i})
    if len(z) >= 3:
        last3 = z[-3:]
        for sgn in (1, -1):
            if (sgn * last3 > 2).sum() >= 2 and sgn * z[i] > 2:
                out.append({"rule": 2, "detail": "2 of 3 beyond 2 sigma (same side)", "index": i})
    if len(z) >= 5:
        last5 = z[-5:]
        for sgn in (1, -1):
            if (sgn * last5 > 1).sum() >= 4 and sgn * z[i] > 1:
                out.append({"rule": 3, "detail": "4 of 5 beyond 1 sigma (same side)", "index": i})
    if len(z) >= 8:
        last8 = z[-8:]
        if (last8 > 0).all() or (last8 < 0).all():
            out.append({"rule": 4, "detail": "8 consecutive points on one side of the centre", "index": i})
    return out


def ewma(values: np.ndarray, lam: float = 0.3) -> np.ndarray:
    out = np.empty(len(values))
    s = values[0] if len(values) else 0.0
    for i, v in enumerate(values):
        s = lam * v + (1 - lam) * s
        out[i] = s
    return out
