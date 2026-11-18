"""AI usage meter (tokens -> US$ estimate) with a daily budget guard that fails closed."""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

# USD per 1M tokens. Planning assumptions (list-price style, deliberately on the high side so the guard is conservative).
# Override with a JSON-free approach: edit here or set the daily cap; see REPORT for how the cap behaves.
PRICES_PER_M: dict[str, tuple[float, float]] = {
    "chat": (0.75, 4.50),  # gpt-5.4-mini class
    "reasoning": (2.50, 15.00),  # gpt-5.4 class
}


class BudgetExceeded(RuntimeError):
    """Raised when the daily AI budget is exhausted; callers must fall back to deterministic output."""


@dataclass
class _Day:
    day: str
    calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost: float = 0.0
    errors: int = 0
    blocked: int = 0
    by_feature: dict[str, dict[str, float]] = field(default_factory=lambda: defaultdict(lambda: defaultdict(float)))
    by_model: dict[str, dict[str, float]] = field(default_factory=lambda: defaultdict(lambda: defaultdict(float)))


def _today() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


class UsageMeter:
    def __init__(self, daily_budget_usd: float, clock=_today) -> None:
        self.daily_budget_usd = float(daily_budget_usd)
        self._clock = clock
        self._day = _Day(day=clock())
        self._last_persist = 0.0
        self.recent: list[dict[str, Any]] = []

    def _roll(self) -> _Day:
        d = self._clock()
        if d != self._day.day:
            self._day = _Day(day=d)
        return self._day

    @staticmethod
    def estimate(role: str, tokens_in: int, tokens_out: int) -> float:
        pin, pout = PRICES_PER_M.get(role, PRICES_PER_M["chat"])
        return tokens_in / 1e6 * pin + tokens_out / 1e6 * pout

    def guard(self, feature: str = "misc") -> None:
        day = self._roll()
        if day.cost >= self.daily_budget_usd:
            day.blocked += 1
            raise BudgetExceeded(
                f"Daily AI budget of US${self.daily_budget_usd:.2f} reached (spent US${day.cost:.4f}); "
                "AI features fall back to deterministic output until 00:00 UTC."
            )

    def record(
        self,
        feature: str,
        role: str,
        model: str,
        tokens_in: int,
        tokens_out: int,
        latency_ms: float = 0.0,
        ok: bool = True,
    ) -> float:
        day = self._roll()
        cost = self.estimate(role, tokens_in, tokens_out)
        day.calls += 1
        day.tokens_in += tokens_in
        day.tokens_out += tokens_out
        day.cost += cost
        if not ok:
            day.errors += 1
        for bucket, key in ((day.by_feature, feature), (day.by_model, model)):
            b = bucket[key]
            b["calls"] += 1
            b["tokens_in"] += tokens_in
            b["tokens_out"] += tokens_out
            b["cost_usd"] += cost
            b["latency_ms"] += latency_ms
        self.recent.append(
            {
                "t": time.time(),
                "feature": feature,
                "model": model,
                "in": tokens_in,
                "out": tokens_out,
                "usd": round(cost, 6),
                "ms": round(latency_ms, 1),
                "ok": ok,
            }
        )
        del self.recent[:-50]
        return cost

    @property
    def blocked(self) -> bool:
        return self._roll().cost >= self.daily_budget_usd

    def snapshot(self) -> dict[str, Any]:
        d = self._roll()
        return {
            "day": d.day,
            "calls": d.calls,
            "errors": d.errors,
            "blocked_calls": d.blocked,
            "tokens_in": d.tokens_in,
            "tokens_out": d.tokens_out,
            "est_cost_usd": round(d.cost, 6),
            "daily_budget_usd": self.daily_budget_usd,
            "remaining_usd": round(max(0.0, self.daily_budget_usd - d.cost), 6),
            "budget_blocked": d.cost >= self.daily_budget_usd,
            "by_feature": {k: {kk: round(vv, 6) for kk, vv in v.items()} for k, v in d.by_feature.items()},
            "by_model": {k: {kk: round(vv, 6) for kk, vv in v.items()} for k, v in d.by_model.items()},
            "prices_per_million_tokens_usd": {k: {"in": v[0], "out": v[1]} for k, v in PRICES_PER_M.items()},
            "price_basis": "planning assumption (list-price style); verify against the Azure Retail Prices API",
            "recent": self.recent[-10:],
        }

    # persistence of the running day so a restart does not reset the cap
    def to_doc(self) -> dict[str, Any]:
        d = self._roll()
        return {
            "id": f"usage-{d.day}",
            "pk": "usage",
            "day": d.day,
            "calls": d.calls,
            "tokens_in": d.tokens_in,
            "tokens_out": d.tokens_out,
            "cost": d.cost,
            "errors": d.errors,
            "blocked": d.blocked,
        }

    def load_doc(self, doc: dict[str, Any] | None) -> None:
        if not doc or doc.get("day") != self._roll().day:
            return
        d = self._day
        d.calls, d.tokens_in, d.tokens_out = (
            int(doc.get("calls", 0)),
            int(doc.get("tokens_in", 0)),
            int(doc.get("tokens_out", 0)),
        )
        d.cost, d.errors, d.blocked = float(doc.get("cost", 0.0)), int(doc.get("errors", 0)), int(doc.get("blocked", 0))

    def should_persist(self, every_s: float = 20.0) -> bool:
        now = time.monotonic()
        if now - self._last_persist >= every_s:
            self._last_persist = now
            return True
        return False
