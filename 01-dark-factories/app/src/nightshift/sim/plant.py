"""Deterministic discrete-time simulator of a discrete-manufacturing plant (1 tick = 1 simulated minute).

State machine per asset (RUN/IDLE/SETUP/DOWN/MAINT/BLOCKED/STARVED), stochastic degradation (hidden health index), sensors,
quality (defect probability from process shift), energy by state with ToU tariff and carbon curves, materials and AMR kit
feeding, a fault-injection library, snapshot/restore/fork and a control API used by agents and humans.

Determinism: every asset owns a seeded stream that always consumes one row per tick, so two runs with the same seed and the
same fault schedule see identical noise (common random numbers) no matter what the controllers do.
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from nightshift.sim.config import PRODUCTION_TYPES, STATES, AssetSpec, PlantConfig, parse_window
from nightshift.sim.rng import Streams
from nightshift.sim.store import TimeSeriesStore

SQRT2 = math.sqrt(2.0)
EPS = 1e-9
CONTROL_ACTIONS = (
    "set_speed",
    "set_setpoint",
    "schedule_maintenance",
    "cancel_maintenance",
    "reassign_op",
    "resequence",
    "set_hold",
    "set_amr_priority",
    "load_shift",
    "safe_stop",
    "resume",
    "set_inline_inspect",
    "tool_change",
    "expedite_material",
    "reorder_material",
    "set_priority",
    "clear_jam",
    "set_recipe",
    "set_safety_mode",
    "stage_spare",
    "expedite_order",
    "apply_plan",
    "set_standby",
)


class ActionRejected(ValueError):
    """Raised by the control API when an action is physically or logically impossible."""


def _tail(x: float) -> float:
    return 0.5 * math.erfc(x / SQRT2)


def p_defect(shift: float, k: float = 5.0) -> float:
    """Probability of an out-of-tolerance part when the process mean is ``shift`` sigma off-centre (tolerance +/- k sigma)."""
    s = abs(shift)
    return _tail(k - s) + _tail(k + s)


def in_window(mod: int, a: int, b: int) -> bool:
    return a <= mod < b if a <= b else (mod >= a or mod < b)


@dataclass
class Op:
    stage: str
    cycle: float
    family: str
    cum_cost: float
    taken: float = 0.0
    done: float = 0.0
    scrap: float = 0.0
    lat: float = 0.0
    assigned: str | None = None
    planned: bool = (
        False  # True when a planner (agent or human) pinned the op to a machine; pulled ops return to the pool
    )
    started_t: int | None = None
    finished_t: int | None = None


@dataclass
class Order:
    id: str
    sku: str
    qty: int
    due: int
    priority: int
    released: int
    ops: list[Op]
    margin: float
    rush: bool = False
    deferrable: bool = False
    hold_until: int = 0
    completed_t: int | None = None
    escapes: float = 0.0
    expedited: bool = False


@dataclass
class WorkOrder:
    id: str
    asset: str
    start_t: int
    duration: int
    kind: str  # planned | corrective
    reason: str
    spare: str | None = None
    tool: bool = False
    status: str = "scheduled"  # scheduled | active | done | cancelled
    created_t: int = 0
    created_by: str = "system"


@dataclass
class Fault:
    id: str
    kind: str
    target: str
    params: dict[str, Any]
    start_t: int
    end_t: int | None = None
    status: str = "active"
    source: str = "console"


@dataclass
class AssetState:
    id: str
    state: str = "IDLE"
    reason: str = ""
    health: float = 0.9
    vib0: float = 1.0
    temp: float = 40.0
    tool_wear: float = 0.0
    thermal: float = 0.0
    qdrift: float = 0.0
    offset: float = 0.0
    speed: float = 100.0
    setup_left: float = 0.0
    repair_left: float = 0.0
    maint_left: float = 0.0
    last_family: str | None = None
    current: tuple[str, int] | None = None
    queue: list[tuple[str, int]] = field(default_factory=list)
    wait_min: int = 0
    op_since: int = 0
    kit: float = 100.0
    kit_requested: bool = False
    safe_stop: bool = False
    standby: bool = False
    inline_inspect: bool = False
    tool_count: float = 0.0
    next_qc_t: int = 0
    qc_fix_t: int | None = None
    battery: float = 90.0
    task: list[Any] | None = None
    flags: dict[str, Any] = field(default_factory=dict)
    recipe: dict[str, float] = field(default_factory=dict)
    sens: dict[str, float] = field(default_factory=dict)
    power_kw: float = 0.0
    mins: dict[str, float] = field(default_factory=lambda: {s: 0.0 for s in STATES})
    units: float = 0.0
    good: float = 0.0
    scrap: float = 0.0
    kwh: float = 0.0
    downtime_unplanned: float = 0.0
    planned_maint: float = 0.0
    safety_stop_min: float = 0.0
    failures: int = 0
    repair_total: float = 0.0
    last_failure_t: int | None = None
    last_maint_t: int = 0
    ideal_min: float = 0.0  # minutes of ideal-rate production (for Performance)
    loss: dict[str, float] = field(default_factory=dict)  # minutes lost by "STATE:reason" (RCA / loss Pareto)


class Plant:
    """One simulated plant. Pure state + deterministic ``step()``; no I/O, safe to deep-copy (fork) at any time."""

    def __init__(
        self, cfg: PlantConfig, seed: int = 20261117, *, chaos_per_day: float = 0.0, initial_orders: int | None = None
    ) -> None:
        self.cfg = cfg
        self.A = cfg.assumptions
        self.seed = seed
        self.t = 0
        self.start_dt = datetime.fromisoformat(self.A["time"]["start"])
        self.streams = Streams(seed ^ (hash_plant(cfg.plant_id) & 0xFFFF))
        self.chaos_per_day = chaos_per_day
        self.events: list[dict[str, Any]] = []
        self.safety_mode = "hardwired"  # "agent" = verified remote restart + adaptive slow-down
        self.manual_qc = True  # periodic manual inspection rounds (replaced by SPC when the Quality agent is active)
        self.dispatch_rule = "fifo"  # pool pull rule when a machine has nothing planned: "fifo" (MES default) or "plan" (priority class, then FIFO)
        self.assets: dict[str, AssetState] = {}
        self.orders: dict[str, Order] = {}
        self.order_seq = 0
        self.work_orders: dict[str, WorkOrder] = {}
        self.wo_seq = 0
        self.faults: list[Fault] = []
        self.fault_seq = 0
        self.pending_faults: list[tuple[int, str, dict[str, Any]]] = []
        self.price_spike: list[float] = [1.0, 0.0]  # multiplier, until_t
        self.zones: dict[str, dict[str, float]] = {z: {"occ": 0.0, "wait": 0.0} for z in cfg.zones()}
        self.shifts: dict[str, dict[str, Any]] = {}
        self.pool_q: dict[str, list[tuple[str, int]]] = {s: [] for s in cfg.pools}
        self.amr_priority: dict[str, float] = {}
        self.amr_requests: list[list[Any]] = []
        self.lots: dict[str, dict[str, Any]] = {}
        self.acc: dict[str, float] = {
            k: 0.0
            for k in (
                "units_good",
                "units_total",
                "scrap_units",
                "scrap_cost",
                "escapes",
                "escape_cost",
                "energy_kwh",
                "energy_cost",
                "co2_kg",
                "downtime_unplanned_min",
                "downtime_loss_eur",
                "orders_completed",
                "orders_on_time",
                "orders_in_full",
                "tardiness_min",
                "tardiness_eur",
                "revenue",
                "maintenance_cost",
                "expedite_cost",
                "safety_stop_min",
                "peak_kw",
            )
        }
        self.history: list[tuple[int, dict[str, Any]]] = []
        self.price_now = 0.0
        self.carbon_now = 0.0
        self.total_kw = 0.0
        self._kw_window: list[float] = []
        self._build_assets()
        keys = [(a.id, m) for a in cfg.assets for m in a.sensors] + [
            ("plant", "power_kw"),
            ("plant", "tariff_eur_kwh"),
            ("plant", "carbon_g_kwh"),
        ]
        self.store = TimeSeriesStore(keys)
        self._row = [float("nan")] * len(keys)
        self._ridx = {a.id: {m: self.store.index[(a.id, m)] for m in a.sensors} for a in cfg.assets}
        self._ridx["plant"] = {
            m: self.store.index[("plant", m)] for m in ("power_kw", "tariff_eur_kwh", "carbon_g_kwh")
        }
        self._nan_idx = [i for (aid, m), i in self.store.index.items() if m in ("dim_mm", "part_weight_g", "torque_nm")]
        self._zone_members = cfg.zones()
        self._prod_ids = [a.id for a in cfg.assets if a.type in PRODUCTION_TYPES]
        self._amr_ids = [a.id for a in cfg.assets if a.type == "AMR"]
        self._utils = {a.type: a.id for a in cfg.assets if a.type in ("COMP", "CHILL")}
        self._planned = [parse_window(w) for w in self.A["calendar"]["planned_windows"]]
        e = self.A["energy"]
        self._tariff = e["tariff_eur_per_kwh"]
        self._off = parse_window(e["tariff_hours"]["offpeak"])
        self._peak = parse_window(e["tariff_hours"]["peak"])
        self.inventory = {
            k: dict(v, on_order=[], delay_until=0.0, delay_min=0.0) for k, v in self.A["materials"].items()
        }
        self.spares = {k: dict(v, on_order=[]) for k, v in self.A["spares"].items()}
        for u, uid in self._utils.items():
            buf = self.A["asset_types"][u]["buffer"]
            self.shifts[uid] = {
                "active": False,
                "soc": 0.0,
                "cap": buf["capacity_kwh"],
                "discharge_kw": buf["discharge_kw"],
                "charge_kw": buf["charge_kw"],
                "hi": 9.9,
                "lo": 0.0,
                "until": 0,
                "shifted_kwh": 0.0,
                "saved_eur": 0.0,
            }
        for _ in range(self.A["orders"]["initial_orders"] if initial_orders is None else initial_orders):
            self._new_order(initial=True)
        self._snapshot_history()

    # ------------------------------------------------------------------ construction
    def _build_assets(self) -> None:
        g = self.streams.generator("init")
        for spec in self.cfg.assets:
            st = AssetState(id=spec.id)
            st.health = 1.0 if spec.type == "WH" else float(g.uniform(0.82, 0.96))
            st.vib0 = float(g.uniform(0.8, 1.4))
            st.temp = 38.0 + float(g.uniform(0, 4))
            st.kit = float(g.uniform(60, 110))
            st.battery = float(g.uniform(60, 95))
            st.next_qc_t = int(g.uniform(0, 120))
            st.state = "RUN" if spec.type in ("WH", "COMP", "CHILL") else "IDLE"
            if spec.type == "PRESS":
                st.recipe = {"inj_speed": 50.0, "melt_temp_c": 240.0, "cool_s": 14.0}
            self.assets[spec.id] = st

    # ------------------------------------------------------------------ calendar & environment
    @property
    def now(self) -> datetime:
        return self.start_dt + timedelta(minutes=self.t)

    def minute_of_day(self, t: int | None = None) -> int:
        d = self.start_dt + timedelta(minutes=self.t if t is None else t)
        return d.hour * 60 + d.minute

    def tariff_at(self, t: int, with_spike: bool = True) -> float:
        mod = self.minute_of_day(t)
        if in_window(mod, *self._off):
            base = self._tariff["offpeak"]
        elif in_window(mod, *self._peak):
            base = self._tariff["peak"]
        else:
            base = self._tariff["shoulder"]
        price = base * self.cfg.energy_price_factor
        if with_spike and self.price_spike[1] > t:
            price *= self.price_spike[0]
        return price

    def carbon_at(self, t: int) -> float:
        c = self.A["energy"]["carbon_g_per_kwh"]
        h = self.minute_of_day(t) / 60.0
        v = (
            c["base"]
            + c["evening_amp"] * math.exp(-(((h - 19.0) / 2.2) ** 2))
            - c["solar_dip"] * math.exp(-(((h - 13.0) / 3.0) ** 2))
        )
        return v * self.cfg.carbon_factor

    def in_planned_window(self, t: int) -> bool:
        mod = self.minute_of_day(t)
        return any(in_window(mod, a, b) for a, b in self._planned)

    def next_planned_windows(self, after_t: int, horizon_min: int = 1440) -> list[tuple[int, int]]:
        """Absolute (start_t, end_t) of planned maintenance windows starting at/after ``after_t``."""
        out: list[tuple[int, int]] = []
        day0 = (self.start_dt + timedelta(minutes=after_t)).replace(hour=0, minute=0, second=0, microsecond=0)
        base = int((day0 - self.start_dt).total_seconds() // 60)
        for d in range(0, horizon_min // 1440 + 2):
            for a, b in self._planned:
                s = base + d * 1440 + a
                e = base + d * 1440 + (b if b > a else b + 1440)
                if s >= after_t and s <= after_t + horizon_min:
                    out.append((s, e))
        return sorted(out)

    # ------------------------------------------------------------------ events
    def _ev(self, kind: str, asset: str | None = None, **kw: Any) -> None:
        self.events.append({"t": self.t, "kind": kind, "asset": asset, **kw})

    def drain_events(self) -> list[dict[str, Any]]:
        ev, self.events = self.events, []
        return ev

    # ------------------------------------------------------------------ orders
    def _new_order(
        self,
        initial: bool = False,
        sku: str | None = None,
        qty: int | None = None,
        due_in_min: int | None = None,
        priority: int | None = None,
        rush: bool = False,
        deferrable: bool | None = None,
    ) -> Order:
        g = self.streams.generator("orders")
        o = self.A["orders"]
        if sku is None:
            skus = list(self.cfg.mix)
            sku = str(g.choice(skus, p=[self.cfg.mix[s] for s in skus]))
        prod = self.cfg.products[sku]
        qty = int(qty if qty is not None else g.choice(prod.qty))
        if priority is None:
            pm = o["priority_mix"]
            priority = int(g.choice([int(k) for k in pm], p=[pm[k] for k in pm]))
        slack = float(g.uniform(*o["lead_slack"]))
        defer = bool(g.random() < o["deferrable_share"]) if deferrable is None else deferrable
        self.order_seq += 1
        oid = f"SO-{self.order_seq:04d}"
        mh = self.A["costs"]["machine_hour_eur"]
        mat = sum(q * self.A["materials"][m]["price_eur"] for m, q in prod.bom.items())
        ops: list[Op] = []
        cum = mat
        bottleneck = max(prod.cycle[s] * qty for s in prod.route)
        for s in prod.route:
            cum += mh[s] * prod.cycle[s] / 60.0
            ops.append(Op(stage=s, cycle=prod.cycle[s], family=prod.family, cum_cost=cum))
        if due_in_min is None:
            if initial:
                due_in_min = int(g.uniform(4, 20) * 60)
            else:
                due_in_min = int(o["base_lead_h"] * 60 + slack * bottleneck * (0.7 if priority == 1 else 1.0))
        order = Order(
            id=oid,
            sku=sku,
            qty=qty,
            due=self.t + due_in_min,
            priority=priority,
            released=self.t,
            ops=ops,
            margin=prod.margin_eur,
            rush=rush,
            deferrable=defer and not rush,
        )
        self.orders[oid] = order
        for i in range(len(order.ops)):
            self._assign(order, i, None)
        self._ev("order_released", None, order=oid, sku=sku, qty=qty, due=order.due, priority=priority, rush=rush)
        return order

    def _assign(self, order: Order, idx: int, asset_id: str | None, planned: bool = False) -> None:
        """Move an op to a machine queue (or back to the pool when ``asset_id`` is None)."""
        key = (order.id, idx)
        op = order.ops[idx]
        if op.assigned and key in self.assets[op.assigned].queue:
            self.assets[op.assigned].queue.remove(key)
        pq = self.pool_q[op.stage]
        if key in pq:
            pq.remove(key)
        op.assigned = asset_id
        op.planned = bool(planned and asset_id)
        if asset_id:
            self.assets[asset_id].queue.append(key)
        else:
            pq.append(key)

    def open_orders(self) -> list[Order]:
        return [o for o in self.orders.values() if o.completed_t is None]

    # ------------------------------------------------------------------ main step
    def step(self) -> None:
        t = self.t
        self._fire_faults()
        self._evolve_hidden()
        self.price_now = self.tariff_at(t)
        self.carbon_now = self.carbon_at(t)
        # order arrivals (state-independent stream => aligned across arms)
        _, u = self.streams.get("orders").next()
        if u[0] < self.cfg.order_rate_per_h / 60.0:
            self._new_order()
        if t % 5 == 0:
            self._material_flow()
        self._zones()
        self._amr_dispatch()
        running_users = {"COMP": 0, "CHILL": 0}
        for spec in self.cfg.assets:
            a = self.assets[spec.id]
            z, uu = self.streams.get(spec.id).next()
            ty = spec.type
            if ty in PRODUCTION_TYPES:
                self._tick_production(spec, a, z, uu)
                if a.state == "RUN":
                    running_users[spec.params["util"]] += 1
            elif ty in ("COMP", "CHILL"):
                continue
            elif ty == "AMR":
                self._tick_amr(spec, a, z, uu)
            else:
                self._tick_wh(spec, a, z)
        for ty in ("COMP", "CHILL"):
            uid = self._utils.get(ty)
            if uid:
                spec = self.cfg.asset(uid)
                z, uu = self.streams.get(uid).next()
                self._tick_utility(spec, self.assets[uid], z, uu, running_users[ty])
        self._energy_totals()
        self._row[self._ridx["plant"]["power_kw"]] = self.total_kw
        self._row[self._ridx["plant"]["tariff_eur_kwh"]] = self.price_now
        self._row[self._ridx["plant"]["carbon_g_kwh"]] = self.carbon_now
        self.store.push(self._row)
        for k in self._nan_idx:
            self._row[k] = float("nan")
        self._chaos()
        self.t += 1
        if self.t % 60 == 0:
            self._snapshot_history()

    def run(self, minutes: int) -> None:
        for _ in range(minutes):
            self.step()

    # ------------------------------------------------------------------ production assets
    def _tick_production(self, spec: AssetSpec, a: AssetState, z: list[float], u: list[float]) -> None:
        p = spec.params
        t = self.t
        st = a.state
        if st == "DOWN":
            a.repair_left -= 1
            if a.repair_left <= 0:
                self._repaired(spec, a)
                st = "IDLE"
            else:
                self._commit(spec, a, "DOWN", "failure", z, 0.0)
                return
        if st == "MAINT":
            a.maint_left -= 1
            if a.maint_left <= 0:
                self._maint_done(spec, a)
                st = "IDLE"
            else:
                self._commit(spec, a, "MAINT", "maintenance", z, 0.0)
                return
        wo = self._wo_due(a.id)
        if wo is not None:
            if self._take_spare(wo):
                wo.status = "active"
                a.maint_left = wo.duration
                self._ev("maintenance_start", a.id, wo=wo.id, wo_kind=wo.kind, duration=wo.duration)
                self._commit(spec, a, "MAINT", "maintenance", z, 0.0)
                return
            wo.start_t = t + 30
            self._ev("maintenance_delayed", a.id, wo=wo.id, reason="spare part unavailable")
        if a.safe_stop:
            self._commit(spec, a, "IDLE", "safety", z, 0.0)
            return
        util = self.assets[self._utils[p["util"]]] if p["util"] in self._utils else None
        if util is not None and util.state in ("DOWN",):
            self._commit(spec, a, "BLOCKED", f"util:{p['util']}", z, 0.0)
            return
        if a.setup_left > 0:
            a.setup_left -= 1
            self._commit(spec, a, "SETUP", "changeover", z, 0.0)
            return
        if "qchar" in p:
            self._quality_rounds(spec, a, p)
        if spec.type in ("CNC", "PRESS") and a.tool_count >= 0.9:  # tool-life management (counter based)
            a.tool_count = 0.0
            a.tool_wear = 0.0
            a.flags.pop("wear_accel", None)
            a.setup_left = p["tool_change_min"] - 1
            self._ev("tool_change", a.id, reason="tool life counter")
            self._commit(spec, a, "SETUP", "tool change", z, 0.0)
            return
        order, idx = self._current_op(a)
        if order is None:
            self._commit(spec, a, "IDLE", "", z, 0.0)
            return
        if a.standby:  # wake-up from energy standby
            a.standby = False
            a.setup_left = 1
            self._commit(spec, a, "SETUP", "wake-up", z, 0.0)
            return
        op = order.ops[idx]
        if a.last_family is not None and a.last_family != op.family:
            a.last_family = op.family
            a.setup_left = p["setup_min"] - 1
            self._commit(spec, a, "SETUP", "changeover", z, 0.0)
            return
        a.last_family = op.family
        prev = order.ops[idx - 1] if idx > 0 else None
        nxt = order.ops[idx + 1] if idx + 1 < len(order.ops) else None
        avail = (prev.done - op.taken) if prev is not None else order.qty * 1.04 - op.taken
        reason = ""
        if avail <= 1e-6:
            reason = "upstream"
        elif a.kit <= 0:
            reason = "kit"
        mat = self._material_for(op.stage, order)
        if not reason and mat is not None and self.inventory[mat[0]]["on_hand"] < mat[1] * 0.5:
            reason = f"material:{mat[0]}"
        room = 1e9
        if not reason and nxt is not None:
            room = self.A["orders"]["buffer_cap_units"] - (op.done - nxt.taken)
            if room <= 1e-6:
                reason = "downstream"
        if reason:
            a.wait_min += 1
            self._commit(spec, a, "BLOCKED" if reason == "downstream" else "STARVED", reason, z, 0.0)
            return
        a.wait_min = 0
        if op.started_t is None:
            op.started_t = t
        perf = 1.0 - 0.35 * max(0.0, 0.45 - a.health) / 0.45
        if a.flags.get("slow"):
            perf *= float(a.flags["slow"])
        rate = (a.speed / 100.0) / op.cycle * perf
        if spec.type == "PRESS":
            rate *= (
                1.0 + 0.004 * (a.recipe.get("inj_speed", 50.0) - 50.0) - 0.006 * (a.recipe.get("cool_s", 14.0) - 14.0)
            )
        units = min(rate, avail, room)
        if mat is not None:
            units = min(units, self.inventory[mat[0]]["on_hand"] / max(mat[1], 1e-9))
            self.inventory[mat[0]]["on_hand"] -= units * mat[1]
        if units <= 0:
            self._commit(spec, a, "STARVED", "material", z, 0.0)
            return
        state, why = "RUN", ""
        if units < 0.5 * rate:  # input-limited or output-limited: the machine is waiting, not producing
            state, why = ("BLOCKED", "downstream") if room < avail else ("STARVED", "upstream")
            a.wait_min += 1
        else:
            a.wait_min = 0
        a.kit -= 1.0
        # ---- quality
        shift = self._shift(spec, a)
        eff = shift - a.offset
        pd = p_defect(eff) if "qchar" in p else 2e-4
        n_def = units * pd
        lat_in = units * (prev.lat / max(prev.done, 1.0)) if prev is not None else 0.0
        scrap_u = 0.0
        scrap_cost = 0.0
        if spec.type == "TEST":
            det = lat_in * 0.95
            esc = lat_in - det
            scrap_u = det
            scrap_cost = det * op.cum_cost
            op.lat += esc
            order.escapes += esc
            self.acc["escapes"] += esc
            self.acc["escape_cost"] += esc * self.A["costs"]["escape_eur_per_unit"]
            good = units - det
        elif "qchar" in p and a.inline_inspect:
            scrap_u = n_def
            scrap_cost = n_def * op.cum_cost
            op.lat += lat_in
            good = units - n_def
        else:
            op.lat += lat_in + (n_def if "qchar" in p else 0.0)
            good = units
        op.taken += units
        op.done += good
        op.scrap += scrap_u
        a.units += units
        a.good += good
        a.scrap += scrap_u
        a.ideal_min += units * op.cycle if state == "RUN" else 0.0
        self.acc["units_total"] += units
        self.acc["scrap_units"] += scrap_u
        self.acc["scrap_cost"] += scrap_cost
        if op.stage == "PACK":
            self.acc["units_good"] += good
        # tool wear / thermal inertia
        a.tool_wear = min(1.5, a.tool_wear + units / p["tool_life_units"] * a.flags.get("wear_accel", 1.0))
        a.tool_count += units / p["tool_life_units"]
        self._commit(spec, a, state, why, z, units, shift=eff, u=u)
        # ---- op completion
        finished = False
        if (
            op.done >= order.qty - 1e-6
            or (idx == 0 and op.taken >= order.qty * 1.04 - 1e-6)
            or prev is not None
            and prev.finished_t is not None
            and op.taken >= prev.done - 1e-6
        ):
            finished = True
        if finished:
            op.finished_t = t
            a.current = None
            if (order.id, idx) in a.queue:
                a.queue.remove((order.id, idx))
            self._ev("op_done", a.id, order=order.id, stage=op.stage, done=round(op.done, 1))
            if idx == len(order.ops) - 1:
                self._complete(order)

    def _quality_rounds(self, spec: AssetSpec, a: AssetState, p: dict[str, Any]) -> None:
        """Baseline quality assurance: a technician inspects each process every 2 h and corrects a shift >= 2.5 sigma after ~20 min."""
        if not self.manual_qc:
            return
        t = self.t
        if a.qc_fix_t is None and t >= a.next_qc_t:
            a.next_qc_t = t + 120
            if abs(self._shift(spec, a) - a.offset) >= 2.5:
                a.qc_fix_t = t + 20
        if a.qc_fix_t is not None and t >= a.qc_fix_t:
            a.qc_fix_t = None
            a.offset = max(-2.0, min(2.0, round(self._shift(spec, a), 2)))
            if a.tool_wear >= 0.5 and spec.type in ("CNC", "PRESS"):
                a.tool_wear = a.tool_count = 0.0
                a.flags.pop("wear_accel", None)
                a.setup_left = p["tool_change_min"]
            self._ev("manual_qc_fix", a.id, offset=a.offset)

    def _complete(self, order: Order) -> None:
        order.completed_t = self.t
        last = order.ops[-1]
        late = max(0, self.t - order.due)
        in_full = last.done >= 0.98 * order.qty
        self.acc["orders_completed"] += 1
        self.acc["orders_on_time"] += 1 if late == 0 and in_full else 0
        self.acc["orders_in_full"] += 1 if in_full else 0
        self.acc["tardiness_min"] += late
        self.acc["tardiness_eur"] += late / 60.0 * self.A["costs"]["tardiness_eur_per_hour"][order.priority]
        self.acc["revenue"] += min(last.done, order.qty) * order.margin
        self._ev("order_done", None, order=order.id, late_min=late, in_full=in_full, shipped=round(last.done, 1))

    def _shift(self, spec: AssetState | AssetSpec, a: AssetState) -> float:
        s = 4.0 * a.tool_wear * a.tool_wear + a.thermal + a.qdrift
        if a.recipe:
            s += (
                0.025 * max(0.0, a.recipe.get("inj_speed", 50.0) - 55.0)
                + 0.03 * max(0.0, 12.0 - a.recipe.get("cool_s", 14.0))
                + 0.05 * max(0.0, 236.0 - a.recipe.get("melt_temp_c", 240.0))
            )
        return s

    def _current_op(self, a: AssetState) -> tuple[Order | None, int]:
        if a.current is not None:
            order = self.orders.get(a.current[0])
            if (
                order is None
                or order.ops[a.current[1]].finished_t is not None
                or order.hold_until > self.t
                or order.ops[a.current[1]].assigned != a.id
            ):
                a.current = None
            elif a.wait_min >= 6 and self.t - a.op_since >= 15:
                alt = self._pick_ready(a, exclude=a.current)
                if alt is not None:
                    old = self.orders[a.current[0]]
                    if not old.ops[a.current[1]].planned:
                        self._assign(old, a.current[1], None)
                    a.current = alt
                    a.wait_min = 0
                    a.op_since = self.t
        if a.current is None:
            a.current = self._pick_ready(a)
            a.op_since = self.t
        if a.current is None:
            return None, 0
        return self.orders[a.current[0]], a.current[1]

    def _ready(self, order: Order, idx: int) -> bool:
        if order.hold_until > self.t:
            return False
        if idx == 0:
            return True
        prev = order.ops[idx - 1]
        avail = prev.done - order.ops[idx].taken
        return avail >= min(self.A["orders"]["transfer_batch"], order.qty) or (
            prev.finished_t is not None and avail > 1e-6
        )

    def _pick_ready(self, a: AssetState, exclude: tuple[str, int] | None = None) -> tuple[str, int] | None:
        """First ready op in the machine's own (planned) queue; otherwise pull from the stage pool (FIFO, or EDD with a plan)."""
        stale: list[tuple[str, int]] = []
        found = None
        for key in a.queue:
            order = self.orders.get(key[0])
            if order is None or order.ops[key[1]].finished_t is not None:
                stale.append(key)
                continue
            if key != exclude and self._ready(order, key[1]):
                found = key
                break
        for key in stale:
            a.queue.remove(key)
        if found is not None:
            return found
        stage = self.cfg.asset(a.id).stage
        pool = self.pool_q.get(stage or "", [])
        best: tuple[str, int] | None = None
        best_rank = None
        for key in pool:
            order = self.orders[key[0]]
            if key == exclude or not self._ready(order, key[1]):
                continue
            rank = (order.priority, order.released) if self.dispatch_rule == "plan" else (order.released, key[1])
            if best_rank is None or rank < best_rank:
                best, best_rank = key, rank
        if best is None and self.dispatch_rule == "plan":
            # work-conserving: an idle machine takes a ready op queued at a busy peer (plans are advisory, the shop floor never idles)
            for pid in self.cfg.pools.get(stage or "", ()):
                if pid == a.id:
                    continue
                peer = self.assets[pid]
                for key in peer.queue:
                    order = self.orders.get(key[0])
                    if (
                        order is None
                        or key == peer.current
                        or key == exclude
                        or order.ops[key[1]].finished_t is not None
                        or not self._ready(order, key[1])
                    ):
                        continue
                    if peer.current is None and peer.state not in ("DOWN", "MAINT") and not peer.safe_stop:
                        continue
                    rank = (order.priority, order.released)
                    if best_rank is None or rank < best_rank:
                        best, best_rank = key, rank
        if best is not None:
            self._assign(self.orders[best[0]], best[1], a.id)
        return best

    def _material_for(self, stage: str, order: Order) -> tuple[str, float] | None:
        prod = self.cfg.products[order.sku]
        for m, q in prod.bom.items():
            if self.A["materials"][m]["stage"] == stage:
                return m, q
        return None

    # ------------------------------------------------------------------ commit: state, degradation, sensors, energy
    def _commit(
        self,
        spec: AssetSpec,
        a: AssetState,
        state: str,
        reason: str,
        z: list[float],
        units: float,
        shift: float = 0.0,
        u: list[float] | None = None,
    ) -> None:
        p = spec.params
        if state != a.state:
            self._ev("state", a.id, frm=a.state, to=state, reason=reason)
        a.state, a.reason = state, reason
        a.mins[state] += 1.0
        if state != "RUN" and not (state == "IDLE" and not reason):
            key = f"{state}:{reason}" if reason else state
            a.loss[key] = a.loss.get(key, 0.0) + 1.0
        if state == "DOWN":
            a.downtime_unplanned += 1.0
            self.acc["downtime_unplanned_min"] += 1.0
            self.acc["downtime_loss_eur"] += p["loss_eur_per_min"]
        elif state == "MAINT":
            a.planned_maint += 1.0
        if reason == "safety":
            a.safety_stop_min += 1.0
            self.acc["safety_stop_min"] += 1.0
        # ---- degradation (only while running) and failures
        load = a.speed / 100.0 if state == "RUN" else 0.0
        if state == "RUN":
            rate = p["degr_per_run_h"] / 60.0 * self.cfg.failure_factor * math.exp(0.3 * z[0])
            b = a.flags.get("bearing")
            if b is not None:
                rate = max(rate, b["rate"] * (1.0 + b["noise"] * z[0]))
            a.health = max(0.0, a.health - rate * (0.6 + 0.4 * load))
            if a.health <= p["fail_threshold"]:
                self._fail(spec, a, "wear_out" if b is None else "bearing_wear", u)
            elif u is not None and u[0] < p["shock_per_run_h"] / 60.0 * self.cfg.failure_factor:
                self._fail(spec, a, "random_shock", u)
        # ---- energy
        pw = p["power_kw"]
        if a.state == "RUN":
            a.power_kw = pw["IDLE"] + (pw["RUN"] - pw["IDLE"]) * load**1.5
            if a.recipe:
                a.power_kw *= (
                    1.0
                    + 0.003 * (a.recipe.get("inj_speed", 50.0) - 50.0)
                    + 0.004 * (a.recipe.get("melt_temp_c", 240.0) - 240.0)
                    - 0.002 * (a.recipe.get("cool_s", 14.0) - 14.0)
                )
        else:
            a.power_kw = pw[a.state] * (0.25 if (a.standby and a.state == "IDLE") else 1.0)
        a.power_kw *= 1.0 + 0.01 * z[4]
        a.kwh += a.power_kw / 60.0
        # ---- sensors
        self._row[self._ridx[spec.id]["power_kw"]] = a.power_kw
        self._sense(spec, a, z, load, shift, units)

    def _sense(self, spec: AssetSpec, a: AssetState, z: list[float], load: float, shift: float, units: float) -> None:
        ty = spec.type
        r = self._ridx[spec.id]
        row = self._row
        idle = a.state != "RUN"
        h = a.health
        d = 1.0 - h
        vib = a.vib0 * (0.25 if idle else 1.0) + 6.0 * d * d * (0.4 + 0.6 * load) + (0.04 if idle else 0.10) * z[1]
        a.sens["vibration_rms"] = vib
        tgt = 24.0 + 22.0 * load + 20.0 * d**1.5 + 2.2 * a.thermal + a.flags.get("heat", 0.0)
        a.temp += 0.12 * (tgt - a.temp) + 0.12 * z[2]
        amps = a.power_kw * 1000.0 / (1.732 * 400.0 * 0.86) + 0.15 * z[4]
        a.sens["current_a"] = amps
        if "vibration_rms" in r:
            row[r["vibration_rms"]] = vib
        if "current_a" in r:
            row[r["current_a"]] = amps
        if ty == "CNC":
            row[r["bearing_temp_c"]] = a.temp
            row[r["spindle_load_pct"]] = (8.0 if idle else 30.0 + 45.0 * load + 28.0 * a.tool_wear) + 1.5 * z[3]
            if a.state == "RUN":
                q = spec.params["qchar"]
                row[r["dim_mm"]] = q["nominal"] + q["sigma"] * (shift + z[5])
        elif ty == "PRESS":
            rc = a.recipe
            row[r["melt_temp_c"]] = rc.get("melt_temp_c", 240.0) + 0.4 * (a.temp - 46.0) + 3.0 * a.thermal + 0.3 * z[2]
            row[r["hydraulic_pressure_bar"]] = (30.0 if idle else 180.0) - 30.0 * d * d + 0.8 * z[3]
            if a.state == "RUN":
                q = spec.params["qchar"]
                row[r["part_weight_g"]] = q["nominal"] + q["sigma"] * (shift + z[5])
        elif ty == "ASM" and a.state == "RUN":
            q = spec.params["qchar"]
            row[r["torque_nm"]] = q["nominal"] + q["sigma"] * (shift + z[5])

    def _fail(self, spec: AssetSpec, a: AssetState, cause: str, u: list[float] | None) -> None:
        mttr = spec.params["mttr_min"]
        a.state = "DOWN"
        a.repair_left = max(15.0, mttr * (0.7 + 0.6 * (u[1] if u else 0.5)))
        a.failures += 1
        a.last_failure_t = self.t
        for wo in self.work_orders.values():
            if wo.asset == a.id and wo.status == "scheduled":
                wo.status = "cancelled"
        self.acc["maintenance_cost"] += self.A["costs"]["repair_eur"]["unplanned"]
        if a.task:
            self.amr_requests.insert(0, [self.t, a.task[0]])
            a.task = None
        self._ev("failure", a.id, cause=cause, repair_min=round(a.repair_left))

    def _repaired(self, spec: AssetSpec, a: AssetState) -> None:
        a.repair_total += spec.params["mttr_min"]
        a.health = 0.92
        for k in ("bearing", "heat", "wear_accel", "thermal_target", "thermal_ramp"):
            a.flags.pop(k, None)
        a.thermal = 0.0
        a.tool_wear = 0.0
        a.offset = 0.0
        a.last_maint_t = self.t
        a.state = "IDLE"
        self._ev("repaired", a.id)

    def _maint_done(self, spec: AssetSpec, a: AssetState) -> None:
        active = [wo for wo in self.work_orders.values() if wo.asset == a.id and wo.status == "active"]
        if not active or any(
            not wo.tool for wo in active
        ):  # a tool change alone does not cure a bearing or thermal fault
            a.health = 0.97
            for k in ("bearing", "heat", "thermal_target", "thermal_ramp"):
                a.flags.pop(k, None)
            a.thermal = 0.0
        a.last_maint_t = self.t
        for wo in self.work_orders.values():
            if wo.asset == a.id and wo.status == "active":
                wo.status = "done"
                if wo.tool:
                    a.tool_wear = 0.0
                    a.flags.pop("wear_accel", None)
                    a.offset = 0.0
                self.acc["maintenance_cost"] += 60.0 if wo.tool else self.A["costs"]["repair_eur"]["planned"]
                self._ev("maintenance_done", a.id, wo=wo.id)
        a.state = "IDLE"

    def _wo_due(self, asset_id: str) -> WorkOrder | None:
        for wo in self.work_orders.values():
            if wo.status == "scheduled" and wo.asset == asset_id and wo.start_t <= self.t:
                return wo
        return None

    def _take_spare(self, wo: WorkOrder) -> bool:
        if not wo.spare:
            return True
        s = self.spares.get(wo.spare)
        if s is None or s["on_hand"] < 1:
            return False
        s["on_hand"] -= 1
        return True

    # ------------------------------------------------------------------ utilities, AMRs, warehouse
    def _tick_utility(self, spec: AssetSpec, a: AssetState, z: list[float], u: list[float], n_running: int) -> None:
        p = spec.params
        st = a.state
        if st == "DOWN":
            a.repair_left -= 1
            if a.repair_left <= 0:
                self._repaired(spec, a)
                a.state = "RUN"
        elif st == "MAINT":
            a.maint_left -= 1
            if a.maint_left <= 0:
                self._maint_done(spec, a)
                a.state = "RUN"
        else:
            wo = self._wo_due(a.id)
            if wo is not None and self._take_spare(wo):
                wo.status = "active"
                a.maint_left = wo.duration
                a.state = "MAINT"
                self._ev("maintenance_start", a.id, wo=wo.id, wo_kind=wo.kind, duration=wo.duration)
        state = a.state
        a.mins[state] += 1.0
        if state == "DOWN":
            a.downtime_unplanned += 1.0
            self.acc["downtime_unplanned_min"] += 1.0
            self.acc["downtime_loss_eur"] += p["loss_eur_per_min"]
        demand = p["util_base_kw"] + p["util_per_running_kw"] * n_running if state == "RUN" else p["power_kw"][state]
        if state == "RUN":
            rate = p["degr_per_run_h"] / 60.0 * self.cfg.failure_factor * math.exp(0.3 * z[0])
            b = a.flags.get("bearing")
            if b is not None:
                rate = max(rate, b["rate"] * (1.0 + b["noise"] * z[0]))
            a.health = max(0.0, a.health - rate)
            if a.health <= p["fail_threshold"]:
                self._fail(spec, a, "wear_out" if b is None else "bearing_wear", u)
            elif u[0] < p["shock_per_run_h"] / 60.0 * self.cfg.failure_factor:
                self._fail(spec, a, "random_shock", u)
        grid = demand * (1.0 + 0.01 * z[4])
        sh = self.shifts[a.id]
        if state == "RUN" and sh["active"] and self.t < sh["until"]:
            if self.price_now >= sh["hi"] and sh["soc"] > 0:
                d_kw = min(sh["discharge_kw"], 0.4 * demand, sh["soc"] * 60.0)
                grid -= d_kw
                sh["soc"] -= d_kw / 60.0
                sh["shifted_kwh"] += d_kw / 60.0
                sh["saved_eur"] += d_kw / 60.0 * self.price_now
            elif self.price_now <= sh["lo"] and sh["soc"] < sh["cap"]:
                c_kw = min(sh["charge_kw"], (sh["cap"] - sh["soc"]) * 60.0 / self.A["energy"]["shift_efficiency"])
                grid += c_kw
                sh["soc"] += c_kw / 60.0 * self.A["energy"]["shift_efficiency"]
                sh["saved_eur"] -= c_kw / 60.0 * self.price_now
        elif sh["active"] and self.t >= sh["until"]:
            sh["active"] = False
        a.power_kw = grid
        a.kwh += grid / 60.0
        d = 1.0 - a.health
        r = self._ridx[spec.id]
        vib = a.vib0 * 0.9 + 6.0 * d * d + 0.08 * z[1]
        a.temp += 0.1 * (30.0 + 22.0 * d**1.5 + (6.0 if state == "RUN" else 0.0) - a.temp) + 0.1 * z[2]
        row = self._row
        row[r["vibration_rms"]] = vib
        row[r["current_a"]] = grid * 1000.0 / (1.732 * 400.0 * 0.86)
        row[r["power_kw"]] = grid
        a.sens["vibration_rms"] = vib
        if spec.type == "COMP":
            row[r["pressure_bar"]] = 7.0 - 0.9 * d * d + 0.05 * z[3] - (0.4 if state == "DOWN" else 0.0)
            row[r["temperature_c"]] = a.temp
        else:
            row[r["supply_temp_c"]] = 7.0 + 2.5 * d * d + 0.1 * z[3] + (6.0 if state == "DOWN" else 0.0)

    def _tick_amr(self, spec: AssetSpec, a: AssetState, z: list[float], u: list[float]) -> None:
        p = spec.params
        st = a.state
        if st == "DOWN":
            a.repair_left -= 1
            if a.repair_left <= 0:
                self._repaired(spec, a)
                a.task = None
        elif st == "MAINT":
            a.battery = min(100.0, a.battery + 100.0 / 30.0)
            a.maint_left -= 1
            if a.maint_left <= 0 or a.battery >= 95:
                a.state = "IDLE"
                a.maint_left = 0
        elif a.task:
            a.task[1] -= 1
            a.battery -= 0.6
            a.state = "RUN"
            if a.task[1] <= 0:
                m = self.assets.get(a.task[0])
                if m is not None:
                    m.kit = min(self.A["feeding"]["kit_capacity_min"], m.kit + p["kit_minutes_per_delivery"])
                    m.kit_requested = False
                a.task = None
                a.state = "IDLE"
        else:
            a.state = "IDLE"
            if a.battery < 25:
                a.state = "MAINT"
                a.maint_left = 30
        a.mins[a.state] += 1.0
        if a.state == "DOWN":
            a.downtime_unplanned += 1.0
        a.power_kw = p["power_kw"][a.state] * (1.0 + 0.01 * z[4])
        a.kwh += a.power_kw / 60.0
        r = self._ridx[spec.id]
        self._row[r["battery_pct"]] = a.battery
        self._row[r["power_kw"]] = a.power_kw
        if (
            a.state != "DOWN"
            and a.health > p["fail_threshold"]
            and u[0] < p["shock_per_run_h"] / 60.0 * 0.5
            and a.state == "RUN"
        ):
            self._fail(spec, a, "random_shock", u)

    def _tick_wh(self, spec: AssetSpec, a: AssetState, z: list[float]) -> None:
        a.state = "RUN"
        a.mins["RUN"] += 1.0
        a.power_kw = spec.params["power_kw"]["RUN"] * (1.0 + 0.01 * z[4])
        a.kwh += a.power_kw / 60.0
        self._row[self._ridx[spec.id]["power_kw"]] = a.power_kw

    def _amr_dispatch(self) -> None:
        fc = self.A["feeding"]
        for pid in self._prod_ids:
            a = self.assets[pid]
            if a.kit < fc["kit_request_below_min"] and not a.kit_requested:
                a.kit_requested = True
                self.amr_requests.append([self.t, pid])
        if not self.amr_requests:
            return
        idle = [self.assets[i] for i in self._amr_ids if self.assets[i].state == "IDLE" and self.assets[i].task is None]
        if not idle:
            return
        if self.amr_priority:
            self.amr_requests.sort(key=lambda r: (-self.amr_priority.get(r[1], 0.0), r[0]))
        for amr in idle:
            if not self.amr_requests:
                break
            _, mid = self.amr_requests.pop(0)
            amr.task = [mid, self.A["asset_types"]["AMR"]["delivery_min"]]
            amr.state = "RUN"

    # ------------------------------------------------------------------ materials
    def _material_flow(self) -> None:
        t = self.t
        for k, m in self.inventory.items():
            arrived = [o for o in m["on_order"] if o[0] <= t]
            for _eta, qty, _ in arrived:
                m["on_hand"] += qty
                self._ev("material_received", None, material=k, qty=qty)
            m["on_order"] = [o for o in m["on_order"] if o[0] > t]
            pos = m["on_hand"] + sum(o[1] for o in m["on_order"])
            if pos <= m["min"]:
                qty = m["max"] - pos
                lead = m["lead_h"] * 60 + (m["delay_min"] if m["delay_until"] > t else 0.0)
                m["on_order"].append([t + lead, qty, "erp"])
                self._ev("material_ordered", None, material=k, qty=round(qty), eta=round(t + lead))
        for s in self.spares.values():
            arrived = [o for o in s["on_order"] if o[0] <= t]
            for o in arrived:
                s["on_hand"] += o[1]
            s["on_order"] = [o for o in s["on_order"] if o[0] > t]
            if s["on_hand"] + sum(o[1] for o in s["on_order"]) < s["min"]:
                s["on_order"].append([t + s["lead_h"] * 60, 1, "erp"])

    # ------------------------------------------------------------------ safety zones
    def _zones(self) -> None:
        sf = self.A["safety"]
        for zid, zs in self.zones.items():
            members = self._zone_members[zid]
            if zs["occ"] > 0:
                zs["occ"] -= 1
                if zs["occ"] <= 0:
                    zs["wait"] = (
                        sf["restart_delay_min_swarm"]
                        if self.safety_mode == "agent"
                        else sf["restart_delay_min_baseline"]
                    )
                    self._ev("zone_clear", None, zone=zid)
                for m in members:
                    self.assets[m].safe_stop = True
            elif zs["wait"] > 0:
                zs["wait"] -= 1
                if zs["wait"] <= 0:
                    for m in members:
                        self.assets[m].safe_stop = False
                    self._ev("zone_restart", None, zone=zid)

    # ------------------------------------------------------------------ energy accounting
    def _energy_totals(self) -> None:
        kw = sum(a.power_kw for a in self.assets.values())
        self.total_kw = kw
        kwh = kw / 60.0
        self.acc["energy_kwh"] += kwh
        self.acc["energy_cost"] += kwh * self.price_now
        self.acc["co2_kg"] += kwh * self.carbon_now / 1000.0
        self._kw_window.append(kw)
        if len(self._kw_window) > 15:
            self._kw_window.pop(0)
        if len(self._kw_window) == 15:
            self.acc["peak_kw"] = max(self.acc["peak_kw"], sum(self._kw_window) / 15.0)

    def current_snapshot(self) -> dict[str, Any]:
        snap: dict[str, Any] = dict(self.acc)
        snap["_t"] = self.t
        snap["_assets"] = {
            aid: {
                **a.mins,
                "units": a.units,
                "good": a.good,
                "scrap": a.scrap,
                "ideal": a.ideal_min,
                "kwh": a.kwh,
                "failures": a.failures,
                "down_unplanned": a.downtime_unplanned,
            }
            for aid, a in self.assets.items()
        }
        return snap

    def _snapshot_history(self) -> None:
        self.history.append((self.t, self.current_snapshot()))
        if len(self.history) > 24 * 14:
            del self.history[0]

    # ------------------------------------------------------------------ faults
    def schedule_fault(self, start_t: int, kind: str, **params: Any) -> None:
        self.pending_faults.append((int(start_t), kind, params))
        self.pending_faults.sort(key=lambda x: x[0])

    def _fire_faults(self) -> None:
        while self.pending_faults and self.pending_faults[0][0] <= self.t:
            _, kind, params = self.pending_faults.pop(0)
            try:
                self.inject_fault(kind, source="schedule", **params)
            except ActionRejected as exc:
                self._ev("fault_rejected", None, fault_kind=kind, reason=str(exc))
        for f in self.faults:
            if f.status == "active" and f.end_t is not None and f.end_t <= self.t:
                self._end_fault(f)

    def _end_fault(self, f: Fault) -> None:
        f.status = "ended"
        if f.kind == "quality_drift":
            a = self.assets.get(f.target)
            if a is not None:
                a.qdrift = 0.0
        self._ev("fault_ended", f.target, fault=f.id, fault_kind=f.kind)

    def inject_fault(self, kind: str, source: str = "console", **params: Any) -> Fault:
        fd = self.A["faults"]
        if kind not in fd:
            raise ActionRejected(f"unknown fault kind {kind!r}")
        prm = {**fd[kind], **{k: v for k, v in params.items() if v is not None}}
        self.fault_seq += 1
        target = str(
            params.get("asset") or params.get("material") or params.get("zone") or params.get("sku") or "plant"
        )
        f = Fault(id=f"F-{self.fault_seq:03d}", kind=kind, target=target, params=prm, start_t=self.t, source=source)
        if kind in ("bearing_wear", "tool_wear", "thermal_drift", "jam", "quality_drift"):
            a = self._need_asset(target)
            spec = self.cfg.asset(target)
            if kind == "bearing_wear":
                ttf = float(prm["ttf_h"]) * 60.0
                a.flags["bearing"] = {
                    "rate": max(a.health - spec.params["fail_threshold"], 0.02) / ttf,
                    "noise": float(prm["noise"]),
                }
            elif kind == "tool_wear":
                if spec.type not in ("CNC", "PRESS", "ASM"):
                    raise ActionRejected("tool wear applies to CNC, press and assembly assets")
                a.flags["wear_accel"] = float(prm["accel"])
            elif kind == "thermal_drift":
                a.flags["thermal_target"] = float(prm["magnitude_sigma"])
                a.flags["thermal_ramp"] = float(prm["magnitude_sigma"]) / (float(prm["ramp_h"]) * 60.0)
                a.flags["heat"] = 9.0
            elif kind == "jam":
                if a.state not in ("DOWN", "MAINT"):
                    a.state = "DOWN"
                    a.repair_left = float(prm["duration_min"])
                    a.flags["jam"] = {"recoverable": bool(prm["recoverable"]), "remote": float(prm["remote_clear_min"])}
                    a.failures += 1
                    a.last_failure_t = self.t
                    self._ev("failure", a.id, cause="jam", repair_min=round(a.repair_left))
            elif kind == "quality_drift":
                a.qdrift = float(prm["magnitude_sigma"])
                f.end_t = self.t + int(float(prm["duration_h"]) * 60)
        elif kind == "supplier_delay":
            m = self.inventory.get(target)
            if m is None:
                raise ActionRejected(f"unknown material {target!r}")
            delay = float(prm["delay_h"]) * 60.0
            m["delay_until"] = self.t + delay * 2
            m["delay_min"] = delay
            for o in m["on_order"]:
                o[0] += delay
            f.end_t = self.t + int(delay)
        elif kind == "rush_order":
            sku = str(params.get("sku") or next(iter(self.cfg.mix)))
            if sku not in self.cfg.products:
                raise ActionRejected(f"unknown sku {sku!r}")
            self._new_order(
                sku=sku,
                qty=int(prm["qty"]),
                due_in_min=int(float(prm["due_in_h"]) * 60),
                priority=int(prm["priority"]),
                rush=True,
            )
        elif kind == "power_price_spike":
            self.price_spike = [float(prm["multiplier"]), self.t + float(prm["duration_h"]) * 60.0]
            f.end_t = int(self.price_spike[1])
        elif kind == "human_intrusion":
            zone = target
            if zone not in self.zones:
                raise ActionRejected(f"unknown zone {zone!r}")
            self.zones[zone]["occ"] = float(prm["duration_min"])
            self.zones[zone]["wait"] = 0.0
            f.end_t = self.t + int(prm["duration_min"])
        self.faults.append(f)
        self._ev("fault_injected", target, fault=f.id, fault_kind=kind, source=source)
        return f

    def _need_asset(self, asset_id: str) -> AssetState:
        a = self.assets.get(asset_id)
        if a is None:
            raise ActionRejected(f"unknown asset {asset_id!r}")
        return a

    def _chaos(self) -> None:
        if self.chaos_per_day <= 0:
            return
        _, u = self.streams.get("chaos").next()
        if u[0] >= self.chaos_per_day / 1440.0:
            return
        g = self.streams.generator("chaos")
        kinds = [
            "bearing_wear",
            "tool_wear",
            "thermal_drift",
            "jam",
            "supplier_delay",
            "power_price_spike",
            "human_intrusion",
            "quality_drift",
        ]
        w = [0.22, 0.18, 0.12, 0.14, 0.08, 0.08, 0.06, 0.12]
        kind = str(g.choice(kinds, p=w))
        prod = [a.id for a in self.cfg.assets if a.type in PRODUCTION_TYPES]
        try:
            if kind == "bearing_wear":
                cand = [
                    a.id
                    for a in self.cfg.assets
                    if a.type in ("CNC", "PRESS") and "bearing" not in self.assets[a.id].flags
                ]
                self.inject_fault(kind, source="chaos", asset=str(g.choice(cand)), ttf_h=float(g.uniform(9, 18)))
            elif kind == "tool_wear" or kind in ("thermal_drift", "quality_drift"):
                cand = [a.id for a in self.cfg.assets if a.type in ("CNC", "PRESS")]
                self.inject_fault(kind, source="chaos", asset=str(g.choice(cand)))
            elif kind == "jam":
                self.inject_fault(kind, source="chaos", asset=str(g.choice(prod)))
            elif kind == "supplier_delay":
                self.inject_fault(
                    kind, source="chaos", material=str(g.choice(list(self.inventory))), delay_h=float(g.uniform(6, 14))
                )
            elif kind == "power_price_spike":
                self.inject_fault(kind, source="chaos")
            else:
                self.inject_fault(kind, source="chaos", zone=str(g.choice(list(self.zones))))
        except ActionRejected:
            return

    # ------------------------------------------------------------------ thermal drift ramp (hidden state evolution)
    def _evolve_hidden(self) -> None:
        for a in self.assets.values():
            tt = a.flags.get("thermal_target")
            if tt is not None:
                a.thermal = min(tt, a.thermal + a.flags["thermal_ramp"])

    # ------------------------------------------------------------------ control API
    def apply(self, action: dict[str, Any], actor: str = "system") -> dict[str, Any]:
        kind = action.get("kind")
        if kind not in CONTROL_ACTIONS:
            raise ActionRejected(f"unknown action kind {kind!r}")
        fn = getattr(self, f"_act_{kind}")
        res = fn(**{k: v for k, v in action.items() if k != "kind"}, _actor=actor)
        self._ev("action", action.get("asset"), action=kind, actor=actor)
        return res

    def _act_set_speed(self, asset: str, pct: float, _actor: str = "system") -> dict[str, Any]:
        lo, hi = self.A["safety"]["forbidden"]["speed_pct"]
        a = self._need_asset(asset)
        if not lo <= pct <= hi:
            raise ActionRejected(f"speed {pct}% outside physical limits {lo}-{hi}%")
        a.speed = float(pct)
        return {"asset": asset, "speed": a.speed}

    def _act_set_setpoint(self, asset: str, name: str, value: float, _actor: str = "system") -> dict[str, Any]:
        a = self._need_asset(asset)
        if name == "offset_comp":
            lo, hi = self.A["safety"]["forbidden"]["offset_sigma"]
            if not lo <= value <= hi:
                raise ActionRejected(f"compensation offset {value} outside {lo}..{hi} sigma")
            a.offset = float(value)
        elif name in ("melt_temp_c", "inj_speed", "cool_s"):
            if self.cfg.asset(asset).type != "PRESS":
                raise ActionRejected("recipe setpoints apply to presses")
            if name == "melt_temp_c":
                lo, hi = self.A["safety"]["forbidden"]["melt_temp_c"]
                if not lo <= value <= hi:
                    raise ActionRejected(f"melt temperature {value} outside {lo}..{hi}")
            a.recipe[name] = float(value)
        else:
            raise ActionRejected(f"unknown setpoint {name!r}")
        return {"asset": asset, name: value}

    _act_set_recipe = _act_set_setpoint

    def _act_schedule_maintenance(
        self,
        asset: str,
        start_t: int,
        duration: int | None = None,
        reason: str = "",
        spare: str | None = None,
        tool: bool = False,
        kind: str = "planned",
        _actor: str = "system",
    ) -> dict[str, Any]:
        spec = self.cfg.asset(asset) if asset in self.assets else None
        if spec is None:
            raise ActionRejected(f"unknown asset {asset!r}")
        if start_t < self.t:
            start_t = self.t
        duration = int(duration or spec.params.get("pm_duration_min", 45))
        if spare is not None and spare not in self.spares:
            raise ActionRejected(f"unknown spare part {spare!r}")
        self.wo_seq += 1
        wo = WorkOrder(
            id=f"WO-{self.wo_seq:04d}",
            asset=asset,
            start_t=int(start_t),
            duration=duration,
            kind=kind,
            reason=reason,
            spare=spare,
            tool=tool,
            created_t=self.t,
            created_by=_actor,
        )
        self.work_orders[wo.id] = wo
        return {"work_order": wo.id, "asset": asset, "start_t": wo.start_t, "duration": duration}

    def _act_cancel_maintenance(self, wo: str, _actor: str = "system") -> dict[str, Any]:
        w = self.work_orders.get(wo)
        if w is None or w.status != "scheduled":
            raise ActionRejected("work order not found or not cancellable")
        w.status = "cancelled"
        return {"work_order": wo, "status": "cancelled"}

    def _act_tool_change(self, asset: str, start_t: int | None = None, _actor: str = "system") -> dict[str, Any]:
        spec = self.cfg.asset(asset) if asset in self.assets else None
        if spec is None or spec.type not in PRODUCTION_TYPES:
            raise ActionRejected("tool change applies to production assets")
        return self._act_schedule_maintenance(
            asset,
            start_t if start_t is not None else self.t + 2,
            spec.params["tool_change_min"],
            "tool change",
            None,
            True,
            "planned",
            _actor,
        )

    def _act_reassign_op(self, order: str, op: int, to_asset: str, _actor: str = "system") -> dict[str, Any]:
        o = self.orders.get(order)
        if o is None or op < 0 or op >= len(o.ops):
            raise ActionRejected("unknown order/op")
        opx = o.ops[op]
        if opx.finished_t is not None:
            raise ActionRejected("operation already finished")
        tgt = self._need_asset(to_asset)
        if self.cfg.asset(to_asset).stage != opx.stage:
            raise ActionRejected(f"{to_asset} cannot run stage {opx.stage}")
        if tgt.state == "DOWN" and tgt.repair_left > 240:
            raise ActionRejected("target asset is down for too long")
        src = self.assets.get(opx.assigned or "")
        if src is not None and src.current == (order, op) and src.state in ("RUN", "SETUP") and src.id != to_asset:
            raise ActionRejected("operation is running; cannot move")
        if src is not None and src.current == (order, op):
            src.current = None
        self._assign(o, op, to_asset, planned=True)
        return {"order": order, "op": op, "to": to_asset}

    def _act_apply_plan(
        self, assignments: list[list[Any]], sequences: dict[str, list[list[Any]]], _actor: str = "system"
    ) -> dict[str, Any]:
        """Bulk (re)assignment + sequencing from a planner; running/set-up operations stay pinned to their machine."""
        moved = skipped = 0
        for oid, idx, asset in assignments:
            o = self.orders.get(str(oid))
            if o is None or int(idx) >= len(o.ops) or asset not in self.assets:
                skipped += 1
                continue
            op = o.ops[int(idx)]
            if op.finished_t is not None or self.cfg.asset(asset).stage != op.stage:
                skipped += 1
                continue
            src = self.assets.get(op.assigned or "")
            if src is not None and src.current == (o.id, int(idx)):
                if src.state in ("RUN", "SETUP") and src.id != asset:
                    skipped += 1
                    continue
                if src.id != asset:
                    src.current = None
            if op.assigned != asset or not op.planned:
                self._assign(o, int(idx), asset, planned=True)
                moved += 1
        for asset, ops in sequences.items():
            if asset in self.assets:
                self._act_resequence(asset, ops)
        self.dispatch_rule = "plan"
        return {"moved": moved, "skipped": skipped, "machines": len(sequences)}

    def _act_resequence(self, asset: str, order_ops: list[list[Any]], _actor: str = "system") -> dict[str, Any]:
        a = self._need_asset(asset)
        wanted = [(str(x[0]), int(x[1])) for x in order_ops]
        have = set(a.queue)
        head = [k for k in wanted if k in have]
        tail = [k for k in a.queue if k not in set(head)]
        a.queue = head + tail
        return {"asset": asset, "queue": len(a.queue)}

    def _act_set_hold(self, order: str, until_t: int, _actor: str = "system") -> dict[str, Any]:
        o = self.orders.get(order)
        if o is None:
            raise ActionRejected("unknown order")
        o.hold_until = int(until_t)
        return {"order": order, "hold_until": o.hold_until}

    def _act_set_priority(self, order: str, priority: int, _actor: str = "system") -> dict[str, Any]:
        o = self.orders.get(order)
        if o is None or priority not in (1, 2, 3):
            raise ActionRejected("bad order/priority")
        o.priority = int(priority)
        return {"order": order, "priority": o.priority}

    def _act_expedite_order(self, order: str, _actor: str = "system") -> dict[str, Any]:
        o = self.orders.get(order)
        if o is None:
            raise ActionRejected("unknown order")
        o.priority, o.expedited = 1, True
        return {"order": order, "priority": 1}

    def _act_set_amr_priority(self, scores: dict[str, float], _actor: str = "system") -> dict[str, Any]:
        self.amr_priority = {str(k): float(v) for k, v in scores.items()}
        return {"cells": len(self.amr_priority)}

    def _act_stage_spare(self, asset: str, spare: str, _actor: str = "system") -> dict[str, Any]:
        if spare not in self.spares:
            raise ActionRejected("unknown spare")
        self._need_asset(asset)
        self.amr_requests.insert(0, [self.t, asset])
        return {"asset": asset, "spare": spare, "staged": True}

    def _act_load_shift(
        self,
        utility: str,
        active: bool,
        until_t: int | None = None,
        hi: float | None = None,
        lo: float | None = None,
        _actor: str = "system",
    ) -> dict[str, Any]:
        sh = self.shifts.get(utility)
        if sh is None:
            raise ActionRejected(f"{utility} has no shiftable buffer")
        sh["active"] = bool(active)
        if until_t is not None:
            sh["until"] = int(until_t)
        if hi is not None:
            sh["hi"] = float(hi)
        if lo is not None:
            sh["lo"] = float(lo)
        return {"utility": utility, **{k: sh[k] for k in ("active", "until", "hi", "lo")}}

    def _act_safe_stop(
        self, asset: str | None = None, zone: str | None = None, _actor: str = "system"
    ) -> dict[str, Any]:
        targets = self._zone_members.get(zone, []) if zone else [asset]
        if not targets or targets == [None]:
            raise ActionRejected("safe_stop needs an asset or zone")
        for t in targets:
            self._need_asset(str(t)).safe_stop = True
        return {"stopped": list(targets)}

    def _act_resume(self, asset: str | None = None, zone: str | None = None, _actor: str = "system") -> dict[str, Any]:
        targets = self._zone_members.get(zone, []) if zone else [asset]
        for t in targets:
            if t is not None:
                self._need_asset(t).safe_stop = False
        return {"resumed": list(targets)}

    def _act_set_standby(self, asset: str, on: bool, _actor: str = "system") -> dict[str, Any]:
        a = self._need_asset(asset)
        if self.cfg.asset(asset).type not in PRODUCTION_TYPES:
            raise ActionRejected("standby applies to production assets")
        if on and a.state != "IDLE":
            raise ActionRejected("asset is not idle")
        a.standby = bool(on)
        return {"asset": asset, "standby": bool(on)}

    def _act_set_inline_inspect(self, asset: str, on: bool, _actor: str = "system") -> dict[str, Any]:
        self._need_asset(asset).inline_inspect = bool(on)
        return {"asset": asset, "inline_inspect": bool(on)}

    def _act_clear_jam(self, asset: str, _actor: str = "system") -> dict[str, Any]:
        a = self._need_asset(asset)
        j = a.flags.get("jam")
        if a.state != "DOWN" or not j or not j["recoverable"]:
            raise ActionRejected("no recoverable jam on this asset")
        a.repair_left = min(a.repair_left, j["remote"])
        a.flags.pop("jam", None)
        return {"asset": asset, "remaining_min": a.repair_left}

    def _act_set_safety_mode(self, mode: str, _actor: str = "system") -> dict[str, Any]:
        if mode not in ("hardwired", "agent"):
            raise ActionRejected("mode must be hardwired|agent")
        self.safety_mode = mode
        return {"safety_mode": mode}

    def _act_reorder_material(self, material: str, qty: float, _actor: str = "system") -> dict[str, Any]:
        m = self.inventory.get(material)
        if m is None:
            raise ActionRejected("unknown material")
        m["on_order"].append(
            [self.t + m["lead_h"] * 60 + (m["delay_min"] if m["delay_until"] > self.t else 0.0), float(qty), "manual"]
        )
        return {"material": material, "qty": qty}

    def _act_expedite_material(
        self, material: str, qty: float | None = None, mode: str = "expedite", _actor: str = "system"
    ) -> dict[str, Any]:
        m = self.inventory.get(material)
        if m is None:
            raise ActionRejected("unknown material")
        c = self.A["costs"]
        qty = float(qty if qty is not None else m["max"] - m["on_hand"])
        prem = c["expedite_premium"] if mode == "expedite" else c["alt_source_premium"]
        lead = max(120.0, m["lead_h"] * 60 * (0.35 if mode == "expedite" else 0.6))
        cost = qty * m["price_eur"] * (1.0 + prem)
        m["on_order"].append([self.t + lead, qty, mode])
        self.acc["expedite_cost"] += qty * m["price_eur"] * prem
        return {"material": material, "qty": qty, "eta": round(self.t + lead), "cost_eur": round(cost, 2), "mode": mode}

    # ------------------------------------------------------------------ queries
    def asset_public(self, aid: str) -> dict[str, Any]:
        spec = self.cfg.asset(aid)
        a = self.assets[aid]
        return {
            "id": aid,
            "name": spec.name,
            "type": spec.type,
            "area": spec.area,
            "line": spec.line,
            "cell": spec.cell,
            "zone": spec.zone,
            "index": spec.index,
            "state": a.state,
            "reason": a.reason,
            "speed": a.speed,
            "power_kw": round(a.power_kw, 2),
            "queue": len(a.queue),
            "current": list(a.current) if a.current else None,
            "safe_stop": a.safe_stop,
            "offset": round(a.offset, 3),
            "inline_inspect": a.inline_inspect,
            "kit": round(a.kit, 1),
            "sensors": {k: round(float(v), 3) for k, v in a.sens.items()},
            "temp": round(a.temp, 2),
        }

    def hidden_truth(self, aid: str) -> dict[str, Any]:
        """Ground truth used only by tests, the fault console and RCA evaluation - never by agents."""
        a = self.assets[aid]
        return {
            "health": a.health,
            "tool_wear": a.tool_wear,
            "thermal": a.thermal,
            "qdrift": a.qdrift,
            "flags": dict(a.flags),
        }

    def snapshot(self) -> dict[str, Any]:
        d = {k: v for k, v in self.__dict__.items() if k != "events"}
        return copy.deepcopy(d)

    def restore(self, snap: dict[str, Any]) -> None:
        keep_events = self.events
        self.__dict__.clear()
        self.__dict__.update(copy.deepcopy(snap))
        self.events = keep_events

    def fork(self) -> Plant:
        f = Plant.__new__(Plant)
        f.__dict__ = copy.deepcopy({k: v for k, v in self.__dict__.items() if k != "events"})
        f.events = []
        return f


def hash_plant(plant_id: str) -> int:
    import zlib

    return zlib.crc32(plant_id.encode())
