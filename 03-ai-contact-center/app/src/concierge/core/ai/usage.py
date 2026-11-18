"""AI usage meter, price table and the daily budget guard (fails closed)."""

from __future__ import annotations

import json
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import resources
from typing import Any

from .base import BudgetExceededError, Usage


def _load_prices() -> dict[str, Any]:
    with resources.files("concierge.data").joinpath("prices.json").open("r", encoding="utf-8") as fh:
        return json.load(fh)


PRICES = _load_prices()


def today_utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


def estimate_cost(model: str, usage: Usage) -> float:
    """USD at list price. Text tokens and audio tokens are priced separately for realtime models."""
    p = PRICES["models"].get(model)
    if not p:
        return 0.0
    text_in = max(usage.input_tokens - usage.audio_in_tokens - usage.cached_tokens, 0)
    cost = text_in * p.get("in", 0) + usage.cached_tokens * p.get("cached_in", p.get("in", 0))
    cost += max(usage.output_tokens - usage.audio_out_tokens, 0) * p.get("out", 0)
    cost += usage.audio_in_tokens * p.get("audio_in", p.get("in", 0))
    cost += usage.audio_out_tokens * p.get("audio_out", p.get("out", 0))
    return cost / 1_000_000.0


@dataclass
class _Totals:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    audio_in_tokens: int = 0
    audio_out_tokens: int = 0
    audio_seconds: float = 0.0
    cost_usd: float = 0.0


