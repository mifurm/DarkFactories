"""Workforce management maths (CC-14): Erlang-C, interval forecasting (seasonal-naive baseline, Holt-Winters on daily totals with weekly
seasonality x intraday profiles), rolling-origin backtests (MAPE/WAPE), AI-vs-human capacity planning with containment what-ifs, greedy shift
scheduling and a discrete-event simulation of the resulting roster. Pure python + numpy, deterministic given seeds."""

from __future__ import annotations

import heapq
import math
import random
from typing import Any

import numpy as np

INTERVAL_S = 1800
N_INT = 48
OPEN_FIRST, OPEN_LAST = 14, 43  # 07:00-22:00 operating window (human queues)
PAID_H_PER_FTE_WEEK = 37.5


# ------------------------------------------------------------------------------------------------------ Erlang
def erlang_b(n: int, a: float) -> float:
    b = 1.0
    for k in range(1, n + 1):
        b = a * b / (k + a * b)
    return b


def erlang_c(n: int, a: float) -> float:
    """Probability that an arriving contact has to wait (M/M/n, infinite patience)."""
    if n <= 0:
        return 1.0
    if n <= a:
        return 1.0
    b = erlang_b(n, a)
    return n * b / (n - a * (1 - b))


def service_level(n: int, a: float, aht_s: float, t_s: float) -> float:
    if n <= a:
        return 0.0
    return max(0.0, 1.0 - erlang_c(n, a) * math.exp(-(n - a) * t_s / aht_s))


def asa(n: int, a: float, aht_s: float) -> float:
    if n <= a:
        return float("inf")
    return erlang_c(n, a) * aht_s / (n - a)


def agents_required(calls: float, aht_s: float, *, interval_s: int = INTERVAL_S, sl_target: float = 0.8, t_s: float = 120, max_occupancy: float = 0.9) -> int:
    """Smallest agent count meeting the service-level target and the occupancy cap for `calls` arriving in one interval."""
    if calls <= 0:
        return 0
    a = calls * aht_s / interval_s
    n = max(1, math.ceil(a))
    while n < 5000:
        if n > a and service_level(n, a, aht_s, t_s) >= sl_target and a / n <= max_occupancy:
            return n
        n += 1
    return n


