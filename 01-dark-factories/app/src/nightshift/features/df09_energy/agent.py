"""Energy & Sustainability agent (DF-09): ToU/carbon-aware load shifting of shiftable utilities, deferral of deferrable jobs during
price spikes and idle-standby of machines with no work."""

from __future__ import annotations

from typing import Any

from nightshift.features.df04_swarm.core import Agent, Blackboard, WorldView
from nightshift.plant.models import Action, Proposal


class EnergyAgent(Agent):
    name = "energy"
    role = "Energy & Sustainability"
    decision_classes = ("energy.load_shift", "energy.defer_job", "energy.standby")

    def __init__(self) -> None:
        super().__init__()
        self.idle_since: dict[str, int] = {}
        self.standby: set[str] = set()
        self.deferred: dict[str, int] = {}
        self.last_shift_t = -(10**9)
        self.plan: dict[str, Any] = {}

    def _prices(self, w: WorldView, hours: int = 24) -> list[tuple[int, float]]:
        return [(w.t + m, w.tariff(w.t + m)) for m in range(0, hours * 60, 30)]

    def perceive(self, w: WorldView, board: Blackboard) -> list[Proposal]:
        props: list[Proposal] = []
        prices = self._prices(w)
        vals = sorted(p for _, p in prices)
        lo, med = vals[0] * 1.01, vals[len(vals) // 2]
        base_now = w._p.tariff_at(w.t, with_spike=False)
        spike = w.price_now > 1.6 * base_now
        self.plan = {
            "price_now": round(w.price_now, 4),
            "carbon_now": round(w.carbon_now),
            "spike": spike,
            "lo": round(lo, 4),
            "hi": round(med, 4),
        }
        # ---- 1. buffer load shifting on utilities (compressor / chiller)
        utilities = [u for u in w.ids("COMP", "CHILL") if u in w.shifts]
        need = [
            u
            for u in utilities
            if not w.shifts[u]["active"]
            or w.shifts[u]["until"] < w.t + 60
            or (spike and w.shifts[u]["hi"] > w.price_now * 0.9)
        ]
        if need and w.t - self.last_shift_t >= 30 and med > lo * 1.25:
            hi = min(med, w.price_now * 0.95) if spike else med
            cap = sum(w.shifts[u]["cap"] for u in need)
            eff = w.A["energy"]["shift_efficiency"]
            spread = max(0.0, (max(p for _, p in prices) if spike else med) - lo)
            value = cap * eff * spread * (3.0 if spike else 1.0)
            if value < 2.0:
                need = []
        if need and w.t - self.last_shift_t >= 30 and med > lo * 1.25:
            self.last_shift_t = w.t
            props.append(
                self.prop(
                    w,
                    "energy.load_shift",
                    f"Shift {' + '.join(need)} load into the cheap tariff window",
                    [
                        Action(
                            "load_shift",
                            {
                                "utility": u,
                                "active": True,
                                "until_t": w.t + 12 * 60,
                                "hi": round(hi, 4),
                                "lo": round(lo, 4),
                            },
                            u,
                        )
                        for u in need
                    ],
                    f"{'Spot-price spike (' + format(w.price_now, '.2f') + ' EUR/kWh vs ' + format(base_now, '.2f') + ' normal). ' if spike else ''}"
                    f"Pre-charge the air receiver / chilled-water buffer when power is <= {lo:.3f} EUR/kWh and discharge it above {hi:.3f}; "
                    f"{cap:.0f} kWh of thermal/pneumatic storage with {int(eff * 100)} % round-trip efficiency, no effect on production.",
                    assets=list(need),
                    claims=[f"util:{u}:shift" for u in need],
                    risk=0.02,
                    cost_eur=0.0,
                    expires_t=w.t + 60,
                    priority=2,
                    horizon_min=720,
                    impact={"energy_eur": round(value, 0)},
                    counterfactual={"spread_eur_per_kwh": round(spread, 3), "buffer_kwh": cap},
                )
            )
        # ---- 2. defer deferrable jobs while power is expensive
        if spike or w.price_now > 1.5 * vals[0]:
            resume = next((t for t, p in prices if p <= 1.15 * vals[0] or (spike and p <= 1.3 * base_now)), w.t + 180)
            resume = int(min(resume, w.t + 8 * 60))
            for o in w.open_orders():
                if (
                    o.deferrable
                    and o.hold_until <= w.t
                    and o.ops[0].taken == 0
                    and o.due - resume > 6 * 60
                    and o.id not in self.deferred
                    and resume - w.t >= 30
                ):
                    stage = o.ops[0].stage
                    kw = w.spec(w.pools[stage][0]).params["power_kw"]["RUN"]
                    kwh = o.qty * o.ops[0].cycle / 60 * kw
                    gain = kwh * max(0.0, w.price_now - vals[0])
                    self.deferred[o.id] = resume
                    props.append(
                        self.prop(
                            w,
                            "energy.defer_job",
                            f"Defer {o.id} ({o.sku}) until power is cheaper",
                            [Action("set_hold", {"order": o.id, "until_t": resume}, None)],
                            f"{o.id} is a deferrable replenishment order with {(o.due - w.t) / 60:.0f} h to its due date; holding it for {(resume - w.t) / 60:.1f} h moves ~{kwh:.0f} kWh "
                            f"from {w.price_now:.2f} to ~{vals[0]:.2f} EUR/kWh power and still leaves {(o.due - resume) / 60:.0f} h of slack.",
                            assets=[],
                            claims=[f"order:{o.id}:hold"],
                            risk=0.06,
                            cost_eur=0.0,
                            expires_t=w.t + 30,
                            impact={"energy_eur": round(gain, 0)},
                            counterfactual={"kwh_moved": round(kwh), "slack_after_h": round((o.due - resume) / 60, 1)},
                        )
                    )
                    break
        # ---- 3. standby for machines with nothing to do
        idle_now = []
        for a in w.ids("CNC", "PRESS", "ASM", "TEST", "PACK"):
            st = w.asset(a)
            if st.state == "IDLE" and not st.queue and not st.safe_stop and a not in self.standby:
                self.idle_since.setdefault(a, w.t)
                if w.t - self.idle_since[a] >= 10:
                    stage = w.spec(a).stage
                    pool_work = any(
                        op.finished_t is None and op.stage == stage and op.assigned is None
                        for o in w.open_orders()
                        for op in o.ops
                    )
                    if not pool_work:
                        idle_now.append(a)
            else:
                self.idle_since.pop(a, None)
        self.standby = {a for a in self.standby if w.asset(a).state == "IDLE"}
        if idle_now:
            sel = idle_now[:4]
            saved = sum(0.75 * w.spec(a).params["power_kw"]["IDLE"] for a in sel) * 0.5 * w.price_now
            self.standby.update(sel)
            props.append(
                self.prop(
                    w,
                    "energy.standby",
                    f"Idle standby for {', '.join(sel)}",
                    [Action("set_standby", {"asset": a, "on": True}, a) for a in sel],
                    f"{', '.join(sel)} have been idle >20 min with no pending work for their stage; standby cuts their draw by 75 % and they wake in ~1 min when work arrives.",
                    assets=sel,
                    claims=[f"standby:{a}" for a in sel],
                    risk=0.05,
                    cost_eur=0.0,
                    expires_t=w.t + 30,
                    impact={"energy_eur": round(saved, 1)},
                )
            )
        return props

    def summary(self, w: WorldView) -> dict[str, Any]:
        plant = w._p
        shifts = [
            {"utility": u, **{k: round(v, 3) if isinstance(v, float) else v for k, v in s.items()}}
            for u, s in w.shifts.items()
        ]
        fc = [{"t": t, "price": round(p, 4), "carbon": round(w.carbon(t))} for t, p in self._prices(w, 24)]
        return {
            "plan": self.plan,
            "shifts": shifts,
            "forecast": fc,
            "standby": sorted(self.standby),
            "deferred": self.deferred,
            "price_now": round(w.price_now, 4),
            "carbon_now": round(w.carbon_now),
            "total_kw": round(plant.total_kw, 1),
            "saved_eur": round(sum(s["saved_eur"] for s in w.shifts.values()), 2),
        }
