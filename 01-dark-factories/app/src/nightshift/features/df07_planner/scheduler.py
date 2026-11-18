"""Finite-capacity scheduler (DF-07): critical-ratio list scheduling with setups, lot-streaming precedence, machine
availability (breakdowns, planned maintenance) and a feasibility validator."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from nightshift.features.df04_swarm.core import WorldView


@dataclass
class Slot:
    order: str
    idx: int
    stage: str
    asset: str
    start: float
    end: float
    setup: float
    work: float
    reason: str = ""
    pinned: bool = False


@dataclass
class MachineState:
    id: str
    free_at: float
    last_family: str | None
    speed: float
    setup_min: float
    blocked: list[tuple[float, float]] = field(default_factory=list)
    slots: list[Slot] = field(default_factory=list)
    down_until: float = 0.0


@dataclass
class Schedule:
    rule: str
    now: int
    slots: list[Slot]
    order_end: dict[str, float]
    tardiness_min: float
    tardiness_eur: float
    late_orders: int
    makespan: float
    utilization: float
    machines: dict[str, MachineState]
    setups: float = 0.0
    notes: list[str] = field(default_factory=list)

    def assignments(self) -> dict[tuple[str, int], str]:
        return {(s.order, s.idx): s.asset for s in self.slots}

    def sequences(self) -> dict[str, list[tuple[str, int]]]:
        out: dict[str, list[tuple[str, int]]] = {}
        for mid, m in self.machines.items():
            out[mid] = [(s.order, s.idx) for s in sorted(m.slots, key=lambda x: x.start)]
        return out

    def public(self) -> dict[str, Any]:
        return {
            "rule": self.rule,
            "now": self.now,
            "tardiness_min": round(self.tardiness_min, 1),
            "tardiness_eur": round(self.tardiness_eur, 0),
            "late_orders": self.late_orders,
            "makespan_min": round(self.makespan - self.now, 1),
            "utilization": round(self.utilization, 3),
            "setup_min": round(self.setups, 1),
            "order_end": {k: round(v) for k, v in self.order_end.items()},
            "slots": [
                {
                    "order": s.order,
                    "idx": s.idx,
                    "stage": s.stage,
                    "asset": s.asset,
                    "start": round(s.start),
                    "end": round(s.end),
                    "setup": round(s.setup),
                    "reason": s.reason,
                    "pinned": s.pinned,
                }
                for s in self.slots
            ],
            "notes": self.notes,
        }


def _place(m: MachineState, start: float, work: float) -> float:
    """End time of ``work`` minutes starting no earlier than ``start``; work pauses while the machine is blocked."""
    cur, rem = start, work
    for bs, be in sorted(m.blocked):
        if be <= cur:
            continue
        if bs <= cur:
            cur = be
            continue
        if cur + rem <= bs:
            break
        rem -= bs - cur
        cur = be
    return cur + rem


def build_schedule(
    w: WorldView,
    rule: str = "cr",
    extra_blocked: dict[str, list[tuple[float, float]]] | None = None,
    exclude: set[str] | None = None,
) -> Schedule:
    """rule 'cr' = priority class + critical ratio (planner); 'fifo' = release order (what the MES would do)."""
    now = float(w.t)
    A = w.A
    batch = A["orders"]["transfer_batch"]
    machines: dict[str, MachineState] = {}
    for ids in w.pools.values():
        for mid in ids:
            a = w.asset(mid)
            sp = w.spec(mid)
            free = now
            if a.state == "DOWN":
                free = now + a.repair_left
            elif a.state == "MAINT":
                free = now + a.maint_left
            elif a.safe_stop:
                free = now + 10
            m = MachineState(
                mid,
                free,
                getattr(a, "last_family", None),
                max(0.4, a.speed / 100.0),
                float(sp.params["setup_min"]),
                down_until=free,
            )
            for wo in w.work_orders:
                if wo.asset == mid and wo.status == "scheduled":
                    m.blocked.append((float(wo.start_t), float(wo.start_t + wo.duration)))
            for iv in (extra_blocked or {}).get(mid, []):
                m.blocked.append(iv)
            if exclude and mid in exclude:
                m.free_at = now + 24 * 60
            machines[mid] = m
    # pinned ops: running or in set-up on their machine
    pinned: dict[tuple[str, int], str] = {}
    for ids in w.pools.values():
        for mid in ids:
            a = w.asset(mid)
            if a.current and a.state in ("RUN", "SETUP"):
                pinned[a.current] = mid
    orders = w.open_orders()
    tard_rate = A["costs"]["tardiness_eur_per_hour"]

    def remaining_flow(o: Any) -> float:
        rem = [max(0.0, o.qty - op.done) * op.cycle for op in o.ops if op.finished_t is None]
        return (max(rem) + 0.25 * (sum(rem) - max(rem))) if rem else 0.0

    key: Callable[[Any], tuple[Any, ...]]
    if rule == "fifo":
        key = lambda o: (o.released, o.id)  # noqa: E731
    else:  # stable: priority class first (rush orders), then release order - no re-ordering churn between cycles
        key = lambda o: (o.priority, o.released, o.id)  # noqa: E731
    slots: list[Slot] = []
    placed: dict[tuple[str, int], Slot] = {}
    order_end: dict[str, float] = {}
    setups = 0.0
    for o in sorted(orders, key=key):
        for idx, op in enumerate(o.ops):
            if op.finished_t is not None:
                continue
            ready = max(now, float(o.hold_until))
            min_end = 0.0
            if idx > 0:
                ps = placed.get((o.id, idx - 1))
                if ps is not None:
                    ready = max(ready, ps.start + min(batch * o.ops[idx - 1].cycle, ps.end - ps.start))
                    min_end = ps.end + op.cycle
            remaining = max(1.0, o.qty - op.done)
            cands = [pinned[(o.id, idx)]] if (o.id, idx) in pinned else w.pools[op.stage]
            best: tuple[float, float, str, float, float, float] | None = None
            for mid in cands:
                m = machines[mid]
                setup = (
                    m.setup_min if (m.last_family and m.last_family != op.family and (o.id, idx) not in pinned) else 0.0
                )
                start = max(m.free_at, ready) + setup
                work = remaining * op.cycle / m.speed
                end = max(_place(m, start, work), min_end)
                cand = (end, setup, mid, start, work, setup)
                if best is None or cand[:2] < best[:2]:
                    best = cand
            assert best is not None
            end, setup, mid, start, work, _ = best
            m = machines[mid]
            m.free_at = end
            m.last_family = op.family
            setups += setup
            alt = sorted(cands)[:1]
            reason = f"{op.stage} on {mid}: earliest finish {end - now:.0f} min from now" + (
                f", +{setup:.0f} min changeover" if setup else ""
            )
            if (o.id, idx) in pinned:
                reason = f"{op.stage} already running on {mid}"
            elif m.blocked:
                reason += "; plans around a maintenance window on " + mid
            elif len(cands) > 1 and alt and alt[0] != mid:
                reason += f"; chosen over {alt[0]}"
            slot = Slot(o.id, idx, op.stage, mid, start - setup, end, setup, work, reason, (o.id, idx) in pinned)
            slots.append(slot)
            m.slots.append(slot)
            placed[(o.id, idx)] = slot
            order_end[o.id] = max(order_end.get(o.id, 0.0), end)
    tard = 0.0
    eur = 0.0
    late = 0
    for o in orders:
        e = order_end.get(o.id, now)
        lateness = max(0.0, e - o.due)
        if lateness > 0:
            late += 1
        tard += lateness
        eur += lateness / 60.0 * tard_rate[o.priority]
    makespan = max((s.end for s in slots), default=now)
    busy = sum(s.work for s in slots)
    util = busy / max(1.0, len(machines) * max(1.0, makespan - now))
    return Schedule(rule, w.t, slots, order_end, tard, eur, late, makespan, min(1.0, util), machines, setups)


def check_feasibility(s: Schedule, w: WorldView) -> list[str]:
    """Violations of the capacity / precedence / availability constraints (empty list = feasible)."""
    out: list[str] = []
    eps = 1e-6
    by_machine: dict[str, list[Slot]] = {}
    for sl in s.slots:
        by_machine.setdefault(sl.asset, []).append(sl)
        if sl.start < s.now - eps:
            out.append(f"{sl.order}/{sl.idx} starts in the past")
    for mid, sls in by_machine.items():
        sls.sort(key=lambda x: x.start)
        for a, b in zip(sls, sls[1:], strict=False):
            if b.start < a.end - eps - b.setup:
                out.append(f"capacity overlap on {mid}: {a.order}/{a.idx} and {b.order}/{b.idx}")
        m = s.machines[mid]
        for sl in sls:
            blocked = sum(max(0.0, min(sl.end, be) - max(sl.start + sl.setup, bs)) for bs, be in m.blocked)
            if sl.end - (sl.start + sl.setup) - blocked + eps < sl.work and not sl.pinned:
                out.append(f"{sl.order}/{sl.idx} on {mid} does not fit around blocked intervals")
    idx = {(sl.order, sl.idx): sl for sl in s.slots}
    for (oid, i), sl in idx.items():
        prev = idx.get((oid, i - 1))
        if prev is not None and (sl.start + sl.setup < prev.start - eps or sl.end < prev.end - eps):
            out.append(f"precedence violated for {oid}: op {i} vs op {i - 1}")
    return out