# ------------------------------------------------------------------------------------------------------ forecasting
def holt_winters(y: list[float], m: int = 7, horizon: int = 7, *, grid: bool = True) -> tuple[list[float], dict[str, float]]:
    """Multiplicative Holt-Winters with damped trend; parameters chosen by one-step SSE grid search."""
    y_arr = np.asarray(y, dtype=float)
    n = len(y_arr)
    if n < 2 * m:
        raise ValueError("need at least two full seasons")
    seasons = min(3, n // m)

    def init() -> tuple[float, float, list[float]]:
        l0 = float(y_arr[:m].mean())
        b0 = float((y_arr[m : 2 * m].mean() - y_arr[:m].mean()) / m)
        s0 = [float(np.mean([y_arr[j * m + i] / y_arr[j * m : (j + 1) * m].mean() for j in range(seasons)])) for i in range(m)]
        return l0, b0, s0

    def run(alpha: float, beta: float, gamma: float, phi: float = 0.98) -> tuple[float, float, float, list[float]]:
        level, trend, season = init()
        season = list(season)
        sse = 0.0
        for t in range(n):
            s = season[t % m]
            pred = (level + phi * trend) * s
            if t >= m:
                sse += (y_arr[t] - pred) ** 2
            new_level = alpha * y_arr[t] / s + (1 - alpha) * (level + phi * trend)
            trend = beta * (new_level - level) + (1 - beta) * phi * trend
            season[t % m] = gamma * y_arr[t] / new_level + (1 - gamma) * s
            level = new_level
        return sse, level, trend, season

    best = (float("inf"), 0.2, 0.01, 0.1)
    if grid:
        for alpha in (0.05, 0.1, 0.2, 0.3, 0.4):
            for beta in (0.0, 0.01, 0.03):
                for gamma in (0.05, 0.1, 0.2, 0.3):
                    sse = run(alpha, beta, gamma)[0]
                    if sse < best[0]:
                        best = (sse, alpha, beta, gamma)
    _, alpha, beta, gamma = best
    _, level, trend, season = run(alpha, beta, gamma)
    phi = 0.98
    fc = []
    for h in range(1, horizon + 1):
        damp = sum(phi**i for i in range(1, h + 1))
        fc.append(max(0.0, (level + damp * trend) * season[(n + h - 1) % m]))
    return fc, {"alpha": alpha, "beta": beta, "gamma": gamma, "phi": phi}


def intraday_profiles(days: list[dict[str, Any]], weeks: int = 6) -> dict[int, list[float]]:
    """Per weekday: recency-weighted share of daily volume by 30-minute interval."""
    out: dict[int, list[float]] = {}
    for dow in range(7):
        rows = [d for d in days if d["dow"] == dow][-weeks:]
        if not rows:
            out[dow] = [1 / N_INT] * N_INT
            continue
        w = np.array([1.0 + 0.5 * i for i in range(len(rows))])
        shares = np.array([np.array(r["intervals"], dtype=float) / max(r["total"], 1) for r in rows])
        prof = (shares * w[:, None]).sum(axis=0) / w.sum()
        out[dow] = (prof / prof.sum()).tolist()
    return out


def deevent(days: list[dict[str, Any]]) -> tuple[list[float], float | None]:
    """Replace known event days (promotions) by the expected same-weekday level so that they do not distort level/seasonality;
    returns the cleaned totals and the observed event uplift (None when the history has no event)."""
    totals = [float(d["total"]) for d in days]
    uplifts: list[float] = []
    for i, d in enumerate(days):
        if not d.get("event"):
            continue
        peers = [float(days[j]["total"]) for j in range(max(0, i - 35), min(len(days), i + 36)) if j != i and days[j]["dow"] == d["dow"] and not days[j].get("event")]
        if peers:
            expected = float(np.median(peers))
            uplifts.append(float(d["total"]) / expected)
            totals[i] = expected
    return totals, (float(np.mean(uplifts)) if uplifts else None)


def forecast_days(days: list[dict[str, Any]], horizon: int = 7, method: str = "hw", promo_offsets: tuple[int, ...] = ()) -> dict[str, Any]:
    """`days`: history docs sorted by date (each with dow, intervals, total, optional event). Returns daily totals and interval forecasts per future
    day. `promo_offsets` are future day offsets (1 = tomorrow) that carry a planned promotion (uplift learned from past events)."""
    totals, uplift = deevent(days)
    last_dow = days[-1]["dow"]
    params: dict[str, float] = {}
    if method == "hw":
        daily, params = holt_winters(totals, 7, horizon)
    else:
        daily = [float(days[-7 + ((h - 1) % 7)]["total"]) for h in range(1, horizon + 1)]
    profiles = intraday_profiles(days)
    out = []
    for h in range(1, horizon + 1):
        dow = (last_dow + h) % 7
        factor = (uplift or 1.3) if (method == "hw" and h in promo_offsets) else 1.0
        if method == "hw":
            intervals = [daily[h - 1] * factor * p for p in profiles[dow]]
            total = daily[h - 1] * factor
        else:  # seasonal naive on intervals: same weekday last week
            src = days[-7 + ((h - 1) % 7)]
            intervals = [float(v) for v in src["intervals"]]
            total = sum(intervals)
        out.append({"offset": h, "dow": dow, "total": round(total, 1), "intervals": [round(v, 2) for v in intervals], "promo": factor != 1.0})
    return {"method": method, "params": params, "event_uplift": uplift, "days": out}


def _mape(f: list[float], a: list[float], floor: float = 0.0) -> float | None:
    pairs = [(x, y) for x, y in zip(f, a, strict=True) if y > floor]
    return float(np.mean([abs(x - y) / y for x, y in pairs])) if pairs else None


def backtest(days: list[dict[str, Any]], *, origins: tuple[int, ...] = (35, 28, 21, 14), horizon: int = 7, interval_floor: float = 10.0) -> dict[str, Any]:
    """Rolling-origin evaluation. `origins` are the number of trailing days left out of training for each fold; known event days (promotions)
    are excluded from the scores (planners forecast those with an event calendar). WAPE is the primary interval metric because MAPE is
    unstable on low-volume intervals; MAPE is reported for intervals with at least `interval_floor` contacts."""
    folds = []
    for back in origins:
        cut = len(days) - back
        if cut < 21:
            continue
        train, test = days[:cut], days[cut : cut + horizon]
        keep = [i for i, t in enumerate(test) if not t.get("event")]
        res: dict[str, Any] = {"train_days": cut, "test_from": test[0]["date"], "test_to": test[-1]["date"], "event_days_excluded": len(test) - len(keep)}
        for method in ("hw", "naive"):
            fc = forecast_days(train, horizon, method)["days"]
            daily_f, daily_a = [fc[i]["total"] for i in keep], [test[i]["total"] for i in keep]
            inter_f = [v for i in keep for v in fc[i]["intervals"][OPEN_FIRST : OPEN_LAST + 1]]
            inter_a = [v for i in keep for v in test[i]["intervals"][OPEN_FIRST : OPEN_LAST + 1]]
            res[method] = {
                "mape_daily": _mape(daily_f, daily_a), "mape_interval": _mape(inter_f, inter_a, interval_floor),
                "wape_interval": float(sum(abs(x - y) for x, y in zip(inter_f, inter_a, strict=True)) / max(sum(inter_a), 1)),
            }  # fmt: skip
        folds.append(res)
    def mean_of(method: str, k: str) -> float | None:
        values = [f[method][k] for f in folds if f[method][k] is not None]
        return round(float(np.mean(values)), 4) if values else None  # a low-volume queue has no interval with >= `interval_floor` contacts

    agg: dict[str, Any] = {}
    for method in ("hw", "naive"):
        agg[method] = {k: mean_of(method, k) for k in ("mape_daily", "mape_interval", "wape_interval")} if folds else {}
    imp = lambda k: round(100 * (1 - agg["hw"][k] / agg["naive"][k]), 1) if folds and agg["hw"][k] is not None and agg["naive"][k] else None  # noqa: E731
    return {
        "folds": folds, "summary": agg, "interval_floor": interval_floor, "operating_window": "07:00-22:00", "improvement_pct": imp("wape_interval"),
        "improvement_daily_pct": imp("mape_daily"), "targets": {"mape_daily_max": 0.10, "min_improvement_vs_naive_pct": 15},
    }  # fmt: skip


# ------------------------------------------------------------------------------------------------------ planning
def plan_day(
    volumes: list[float], aht_s: float, *, containment: float = 0.3, sl_target: float = 0.8, t_s: float = 120, shrinkage: float = 0.15, max_occupancy: float = 0.88, sl_buffer: float = 0.04,
    ai_aht_s: float = 150.0, aht_uplift_per_10pct: float = 0.02, voice_share: float = 0.5, ai_voice_min_per_contact: float = 3.0,
) -> dict[str, Any]:  # fmt: skip
    """Per interval: human agents required (Erlang-C on the non-contained volume, with a complexity uplift on AHT; planned to the target plus a
    small buffer for variability), scheduled heads incl. shrinkage, and AI capacity (concurrent AI sessions by Little's law, voice minutes) -
    the AI sees every contact first."""
    aht_h = aht_s * (1 + aht_uplift_per_10pct * containment * 10)
    plan_target = min(0.99, sl_target + sl_buffer)
    req, heads, human_vol, ai_conc, ai_minutes = [], [], [], [], []
    deferred = 0.0
    for i, v in enumerate(volumes):
        in_hours = OPEN_FIRST <= i <= OPEN_LAST
        hv = v * (1 - containment) if in_hours else 0.0
        deferred += v * (1 - containment) if not in_hours else 0.0  # out-of-hours human demand: AI-only + next-morning callbacks
        n = agents_required(hv, aht_h, sl_target=plan_target, t_s=t_s, max_occupancy=max_occupancy)
        req.append(n)
        heads.append(math.ceil(n / (1 - shrinkage)) if n else 0)
        human_vol.append(round(hv, 2))
        ai_conc.append(round(v * ai_aht_s / INTERVAL_S, 2))
        ai_minutes.append(round(v * voice_share * ai_voice_min_per_contact, 1))
    paid_h = sum(heads) * 0.5
    return {
        "aht_human_s": round(aht_h, 1), "containment": containment, "human_volume": human_vol, "agents_required": req, "heads_scheduled": heads,
        "ai_concurrent_sessions": ai_conc, "ai_voice_minutes": ai_minutes, "totals": {
            "contacts": round(sum(volumes), 1), "human_contacts": round(sum(human_vol), 1), "ai_contacts": round(sum(volumes) - sum(human_vol) - deferred, 1), "out_of_hours_deferred": round(deferred, 1),
            "agent_hours_required": round(sum(req) * 0.5, 1), "agent_hours_scheduled": round(paid_h, 1), "fte_day_equivalent": round(paid_h / (PAID_H_PER_FTE_WEEK / 5), 1), "peak_agents": max(req) if req else 0,
            "peak_ai_sessions": max(ai_conc) if ai_conc else 0, "ai_voice_minutes": round(sum(ai_minutes), 1),
        },
    }  # fmt: skip


def shift_templates() -> list[dict[str, Any]]:
    """8-hour shifts (16 intervals) starting every 30 minutes from 06:00 to 14:00, one 30-minute break (staggered)."""
    return [{"start": s, "len": 16} for s in range(12, 30)]


def build_schedule(requirement: list[int], *, max_iter: int = 400) -> dict[str, Any]:
    """Greedy set cover: repeatedly add the shift that removes the most uncovered requirement; break offsets are staggered."""
    cover = [0] * N_INT
    deficit = list(requirement)
    shifts: list[dict[str, Any]] = []
    templates = shift_templates()

    def covered(start: int, brk: int) -> list[int]:
        return [i for i in range(start, start + 16) if i < N_INT and i != start + brk]

    for _ in range(max_iter):
        if sum(max(0, d) for d in deficit) == 0:
            break
        brk = 7 + (len(shifts) % 3)
        best, best_gain = None, (0, 0)
        for t in templates:
            idx = covered(t["start"], brk)
            gain = (sum(1 for i in idx if deficit[i] > 0), sum(max(0, deficit[i]) for i in idx))
            if gain > best_gain:
                best, best_gain = (t["start"], brk, idx), gain
        if best is None or best_gain[0] == 0:
            break
        start, brk, idx = best
        for i in idx:
            cover[i] += 1
            deficit[i] -= 1
        shifts.append({"start": start, "break": start + brk})
    grouped: dict[int, int] = {}
    for s in shifts:
        grouped[s["start"]] = grouped.get(s["start"], 0) + 1
    roster = [{"start_interval": k, "start": f"{k // 2:02d}:{30 * (k % 2):02d}", "end": f"{(k + 16) // 2 % 24:02d}:{30 * ((k + 16) % 2):02d}", "agents": v} for k, v in sorted(grouped.items())]
    under = [max(0, r - c) for r, c in zip(requirement, cover, strict=True)]
    over = [max(0, c - r) for r, c in zip(requirement, cover, strict=True)]
    return {"roster": roster, "agents_total": len(shifts), "coverage": cover, "requirement": requirement, "under": under, "over": over, "uncovered_intervals": [i for i, u in enumerate(under) if u > 0], "paid_hours": round(len(shifts) * 7.5, 1)}


def simulate(expected: list[float], seats: list[float], aht_s: float, t_s: float, *, seed: int = 11, days: int = 12) -> dict[str, Any]:
    """Discrete-event simulation (Poisson arrivals, exponential handling, FIFO, infinite patience) of a roster over `days` replications."""
    results = []
    for rep in range(days):
        rng = random.Random(seed * 1000 + rep)
        arrivals: list[float] = []
        for i, lam in enumerate(expected):
            n = max(0, round(rng.gauss(lam, math.sqrt(lam)))) if lam > 30 else _poisson(rng, lam)
            arrivals += [i * INTERVAL_S + rng.random() * INTERVAL_S for _ in range(n)]
        arrivals.sort()
        events: list[tuple[float, int, int]] = [(a, 1, k) for k, a in enumerate(arrivals)] + [(i * INTERVAL_S, 0, -1) for i in range(N_INT)]
        heapq.heapify(events)
        busy, queue, waits, per_int_wait = 0, [], [], [[] for _ in range(N_INT)]
        busy_time, seat_time = 0.0, sum(seats) * INTERVAL_S
        arrive_t: dict[int, float] = {}
        max_q = 0
        seq = len(arrivals) + N_INT + 1
        while events:
            t, kind, ident = heapq.heappop(events)
            cap = int(seats[min(N_INT - 1, int(t // INTERVAL_S))]) if t < N_INT * INTERVAL_S else 0
            if kind == 1:
                arrive_t[ident] = t
                queue.append(ident)
            elif kind == 2:
                busy -= 1
            while queue and busy < cap:
                k = queue.pop(0)
                w = t - arrive_t[k]
                waits.append(w)
                per_int_wait[min(N_INT - 1, int(arrive_t[k] // INTERVAL_S))].append(w)
                svc = rng.expovariate(1 / aht_s)
                busy += 1
                busy_time += svc
                seq += 1
                heapq.heappush(events, (t + svc, 2, seq))
            max_q = max(max_q, len(queue))
            if kind == 0 and t >= N_INT * INTERVAL_S:
                break
        waits += [N_INT * INTERVAL_S - arrive_t[k] + aht_s for k in queue]  # anything still queued at day end counts as a long wait
        sl = sum(1 for w in waits if w <= t_s) / len(waits) if waits else 1.0
        results.append({"sl": sl, "asa": float(np.mean(waits)) if waits else 0.0, "answered": len(waits), "occupancy": busy_time / seat_time if seat_time else 0.0, "max_queue": max_q, "per_interval": per_int_wait})
    sls = [r["sl"] for r in results]
    per_int = []
    for i in range(N_INT):
        allw = [w for r in results for w in r["per_interval"][i]]
        per_int.append(round(sum(1 for w in allw if w <= t_s) / len(allw), 3) if allw else None)
    return {
        "replications": days, "sl_mean": round(float(np.mean(sls)), 4), "sl_min": round(min(sls), 4), "sl_max": round(max(sls), 4), "asa_s": round(float(np.mean([r["asa"] for r in results])), 1),
        "occupancy": round(float(np.mean([r["occupancy"] for r in results])), 3), "max_queue": max(r["max_queue"] for r in results), "answered_per_day": round(float(np.mean([r["answered"] for r in results])), 1), "sl_by_interval": per_int,
    }  # fmt: skip


def _poisson(rng: random.Random, lam: float) -> int:
    if lam <= 0:
        return 0
    limit, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1
