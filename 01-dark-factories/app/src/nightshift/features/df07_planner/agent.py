"""Production Planner agent (DF-07): finite-capacity re-planning on disruption, rush orders and shortages."""

from __future__ import annotations

from typing import Any

from nightshift.features.df04_swarm.core import Agent, Blackboard, WorldView
from nightshift.features.df07_planner.scheduler import Schedule, build_schedule, check_feasibility
from nightshift.plant.models import Action, Proposal


class PlannerAgent(Agent):
    name = "planner"
    role = "Production Planner"
    decision_classes = ("schedule.replan", "schedule.expedite")

    def __init__(self) -> None:
        super().__init__()
        self.last_plan_t = -(10**9)
        self.last_sig: tuple[Any, ...] = ()
        self.schedule: Schedule | None = None
        self.baseline: Schedule | None = None
        self.violations: list[str] = []
        self.replans = 0

    # ------------------------------------------------------------------ helpers
    def _signature(self, w: WorldView) -> tuple[Any, ...]:
        down = tuple(
            sorted(a for a in w.ids("CNC", "PRESS", "ASM", "TEST", "PACK") if w.asset(a).state in ("DOWN", "MAINT"))
        )
        wos = tuple(sorted((x.asset, x.start_t) for x in w.work_orders))
        orders = tuple(sorted(o.id for o in w.open_orders() if o.priority == 1 or o.rush))
        return down, wos, orders

    def _diff(self, w: WorldView, sched: Schedule) -> tuple[list[list[Any]], dict[str, list[list[Any]]], set[str]]:
        changes: list[list[Any]] = []
        touched: set[str] = set()
        for (oid, idx), asset in sched.assignments().items():
            op = w.order(oid).ops[idx]
            if op.assigned != asset or not op.planned:
                changes.append([oid, idx, asset])
                if op.assigned and op.assigned != asset:
                    touched.update({op.assigned, asset})
        seqs = {mid: [[o, i] for o, i in seq] for mid, seq in sched.sequences().items() if seq}
        return changes, seqs, touched

    def _proposal(self, w: WorldView, sched: Schedule, base: Schedule, why: str, corr: str = "") -> Proposal | None:
        changes, seqs, touched = self._diff(w, sched)
        if not changes and not touched:
            return None
        saved_eur = max(0.0, base.tardiness_eur - sched.tardiness_eur)
        saved_min = max(0.0, base.tardiness_min - sched.tardiness_min)
        phys = sorted(touched)[:4]
        rationale = (
            f"{why} {len(changes)} operation(s) (re)assigned and {len(seqs)} machine queue(s) re-sequenced by priority class and critical "
            f"ratio. Projected tardiness {sched.tardiness_min / 60:.1f} h / {sched.late_orders} late order(s) versus "
            f"{base.tardiness_min / 60:.1f} h / {base.late_orders} late under FIFO (saves ~{saved_min / 60:.1f} h, EUR {saved_eur:,.0f})."
        )
        return self.prop(
            w,
            "schedule.replan",
            f"Re-plan shop floor ({len(changes)} changes)",
            [Action("apply_plan", {"assignments": changes, "sequences": seqs}, phys[0] if phys else None)],
            rationale,
            correlation=corr,
            assets=phys,
            claims=["schedule:plan"],
            risk=0.08,
            cost_eur=0.0,
            expires_t=w.t + 30,
            priority=2,
            evidence=[
                {
                    "type": "schedule",
                    "ref": "planner/cr",
                    "tardiness_min": round(sched.tardiness_min),
                    "late_orders": sched.late_orders,
                },
                {
                    "type": "schedule",
                    "ref": "planner/fifo",
                    "tardiness_min": round(base.tardiness_min),
                    "late_orders": base.late_orders,
                },
            ],
            impact={"due_date_eur": round(saved_eur, 0)},
            counterfactual={"fifo_tardiness_min": round(base.tardiness_min), "fifo_late_orders": base.late_orders},
        )

    # ------------------------------------------------------------------ cycle
    def perceive(self, w: WorldView, board: Blackboard) -> list[Proposal]:
        blocked: dict[str, list[tuple[float, float]]] = {}
        sched = build_schedule(w, "cr", blocked)
        base = build_schedule(w, "fifo", blocked)
        self.schedule, self.baseline = sched, base
        self.violations = check_feasibility(sched, w)
        sig = self._signature(w)
        unplanned = sum(
            1
            for o in w.open_orders()
            for op in o.ops
            if op.finished_t is None and not op.planned and op.assigned is None
        )
        disruption = sig != self.last_sig
        gain = base.tardiness_eur - sched.tardiness_eur
        if board.get("pdm.pending") and w.t - self.last_plan_t < 15:
            return []
        due = (
            (disruption and w.t - self.last_plan_t >= 5)
            or (unplanned and w.t - self.last_plan_t >= 10)
            or (gain >= 40 and w.t - self.last_plan_t >= 10)
        )
        if not due:
            return []
        why = (
            "Disruption or new demand detected."
            if disruption
            else "Unplanned operations in the pool."
            if unplanned
            else "A better sequence exists."
        )
        p = self._proposal(w, sched, base, why)
        if p is None:
            self.last_sig = sig
            return []
        self.last_plan_t = w.t
        self.last_sig = sig
        self.replans += 1
        return [p]

    def respond(self, w: WorldView, board: Blackboard, proposals: list[Proposal]) -> list[Proposal]:
        out: list[Proposal] = []
        for p in proposals:
            if p.decision_class != "maintenance.schedule":
                continue
            act = p.actions[0].params
            aid = act["asset"]
            blocked = {aid: [(float(act["start_t"]), float(act["start_t"] + act["duration"]))]}
            sched = build_schedule(w, "cr", blocked)
            base = build_schedule(w, "fifo", blocked)
            sc_noplan = build_schedule(w, "cr", {})
            pr = self._proposal(
                w,
                sched,
                base,
                f"Maintenance on {aid} is booked {self._fmt(w, act['start_t'])}; the planner moves its job set to peers "
                f"and re-sequences around the window.",
                corr=p.correlation,
            )
            if pr is None:
                continue
            pr.impact["due_date_eur"] = round(
                max(0.0, sc_noplan.tardiness_eur - sched.tardiness_eur) + pr.impact.get("due_date_eur", 0.0), 0
            )
            self.last_plan_t = w.t
            out.append(pr)
            self.schedule, self.baseline = sched, base
            self.violations = check_feasibility(sched, w)
        return out

    @staticmethod
    def _fmt(w: WorldView, t: int) -> str:
        from datetime import timedelta

        return "at " + (w.now + timedelta(minutes=t - w.t)).strftime("%H:%M")

    # ------------------------------------------------------------------ explanation
    def explain(self, order_id: str | None = None) -> dict[str, Any]:
        s, b = self.schedule, self.baseline
        if s is None or b is None:
            return {"summary": "No schedule yet.", "orders": []}
        rows = []
        for oid, end in sorted(s.order_end.items(), key=lambda kv: kv[1]):
            if order_id and oid != order_id:
                continue
            slots = [x for x in s.slots if x.order == oid]
            rows.append(
                {
                    "order": oid,
                    "projected_end": round(end),
                    "baseline_end": round(b.order_end.get(oid, end)),
                    "ops": [
                        {
                            "stage": x.stage,
                            "asset": x.asset,
                            "start": round(x.start),
                            "end": round(x.end),
                            "why": x.reason,
                        }
                        for x in slots
                    ],
                }
            )
        return {
            "summary": (
                f"Priority-class + critical-ratio list scheduling over {len(s.machines)} machines. Projected tardiness "
                f"{s.tardiness_min / 60:.1f} h ({s.late_orders} late) vs FIFO {b.tardiness_min / 60:.1f} h ({b.late_orders} late); "
                f"utilisation {s.utilization:.0%}, changeover time {s.setups:.0f} min."
            ),
            "orders": rows[:40],
        }