def _pct(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


class UsageMeter:
    """Per-feature / per-model / per-conversation token, audio and cost metering with a daily USD budget cap."""

    def __init__(self, daily_budget_usd: float, repo: Any | None = None, enforce: bool = True) -> None:
        self.daily_budget_usd = daily_budget_usd
        self.repo = repo
        self.enforce = enforce
        self.day = today_utc()
        self.by_model: dict[str, _Totals] = defaultdict(_Totals)
        self.by_feature: dict[str, _Totals] = defaultdict(_Totals)
        self.by_conv: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        self.latency: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=800))
        self.total = _Totals()
        self.blocked = 0
        self._dirty = False
        self._last_flush = 0.0

    # -- budget ------------------------------------------------------------------------------
    def _roll_day(self) -> None:
        today = today_utc()
        if today != self.day:
            self.day = today
            self.by_model.clear()
            self.by_feature.clear()
            self.total = _Totals()
            self.blocked = 0

    def check_budget(self) -> None:
        self._roll_day()
        if self.enforce and self.total.cost_usd >= self.daily_budget_usd:
            self.blocked += 1
            raise BudgetExceededError(self.total.cost_usd, self.daily_budget_usd)

    @property
    def remaining_usd(self) -> float:
        self._roll_day()
        return max(self.daily_budget_usd - self.total.cost_usd, 0.0)

    # -- recording ---------------------------------------------------------------------------
    def record(
        self,
        *,
        model: str,
        feature: str,
        usage: Usage | None = None,
        conv_id: str | None = None,
        latency_ms: float | None = None,
        audio_seconds: float = 0.0,
        extra_cost_usd: float = 0.0,
        simulated: bool = False,
    ) -> float:
        self._roll_day()
        usage = usage or Usage()
        cost = estimate_cost(model, usage) + extra_cost_usd
        if "transcribe" in model and audio_seconds:
            cost += audio_seconds / 60.0 * PRICES["models"].get(model, {}).get("per_minute_usd", 0)
        for bucket in (self.by_model[model], self.by_feature[feature], self.total):
            bucket.calls += 1
            bucket.input_tokens += usage.input_tokens
            bucket.output_tokens += usage.output_tokens
            bucket.audio_in_tokens += usage.audio_in_tokens
            bucket.audio_out_tokens += usage.audio_out_tokens
            bucket.audio_seconds += audio_seconds
            if not simulated:  # offline stub calls never count against the real budget
                bucket.cost_usd += cost
        if conv_id:
            c = self.by_conv[conv_id]
            c["cost_usd"] += cost
            c["input_tokens"] += usage.input_tokens
            c["output_tokens"] += usage.output_tokens
            c["audio_seconds"] += audio_seconds
            c["calls"] += 1
        if latency_ms is not None:
            self.latency[feature].append(latency_ms)
        self._dirty = True
        return cost

    def conversation(self, conv_id: str) -> dict[str, float]:
        return dict(self.by_conv.get(conv_id, {}))

    def forget(self, conv_id: str) -> None:
        self.by_conv.pop(conv_id, None)

    # -- persistence (budget survives restarts) ----------------------------------------------
    async def load(self) -> None:
        if not self.repo:
            return
        doc = await self.repo.get("usage_daily", self.day)
        if doc:
            self.total.cost_usd = float(doc.get("cost_usd", 0.0))
            self.total.calls = int(doc.get("calls", 0))
            self.total.input_tokens = int(doc.get("input_tokens", 0))
            self.total.output_tokens = int(doc.get("output_tokens", 0))
            self.total.audio_seconds = float(doc.get("audio_seconds", 0.0))
            for k, v in (doc.get("by_model") or {}).items():
                self.by_model[k] = _Totals(**v)
            for k, v in (doc.get("by_feature") or {}).items():
                self.by_feature[k] = _Totals(**v)

    async def flush(self, force: bool = False) -> None:
        if not self.repo or not self._dirty:
            return
        if not force and time.time() - self._last_flush < 15:
            return
        self._last_flush = time.time()
        self._dirty = False
        await self.repo.put(
            "usage_daily",
            {
                "id": self.day,
                "day": self.day,
                "cost_usd": round(self.total.cost_usd, 6),
                "calls": self.total.calls,
                "input_tokens": self.total.input_tokens,
                "output_tokens": self.total.output_tokens,
                "audio_seconds": round(self.total.audio_seconds, 2),
                "by_model": {k: v.__dict__ for k, v in self.by_model.items()},
                "by_feature": {k: v.__dict__ for k, v in self.by_feature.items()},
            },
            ttl=60 * 60 * 24 * 120,
        )

    # -- views -------------------------------------------------------------------------------
    def snapshot(self) -> dict[str, Any]:
        self._roll_day()
        return {
            "day": self.day,
            "budget_usd": self.daily_budget_usd,
            "spent_usd": round(self.total.cost_usd, 4),
            "remaining_usd": round(self.remaining_usd, 4),
            "budget_pct": round(100 * self.total.cost_usd / self.daily_budget_usd, 1) if self.daily_budget_usd else 0,
            "status": "exhausted" if self.remaining_usd <= 0 else ("warning" if self.total.cost_usd > 0.8 * self.daily_budget_usd else "ok"),
            "blocked_calls": self.blocked,
            "calls": self.total.calls,
            "tokens": {"input": self.total.input_tokens, "output": self.total.output_tokens},
            "audio_seconds": round(self.total.audio_seconds, 1),
            "by_model": {k: {**v.__dict__, "cost_usd": round(v.cost_usd, 5)} for k, v in self.by_model.items()},
            "by_feature": {
                k: {
                    **v.__dict__,
                    "cost_usd": round(v.cost_usd, 5),
                    "latency_p50_ms": round(_pct(list(self.latency.get(k, [])), 0.5), 1),
                    "latency_p95_ms": round(_pct(list(self.latency.get(k, [])), 0.95), 1),
                }
                for k, v in self.by_feature.items()
            },
            "price_table": {"source": PRICES["source"], "retrieved": PRICES["retrieved"]},
        }

    def latency_stats(self, feature: str) -> dict[str, float]:
        vals = list(self.latency.get(feature, []))
        return {"n": len(vals), "p50": round(_pct(vals, 0.5), 1), "p95": round(_pct(vals, 0.95), 1)}
