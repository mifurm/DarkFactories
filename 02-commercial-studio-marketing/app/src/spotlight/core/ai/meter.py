"""AI usage meter (tokens / images / TTS characters / render seconds -> USD) and the budget guard (CS-15)."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

from ...errors import BudgetExceeded
from ...i18n import t
from ...util import new_id, now_iso, today_utc
from .base import AICtx, current_ctx
from .pricing import AGENCY_BASELINE_PER_ASSET_USD, PRICES_AS_OF

AlertFn = Callable[[str, dict[str, Any]], Awaitable[None]]
ALERT_THRESHOLDS = (0.8, 1.0)


def _usd(v: float) -> str:
    return f"${v:.2f}" if v >= 0.1 or v == 0 else f"${v:.4f}"


class UsageMeter:
    def __init__(self, repo: Any, simulated: bool = False) -> None:
        self.repo = repo
        self.simulated = simulated
        self._loaded_days: set[str] = set()
        self._day_total: dict[str, float] = defaultdict(float)
        self._day_events: dict[str, int] = defaultdict(int)
        self._campaign_total: dict[str, float] = {}
        self._lock = asyncio.Lock()
        self.calls_by_kind: dict[str, int] = defaultdict(int)  # in-process counters (for /api/ops/metrics)

    async def _ensure_day(self, day: str) -> None:
        if day in self._loaded_days:
            return
        async with self._lock:
            if day in self._loaded_days:
                return
            rows = await self.repo.query("usage", pk=day)
            self._day_total[day] = sum(float(r.get("cost_usd", 0)) for r in rows)
            self._day_events[day] = len(rows)
            self._loaded_days.add(day)

    async def today_total(self) -> float:
        day = today_utc()
        await self._ensure_day(day)
        return round(self._day_total[day], 6)

    async def campaign_total(self, campaign_id: str) -> float:
        if campaign_id not in self._campaign_total:
            rows = await self.repo.query("usage", {"campaign_id": campaign_id})
            self._campaign_total[campaign_id] = sum(float(r.get("cost_usd", 0)) for r in rows)
        return round(self._campaign_total[campaign_id], 6)

    async def record(
        self,
        *,
        kind: str,
        model: str,
        units: dict[str, Any],
        cost_usd: float,
        cached: bool = False,
        ctx: AICtx | None = None,
    ) -> dict[str, Any]:
        ctx = ctx or current_ctx()
        day = today_utc()
        await self._ensure_day(day)
        cost = 0.0 if cached else round(float(cost_usd), 6)
        event = {
            "id": new_id("use"),
            "pk": day,
            "type": "usage",
            "ts": now_iso(),
            "kind": kind,
            "model": model,
            "units": units,
            "cost_usd": cost,
            "feature": ctx.feature,
            "campaign_id": ctx.campaign_id,
            "ref": ctx.ref,
            "cached": cached,
            "simulated": self.simulated,
        }
        await self.repo.upsert("usage", event)
        self._day_total[day] += cost
        self._day_events[day] += 1
        self.calls_by_kind[kind] += 1
        if ctx.campaign_id and ctx.campaign_id in self._campaign_total:
            self._campaign_total[ctx.campaign_id] += cost
        elif ctx.campaign_id:
            await self.campaign_total(ctx.campaign_id)
        return event

    async def events(self, day: str | None = None, campaign_id: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
        where = {"campaign_id": campaign_id} if campaign_id else None
        rows = await self.repo.query("usage", where, pk=day if not campaign_id else None, order_by="ts", desc=True, limit=limit)
        return rows

    async def summary(self, day: str | None = None, campaign_id: str | None = None) -> dict[str, Any]:
        day = day or today_utc()
        rows = await self.events(day=day, campaign_id=campaign_id, limit=5000)
        by_kind: dict[str, dict[str, Any]] = {}
        by_feature: dict[str, float] = defaultdict(float)
        by_campaign: dict[str, float] = defaultdict(float)
        cached_hits = 0
        for r in rows:
            k = by_kind.setdefault(r["kind"], {"calls": 0, "cost_usd": 0.0, "cached": 0})
            k["calls"] += 1
            k["cost_usd"] = round(k["cost_usd"] + r.get("cost_usd", 0), 6)
            if r.get("cached"):
                k["cached"] += 1
                cached_hits += 1
            if r.get("feature"):
                by_feature[r["feature"]] += r.get("cost_usd", 0)
            if r.get("campaign_id"):
                by_campaign[r["campaign_id"]] += r.get("cost_usd", 0)
        return {
            "day": day,
            "total_usd": round(sum(r.get("cost_usd", 0) for r in rows), 6),
            "events": len(rows),
            "cached_hits": cached_hits,
            "by_kind": by_kind,
            "by_feature": {k: round(v, 6) for k, v in by_feature.items()},
            "by_campaign": {k: round(v, 6) for k, v in by_campaign.items()},
            "simulated_prices": self.simulated,
            "prices_as_of": PRICES_AS_OF,
            "pricing_note": t("cost.pricing_note"),
        }


class BudgetGuard:
    """Fails closed: refuses generation when the daily / per-campaign cap would be exceeded."""

    def __init__(self, meter: UsageMeter, repo: Any, daily_cap: float, campaign_cap: float, on_alert: AlertFn | None = None) -> None:
        self.meter = meter
        self.repo = repo
        self.daily_cap = daily_cap
        self.campaign_cap = campaign_cap
        self.on_alert = on_alert
        self._alerted: set[str] = set()
        self.refusals = 0

    async def _campaign(self, campaign_id: str) -> dict[str, Any] | None:
        return await self.repo.get("campaigns", campaign_id, pk=campaign_id)

    async def caps(self, campaign_id: str | None = None) -> dict[str, Any]:
        spent_today = await self.meter.today_total()
        out: dict[str, Any] = {
            "daily_cap_usd": self.daily_cap,
            "spent_today_usd": spent_today,
            "daily_remaining_usd": round(max(0.0, self.daily_cap - spent_today), 6),
            "guard_active": True,
        }
        if campaign_id:
            camp = await self._campaign(campaign_id)
            cap = float((camp or {}).get("budget_cap_usd") or self.campaign_cap)
            spent = await self.meter.campaign_total(campaign_id)
            out.update(
                campaign_cap_usd=cap,
                campaign_spent_usd=spent,
                campaign_remaining_usd=round(max(0.0, cap - spent), 6),
                premium_approved=bool((camp or {}).get("premium_approved")),
            )
        return out

    async def authorize(self, est_cost: float, *, kind: str, model: str = "", premium: bool = False) -> None:
        ctx = current_ctx()
        spent_today = await self.meter.today_total()
        if spent_today + est_cost > self.daily_cap + 1e-9:
            self.refusals += 1
            await self._maybe_alert("daily:" + today_utc(), self.daily_cap, self.daily_cap)
            raise BudgetExceeded(
                f"Daily AI budget reached: {_usd(spent_today)} of {_usd(self.daily_cap)} spent today (UTC); "
                f"this {kind} call (~{_usd(est_cost)}) would exceed the cap. Generation is paused (fails closed).",
                code="daily_budget_exceeded",
                hint="The cap resets at 00:00 UTC, or an Admin can raise DAILY_AI_BUDGET_USD.",
                details={"spent_today_usd": spent_today, "cap_usd": self.daily_cap, "estimated_usd": round(est_cost, 4)},
                params={"spent": spent_today, "cap": self.daily_cap, "call": kind, "est": est_cost},
            )
        if ctx.campaign_id:
            camp = await self._campaign(ctx.campaign_id)
            cap = float((camp or {}).get("budget_cap_usd") or self.campaign_cap)
            spent = await self.meter.campaign_total(ctx.campaign_id)
            if spent + est_cost > cap + 1e-9:
                self.refusals += 1
                await self._maybe_alert("campaign:" + ctx.campaign_id, cap, cap)
                raise BudgetExceeded(
                    f"Campaign AI cap reached: {_usd(spent)} of {_usd(cap)} spent on this campaign; "
                    f"this {kind} call (~{_usd(est_cost)}) would exceed it.",
                    code="campaign_budget_exceeded",
                    hint="A Brand Manager can raise the campaign cap in the Cost Meter.",
                    details={"campaign_spent_usd": spent, "cap_usd": cap, "estimated_usd": round(est_cost, 4)},
                    params={"spent": spent, "cap": cap, "call": kind, "est": est_cost},
                )
            if premium and not (ctx.premium_ok or (camp or {}).get("premium_approved")):
                self.refusals += 1
                raise BudgetExceeded(
                    f"Premium ({kind}, hero quality) generation needs approval: premium calls cost up to ~{_usd(est_cost)} each.",
                    code="premium_requires_approval",
                    hint="Ask a Brand Manager to approve premium generation for this campaign (Cost Meter).",
                    params={"call": kind, "est": est_cost},
                )
            await self._maybe_alert("campaign:" + ctx.campaign_id, spent + est_cost, cap)
        elif premium and not ctx.premium_ok:
            self.refusals += 1
            raise BudgetExceeded("Premium generation needs an approved campaign context.", code="premium_requires_approval", key="err.premium_requires_approval.no_campaign")
        await self._maybe_alert("daily:" + today_utc(), spent_today + est_cost, self.daily_cap)

    async def _maybe_alert(self, scope: str, spent: float, cap: float) -> None:
        if cap <= 0 or not self.on_alert:
            return
        for th in ALERT_THRESHOLDS:
            key = f"{scope}:{th}"
            if spent >= cap * th and key not in self._alerted:
                self._alerted.add(key)
                await self.on_alert("budget.alert", {"scope": scope, "threshold": th, "spent_usd": round(spent, 4), "cap_usd": cap})


def cost_per_approved_asset(total_spend: float, approved_assets: int, baseline: float = AGENCY_BASELINE_PER_ASSET_USD) -> dict[str, Any]:
    per = (total_spend / approved_assets) if approved_assets else None
    return {
        "ai_spend_usd": round(total_spend, 4),
        "approved_assets": approved_assets,
        "cost_per_approved_asset_usd": round(per, 4) if per is not None else None,
        "agency_baseline_per_asset_usd": baseline,
        "baseline_note": t("cost.baseline_note"),
        "savings_pct": round((1 - per / baseline) * 100, 2) if per is not None and baseline else None,
    }
