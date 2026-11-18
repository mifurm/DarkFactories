"""Swarm runtime (DF-04): world view, blackboard, agent base class, executor and the Shift Supervisor (orchestrator).

Pipeline per cycle: perceive -> respond -> de-duplicate -> group into plans -> utility -> Safety veto -> conflict arbitration
-> sim-first validation -> policy decision -> execute / inbox -> ledger at every step.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import numpy as np

from nightshift.features.df12_policy.engine import PolicyEngine
from nightshift.features.df13_inbox.inbox import Inbox
from nightshift.features.df14_ledger.ledger import Ledger
from nightshift.plant.models import Action, Plan, Proposal, next_id
from nightshift.sim.plant import ActionRejected, Plant

log = logging.getLogger("nightshift.swarm")
RISK_EXPOSURE_EUR = 100.0
DEFAULT_WEIGHTS = {
    "maintenance_eur": 1.0,
    "due_date_eur": 1.0,
    "quality_eur": 1.0,
    "energy_eur": 0.8,
    "throughput_eur": 1.0,
}


class WorldView:
    """Read-only, observable view of the plant. Hidden state (true health, tool wear, injected faults) is NOT exposed."""

    def __init__(self, plant: Plant) -> None:
        self._p = plant
        self.t = plant.t
        self.now = plant.now
        self.cfg = plant.cfg
        self.A = plant.A
        self.price_now = plant.price_now or plant.tariff_at(plant.t)
        self.carbon_now = plant.carbon_now or plant.carbon_at(plant.t)
        self.pools = plant.cfg.pools
        self.safety_mode = plant.safety_mode
        self.work_orders = [wo for wo in plant.work_orders.values() if wo.status in ("scheduled", "active")]
        self.inventory = plant.inventory
        self.spares = plant.spares
        self.shifts = plant.shifts
        self.minute_of_day = plant.minute_of_day()

    def ids(self, *types: str) -> list[str]:
        return [a.id for a in self.cfg.assets if not types or a.type in types]

    def spec(self, aid: str):
        return self.cfg.asset(aid)

    def asset(self, aid: str) -> SimpleNamespace:
        a = self._p.assets[aid]
        return SimpleNamespace(
            id=aid,
            state=a.state,
            reason=a.reason,
            speed=a.speed,
            power_kw=a.power_kw,
            queue=list(a.queue),
            current=a.current,
            safe_stop=a.safe_stop,
            offset=a.offset,
            inline_inspect=a.inline_inspect,
            last_maint_t=a.last_maint_t,
            kit=a.kit,
            recipe=dict(a.recipe),
            repair_left=a.repair_left,
            maint_left=a.maint_left,
            battery=a.battery,
            failures=a.failures,
            last_failure_t=a.last_failure_t,
            last_family=a.last_family,
            units=a.units,
            scrap=a.scrap,
            kwh=a.kwh,
            standby=a.standby,
        )

    def series(self, aid: str, metric: str, n: int = 60) -> np.ndarray:
        return self._p.store.series(aid, metric, n)

    def latest(self, aid: str, metric: str) -> float:
        return self._p.store.latest(aid, metric)

    def has_metric(self, aid: str, metric: str) -> bool:
        return self._p.store.has(aid, metric)

    def open_orders(self):
        return self._p.open_orders()

    def order(self, oid: str):
        return self._p.orders.get(oid)

    def tariff(self, t: int) -> float:
        return self._p.tariff_at(t)

    def carbon(self, t: int) -> float:
        return self._p.carbon_at(t)

    def zone_occupied(self, zone: str) -> bool:
        z = self._p.zones.get(zone)
        return bool(z and (z["occ"] > 0 or z["wait"] > 0))

    def zone_state(self, zone: str) -> tuple[float, float]:
        z = self._p.zones.get(zone) or {"occ": 0.0, "wait": 0.0}
        return z["occ"], z["wait"]

    def zone_members(self, zone: str) -> list[str]:
        return list(self._p._zone_members.get(zone, []))

    def windows(self, horizon_min: int = 1440) -> list[tuple[int, int]]:
        return self._p.next_planned_windows(self.t, horizon_min)

    def amr_requests(self) -> list[list[Any]]:
        return list(self._p.amr_requests)

    def amr_ids(self) -> list[str]:
        return list(self._p._amr_ids)

    def recent_events(self) -> list[dict[str, Any]]:
        return list(self._p.events)


class Blackboard:
    def __init__(self) -> None:
        self.facts: dict[str, Any] = {}

    def post(self, key: str, value: Any) -> None:
        self.facts[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        return self.facts.get(key, default)

    def drop(self, key: str) -> None:
        self.facts.pop(key, None)


class Agent:
    """Base class: ``perceive`` produces primary proposals; ``respond`` reacts to the other agents' proposals."""

    name = "agent"
    role = "Agent"
    decision_classes: tuple[str, ...] = ()
    interval = 1  # in supervisor cycles
    max_proposals = 6

    def __init__(self) -> None:
        self.enabled = True
        self.last_run = -(10**9)
        self.stats = {
            "cycles": 0,
            "proposals": 0,
            "errors": 0,
            "executed": 0,
            "vetoed": 0,
            "rejected": 0,
            "pending": 0,
            "denied": 0,
        }
        self.latency_ms: list[float] = []

    def perceive(self, w: WorldView, board: Blackboard) -> list[Proposal]:
        return []

    def respond(self, w: WorldView, board: Blackboard, proposals: list[Proposal]) -> list[Proposal]:
        return []

    def on_event(self, ev: dict[str, Any], w: WorldView, board: Blackboard) -> None:
        return None

    def prop(
        self, w: WorldView, decision_class: str, title: str, actions: list[Action], rationale: str, **kw: Any
    ) -> Proposal:
        kw.setdefault("expires_t", w.t + 180)
        return Proposal(
            agent=self.name,
            decision_class=decision_class,
            title=title,
            actions=actions,
            rationale=rationale,
            created_t=w.t,
            **kw,
        )

    def info(self) -> dict[str, Any]:
        lat = sorted(self.latency_ms[-200:])
        return {
            "name": self.name,
            "role": self.role,
            "enabled": self.enabled,
            "decision_classes": list(self.decision_classes),
            "stats": dict(self.stats),
            "p50_ms": round(lat[len(lat) // 2], 3) if lat else 0.0,
            "p95_ms": round(lat[int(len(lat) * 0.95)], 3) if lat else 0.0,
        }


@dataclass
class Veto:
    agent: str
    rule: str
    reason: str


class Executor:
    """The only code path that touches the plant: guards are re-checked here (defence in depth) and every action is ledgered."""

    def __init__(self, plant: Plant, policy: PolicyEngine, ledger: Ledger) -> None:
        self.plant, self.policy, self.ledger = plant, policy, ledger
        self.executed = 0
        self.blocked = 0

    def execute(self, plan: Plan, actor: str, human_approved: bool = False) -> dict[str, Any]:
        t = self.plant.t
        cls = plan.decision_class
        sim_time = self.plant.now.isoformat(timespec="minutes")
        blocked: list[dict[str, str]] = []
        for a in plan.actions:
            blocked += self.policy.guard_for_execution(a, cls, actor, human_approved)
        if blocked:
            self.blocked += 1
            self.ledger.append(
                "action",
                f"Execution blocked for plan {plan.id}: {blocked[0]['detail']}",
                agent=actor,
                assets=plan.assets,
                decision_class=cls,
                outcome="blocked",
                rationale="; ".join(b["rule"] for b in blocked),
                payload={"violations": blocked},
                corr=plan.id,
                sim_t=t,
                sim_time=sim_time,
            )
            plan.status = "blocked"
            return {"ok": False, "blocked": blocked, "results": []}
        results = []
        ok = True
        for p in plan.proposals:
            for a in p.actions:
                try:
                    res = self.plant.apply(a.to_sim(), actor=p.agent)
                    results.append({"action": a.kind, "ok": True, "result": res})
                    self.ledger.append(
                        "action",
                        f"{p.agent}: {a.kind} {a.target or ''}".strip(),
                        agent=p.agent,
                        assets=[a.target] if a.target else p.assets,
                        decision_class=cls,
                        outcome="executed",
                        payload={"params": a.params, "result": res},
                        corr=plan.id,
                        ref=p.id,
                        sim_t=t,
                        sim_time=sim_time,
                    )
                    self.executed += 1
                except ActionRejected as exc:
                    ok = False
                    results.append({"action": a.kind, "ok": False, "error": str(exc)})
                    self.ledger.append(
                        "action",
                        f"{p.agent}: {a.kind} rejected by plant: {exc}",
                        agent=p.agent,
                        assets=[a.target] if a.target else p.assets,
                        decision_class=cls,
                        outcome="rejected_by_plant",
                        payload={"params": a.params, "error": str(exc)},
                        corr=plan.id,
                        ref=p.id,
                        sim_t=t,
                        sim_time=sim_time,
                    )
        plan.status = "executed" if ok else "partial"
        self.policy.record_auto(cls, t)
        return {"ok": ok, "results": results}


class Supervisor:
    """The Shift Supervisor: runs the agents, arbitrates, validates, applies policy and executes."""

    def __init__(
        self,
        plant: Plant,
        ledger: Ledger,
        policy: PolicyEngine,
        inbox: Inbox,
        agents: list[Agent],
        *,
        safety: Any = None,
        twin: Any = None,
        sim_first: str = "surrogate",
        headless_approval_latency: int | None = None,
        on_event: Callable[[str, dict[str, Any]], None] | None = None,
        metrics: Any = None,
    ) -> None:
        self.plant, self.ledger, self.policy, self.inbox = plant, ledger, policy, inbox
        self.agents = agents
        self.safety = safety
        self.twin = twin
        self.sim_first = sim_first
        self.latency = headless_approval_latency  # A/B replay: humans approve after this many sim-minutes
        self.human_clock: Callable[[], int] | None = (
            None  # live: approval SLAs follow (scaled) wall-clock time, not simulated time
        )
        self.on_event = on_event or (lambda kind, data: None)
        self.metrics = metrics
        self.board = Blackboard()
        self.executor = Executor(plant, policy, ledger)
        self.weights = dict(DEFAULT_WEIGHTS)
        self.plans: dict[str, Plan] = {}
        self.cooldown: dict[str, int] = {}  # claim key -> sim minute until which it is considered handled
        self.expectations: list[dict[str, Any]] = []
        self.cycles = 0
        self.stats = {
            "proposals": 0,
            "plans": 0,
            "auto": 0,
            "approvals": 0,
            "denied": 0,
            "vetoed": 0,
            "arbitrated": 0,
            "sim_rejected": 0,
            "executed": 0,
            "expired": 0,
        }
        self._pending_exec: dict[str, Plan] = {}

    # ------------------------------------------------------------------ helpers
    def agent(self, name: str) -> Agent | None:
        return next((a for a in self.agents if a.name == name), None)

    def _t(self) -> int:
        return self.plant.t

    def _ht(self) -> int:
        """Clock for human-in-the-loop timers (SLA, escalation, expiry)."""
        return self.human_clock() if self.human_clock else self.plant.t

    def _sim_time(self) -> str:
        return self.plant.now.isoformat(timespec="minutes")

    def _log(self, kind: str, summary: str, **kw: Any) -> dict[str, Any]:
        kw.setdefault("sim_t", self._t())
        kw.setdefault("sim_time", self._sim_time())
        return self.ledger.append(kind, summary, **kw)

    def _emit(self, kind: str, data: dict[str, Any]) -> None:
        self.on_event(kind, data)

    # ------------------------------------------------------------------ cycle
    def cycle(self) -> list[Plan]:
        self.cycles += 1
        w = WorldView(self.plant)
        t = w.t
        proposals: list[Proposal] = []
        for ag in self.agents:
            if not ag.enabled or self.cycles % max(1, ag.interval):
                continue
            t0 = time.perf_counter()
            try:
                ps = ag.perceive(w, self.board)[: ag.max_proposals]
            except Exception:
                ag.stats["errors"] += 1
                log.exception("agent %s perceive failed", ag.name)
                ps = []
            ms = (time.perf_counter() - t0) * 1000
            ag.latency_ms.append(ms)
            del ag.latency_ms[:-400]
            ag.stats["cycles"] += 1
            ag.stats["proposals"] += len(ps)
            if self.metrics is not None:
                self.metrics.observe_agent(ag.name, "cycle", ms)
            proposals += ps
        for ag in self.agents:
            if not ag.enabled:
                continue
            try:
                resp = ag.respond(w, self.board, proposals)[: ag.max_proposals]
            except Exception:
                ag.stats["errors"] += 1
                log.exception("agent %s respond failed", ag.name)
                resp = []
            ag.stats["proposals"] += len(resp)
            proposals += resp
        proposals = [p for p in proposals if not self._cooling(p, t)]
        if proposals:
            self.stats["proposals"] += len(proposals)
        plans = self._group(proposals)
        for plan in plans:
            self._score(plan)
        plans.sort(key=lambda p: -p.utility)
        handled: list[Plan] = []
        claimed: dict[str, Plan] = {}
        for plan in plans:
            self.plans[plan.id] = plan
            self.stats["plans"] += 1
            for p in plan.proposals:
                self._log(
                    "proposal",
                    f"{p.agent}: {p.title}",
                    agent=p.agent,
                    assets=p.assets,
                    decision_class=p.decision_class,
                    rationale=p.rationale,
                    outcome="proposed",
                    counterfactual=p.counterfactual,
                    corr=plan.id,
                    ref=p.id,
                    payload={
                        "impact": p.impact,
                        "risk": p.risk,
                        "cost_eur": p.cost_eur,
                        "evidence": p.evidence[:6],
                        "actions": [a.public() for a in p.actions],
                        "utility": round(p.utility, 1),
                    },
                )
                self._emit(
                    "proposal", {"plan": plan.id, "agent": p.agent, "title": p.title, "class": p.decision_class, "t": t}
                )
            if self._safety_veto(plan):
                handled.append(plan)
                continue
            clash = next((claimed[c] for p in plan.proposals for c in p.claims if c in claimed), None)
            if clash is not None:
                self._arbitrated_out(plan, clash)
                handled.append(plan)
                continue
            for p in plan.proposals:
                for c in p.claims:
                    claimed[c] = plan
            if self._validate(plan):
                self._decide(plan)
            handled.append(plan)
        for plan in handled:
            for p in plan.proposals:
                self._set_cooldown(p, t, plan.status)
        self._expire(t)
        return handled

    def submit(self, p: Proposal) -> Plan:
        """Run an externally created proposal (copilot, API) through the full pipeline: veto, sim-first validation, policy, execute/inbox."""
        plan = Plan(id=next_id("PLN"), trigger=p.id, proposals=[p])
        self._score(plan)
        self.plans[plan.id] = plan
        self.stats["proposals"] += 1
        self.stats["plans"] += 1
        self._log(
            "proposal",
            f"{p.agent}: {p.title}",
            agent=p.agent,
            assets=p.assets,
            decision_class=p.decision_class,
            rationale=p.rationale,
            outcome="proposed",
            corr=plan.id,
            ref=p.id,
            payload={"actions": [a.public() for a in p.actions], "risk": p.risk},
        )
        if self._safety_veto(plan):
            return plan
        if self._validate(plan):
            self._decide(plan)
        return plan

    # ------------------------------------------------------------------ cooldown / grouping / scoring
    def _cooling(self, p: Proposal, t: int) -> bool:
        return any(self.cooldown.get(c, -1) > t for c in p.claims)

    def _set_cooldown(self, p: Proposal, t: int, status: str) -> None:
        span = {
            "executed": 90,
            "pending_approval": 120,
            "approved": 90,
            "vetoed": 30,
            "rejected_arbitration": 15,
            "denied": 60,
            "rejected_simulation": 45,
            "observed": 60,
            "recommended": 120,
            "blocked": 30,
            "partial": 60,
        }.get(status, 20)
        for c in p.claims:
            self.cooldown[c] = max(self.cooldown.get(c, 0), t + span)

    def _group(self, proposals: list[Proposal]) -> list[Plan]:
        groups: dict[str, list[Proposal]] = {}
        order: list[str] = []
        for p in proposals:
            key = p.correlation or p.id
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append(p)
        return [Plan(id=next_id("PLN"), trigger=k, proposals=groups[k]) for k in order]

    def _score(self, plan: Plan) -> None:
        total = 0.0
        for p in plan.proposals:
            val = p.value_eur(self.weights)
            u = val - p.cost_eur - p.risk * RISK_EXPOSURE_EUR
            p.utility = u
            p.utility_breakdown = {
                "value_eur": round(val, 1),
                "cost_eur": round(-p.cost_eur, 1),
                "risk_penalty_eur": round(-p.risk * RISK_EXPOSURE_EUR, 1),
            }
            total += u
        plan.utility = total

    # ------------------------------------------------------------------ safety veto, arbitration
    def _safety_veto(self, plan: Plan) -> bool:
        if self.safety is None or not self.safety.enabled or plan.decision_class == "safety.protective_stop":
            return False
        vetoes: list[Veto] = self.safety.review(plan, WorldView(self.plant))
        if not vetoes:
            return False
        plan.status = "vetoed"
        self.stats["vetoed"] += 1
        for p in plan.proposals:
            ag = self.agent(p.agent)
            if ag:
                ag.stats["vetoed"] += 1
            p.status = "vetoed"
        v = vetoes[0]
        self._log(
            "veto",
            f"Safety veto ({v.rule}): {v.reason}",
            agent="safety",
            assets=plan.assets,
            decision_class=plan.decision_class,
            outcome="vetoed",
            rationale="; ".join(f"{x.rule}: {x.reason}" for x in vetoes),
            corr=plan.id,
            payload={"vetoes": [x.__dict__ for x in vetoes], "plan": plan.public()["proposals"][0]["title"]},
        )
        self._emit("veto", {"plan": plan.id, "rule": v.rule, "reason": v.reason})
        if self.metrics is not None:
            self.metrics.observe_agent("safety", "veto")
        return True

    def _arbitrated_out(self, loser: Plan, winner: Plan) -> None:
        loser.status = "rejected_arbitration"
        self.stats["arbitrated"] += 1
        for p in loser.proposals:
            p.status = "rejected_arbitration"
            ag = self.agent(p.agent)
            if ag:
                ag.stats["rejected"] += 1
        self._log(
            "arbitration",
            f"Plan {loser.id} lost arbitration to {winner.id} (utility {loser.utility:.0f} vs {winner.utility:.0f})",
            agent="supervisor",
            assets=loser.assets,
            decision_class=loser.decision_class,
            outcome="rejected_arbitration",
            rationale="Overlapping resource claims; the plan with the higher explicit EUR utility wins. "
            f"Winner: {winner.proposals[0].title}.",
            corr=loser.id,
            payload={
                "winner": winner.id,
                "utilities": {loser.id: round(loser.utility, 1), winner.id: round(winner.utility, 1)},
            },
        )

    # ------------------------------------------------------------------ sim-first validation
    def _validate(self, plan: Plan) -> bool:
        dec = self.policy.evaluate(plan, self._t())
        plan.decision = {"policy": dec.public()}
        if not dec.needs_sim_first or dec.outcome in ("deny", "observe"):
            return True
        if self.sim_first == "off":
            return True
        if self.sim_first == "full" and self.twin is not None:
            res = self.twin.simulate_ahead(
                [a for a in plan.actions],
                horizon_min=max(p.horizon_min for p in plan.proposals),
                estimates=self.board.get("pdm.estimates", {}),
            )
            plan.whatif = res
            self._log(
                "whatif",
                f"Sim-first: plan {plan.id} projected net {res['delta']['net_value_eur']:+.0f} EUR over {res['horizon_min']} min",
                agent="twin",
                assets=plan.assets,
                decision_class=plan.decision_class,
                outcome="pass" if res["accept"] else "fail",
                rationale=res["explanation"],
                counterfactual=res["counterfactual"],
                corr=plan.id,
                payload=res,
            )
            if res["accept"]:
                for p in plan.proposals:
                    p.counterfactual = {**p.counterfactual, **res["counterfactual"]}
                return True
            self._reject_sim(plan, res["explanation"])
            return False
        # surrogate: the agents' own impact estimates stand in for a fork run (headless replays)
        if plan.utility > 0:
            plan.whatif = {"mode": "surrogate", "accept": True, "delta": {"net_value_eur": round(plan.utility, 1)}}
            return True
        self._reject_sim(plan, f"surrogate estimate negative ({plan.utility:.0f} EUR)")
        return False

    def _reject_sim(self, plan: Plan, why: str) -> None:
        plan.status = "rejected_simulation"
        self.stats["sim_rejected"] += 1
        for p in plan.proposals:
            p.status = "rejected_simulation"
        self._log(
            "decision",
            f"Plan {plan.id} rejected by sim-first validation: {why}",
            agent="supervisor",
            assets=plan.assets,
            decision_class=plan.decision_class,
            outcome="rejected_simulation",
            rationale=why,
            corr=plan.id,
        )

    # ------------------------------------------------------------------ policy decision
    def _decide(self, plan: Plan) -> None:
        t = self._t()
        dec = self.policy.evaluate(plan, t)
        plan.decision = {"policy": dec.public()}
        cls = plan.decision_class
        first = plan.proposals[0]
        base = dict(
            agent="supervisor",
            assets=plan.assets,
            decision_class=cls,
            corr=plan.id,
            payload={"policy": dec.public(), "utility": round(plan.utility, 1)},
        )
        for p in plan.proposals:
            p.status = dec.outcome
        if dec.outcome == "deny":
            plan.status = "denied"
            self.stats["denied"] += 1
            self._count(plan, "denied")
            self._log(
                "decision",
                f"DENIED by policy: {first.title}",
                outcome="denied",
                rationale="; ".join(dec.reasons),
                **base,
            )
            self._emit("decision", {"plan": plan.id, "outcome": "denied", "title": first.title, "reasons": dec.reasons})
        elif dec.outcome == "observe":
            plan.status = "observed"
            self._log(
                "decision",
                f"L0 observe-only: {first.title}",
                outcome="observed",
                rationale="; ".join(dec.reasons),
                **base,
            )
        elif dec.outcome in ("require_approval", "recommend"):
            advisory = dec.outcome == "recommend"
            plan.status = "recommended" if advisory else "pending_approval"
            item = self.inbox.add(
                plan,
                dec,
                self._ht(),
                self._explanation(plan, dec),
                advisory=advisory,
                validity_min=None if self.human_clock is None else 8 * dec.sla_min,
            )
            self._pending_exec[item.id] = plan
            self.stats["approvals"] += 1
            self._count(plan, "pending")
            self._log(
                "decision",
                f"{'Recommendation' if advisory else 'Approval required'}: {first.title}",
                outcome=plan.status,
                rationale="; ".join(dec.reasons) or "policy requires a human decision",
                ref=item.id,
                **base,
            )
            self._emit("inbox", {"item": item.id, "title": item.title, "plan": plan.id, "advisory": advisory})
            if self.latency is not None and not advisory:
                item.flags = {"auto_at": t + self.latency}  # type: ignore[attr-defined]
        else:
            plan.status = "approved"
            self.stats["auto"] += 1
            self._log(
                "decision",
                f"AUTO-APPROVED ({dec.reasons[0] if dec.reasons else 'policy'}): {first.title}",
                outcome="auto_approved",
                rationale="; ".join(dec.reasons),
                **base,
            )
            self._run(plan, "supervisor", human=False)

    def _count(self, plan: Plan, key: str) -> None:
        for p in plan.proposals:
            ag = self.agent(p.agent)
            if ag:
                ag.stats[key] = ag.stats.get(key, 0) + 1

    def _explanation(self, plan: Plan, dec: Any) -> str:
        parts = [p.rationale for p in plan.proposals[:3]]
        parts.append("Why a human: " + ("; ".join(dec.reasons) if dec.reasons else "policy"))
        if plan.whatif and plan.whatif.get("explanation"):
            parts.append("What-if: " + plan.whatif["explanation"])
        return " ".join(parts)

    def _run(self, plan: Plan, actor: str, human: bool) -> dict[str, Any]:
        res = self.executor.execute(plan, actor, human_approved=human)
        if res["ok"]:
            self.stats["executed"] += 1
            self._count(plan, "executed")
            for p in plan.proposals:
                if p.expect:
                    self.expectations.append({"plan": plan.id, "proposal": p.id, "t": self._t(), **p.expect})
        self._emit("executed", {"plan": plan.id, "ok": res["ok"], "title": plan.proposals[0].title, "actor": actor})
        return res

    # ------------------------------------------------------------------ human resolution & housekeeping
    def resolve(self, item_id: str, option: str, actor: str, comment: str = "") -> dict[str, Any]:
        item = self.inbox.resolve(item_id, option, actor, self._ht(), comment)
        plan = self._pending_exec.get(item_id)
        out: dict[str, Any] = {"item": item.public(self._ht()), "executed": None}
        if option == "defer" or plan is None:
            return out
        if option == "reject":
            plan.status = "rejected"
            self._log(
                "override",
                f"{actor} rejected: {plan.proposals[0].title}",
                agent=actor,
                assets=plan.assets,
                decision_class=plan.decision_class,
                outcome="rejected_by_human",
                rationale=comment or "rejected in the approvals inbox",
                corr=plan.id,
                ref=item_id,
            )
            self._pending_exec.pop(item_id, None)
            return out
        self._log(
            "override",
            f"{actor} approved: {plan.proposals[0].title}",
            agent=actor,
            assets=plan.assets,
            decision_class=plan.decision_class,
            outcome="approved_by_human",
            rationale=comment or "approved in the approvals inbox",
            corr=plan.id,
            ref=item_id,
        )
        self._pending_exec.pop(item_id, None)
        if item.advisory:
            return out
        out["executed"] = self._run(plan, actor, human=True)
        return out

    def housekeeping(self) -> list[tuple[str, Any]]:
        """Called every sim minute: SLA timers, human latency emulation (replays) and outcome tracking."""
        t = self._t()
        events = self.inbox.tick(self._ht())
        for kind, item in events:
            plan = self._pending_exec.pop(item.id, None) if kind == "expired" else None
            if plan is not None:
                plan.status = "expired"
                self.stats["expired"] += 1
                self._log(
                    "decision",
                    f"Approval expired ({item.resolution}): {item.title}",
                    agent="supervisor",
                    assets=plan.assets,
                    decision_class=plan.decision_class,
                    outcome="expired",
                    rationale="No human decision before the SLA ran out - fail-safe: nothing executed.",
                    corr=plan.id,
                    ref=item.id,
                )
            self._log(
                "system",
                f"Inbox item {item.id} {kind} -> {item.assigned_role}",
                agent="inbox",
                outcome=kind,
                ref=item.id,
            )
            self._emit("inbox_event", {"item": item.id, "event": kind, "role": item.assigned_role})
        if self.latency is not None:
            for item in list(self.inbox.pending()):
                at = getattr(item, "flags", {}).get("auto_at")
                if at is not None and t >= at and item.id in self._pending_exec:
                    self.resolve(
                        item.id, "approve", "emulated-operator", "replay: approval after assumed human latency"
                    )
        return list(events)

    def _expire(self, t: int) -> None:
        for k in [k for k, v in self.cooldown.items() if v < t - 600]:
            del self.cooldown[k]
        for pid in [k for k, pl in self.plans.items() if pl.proposals and t - pl.proposals[0].created_t > 1440]:
            del self.plans[pid]

    def on_plant_events(self, events: list[dict[str, Any]]) -> None:
        """Observations + outcome tracking from the plant's event stream."""
        for ev in events:
            kind = ev["kind"]
            a = ev.get("asset")
            if kind == "failure":
                self._log(
                    "observation",
                    f"Failure on {a}: {ev.get('cause')} (repair ~{ev.get('repair_min')} min)",
                    agent="plant",
                    assets=[a] if a else [],
                    outcome="failure",
                    payload=ev,
                    sim_t=ev["t"],
                )
                for ex in self.expectations:
                    if ex.get("asset") == a and not ex.get("closed"):
                        ex["closed"] = True
                        self._log(
                            "outcome",
                            f"Failure on {a} occurred despite plan {ex['plan']}",
                            agent="supervisor",
                            assets=[a],
                            outcome="failure_not_avoided",
                            corr=ex["plan"],
                            sim_t=ev["t"],
                        )
                self._emit("alert", {"kind": "failure", "asset": a, "cause": ev.get("cause"), "t": ev["t"]})
            elif kind == "maintenance_done":
                for ex in self.expectations:
                    if ex.get("asset") == a and ex.get("wo") == ev.get("wo") and not ex.get("closed"):
                        ex["closed"] = True
                        mttr = self.plant.cfg.asset(str(a)).params["mttr_min"]
                        loss = self.plant.cfg.asset(str(a)).params["loss_eur_per_min"]
                        self._log(
                            "outcome",
                            f"Planned maintenance on {a} completed - predicted failure avoided (~{mttr} min unplanned downtime, EUR {mttr * loss:,.0f} loss)",
                            agent="supervisor",
                            assets=[a],
                            outcome="failure_avoided",
                            corr=ex["plan"],
                            counterfactual={
                                "avoided_downtime_min": mttr,
                                "avoided_loss_eur": round(mttr * loss, 0),
                                "predicted_failure_t": ex.get("predicted_failure_t"),
                            },
                            payload=ev,
                            sim_t=ev["t"],
                        )
                        self._emit("outcome", {"asset": a, "outcome": "failure_avoided", "t": ev["t"]})
            elif kind in ("zone_clear", "zone_restart"):
                self._log(
                    "observation",
                    f"Safety zone {ev.get('zone')} {'cleared' if kind == 'zone_clear' else 'restarted'}",
                    agent="safety",
                    outcome=kind,
                    payload=ev,
                    sim_t=ev["t"],
                )
            elif kind == "order_done" and ev.get("late_min", 0) > 0:
                self._log(
                    "observation",
                    f"Order {ev['order']} shipped {ev['late_min']} min late",
                    agent="plant",
                    outcome="late_order",
                    payload=ev,
                    sim_t=ev["t"],
                )
            for ag in self.agents:
                if ag.enabled:
                    try:
                        ag.on_event(ev, WorldView(self.plant) if kind in ("failure", "repaired") else None, self.board)  # type: ignore[arg-type]
                    except Exception:
                        ag.stats["errors"] += 1

    def info(self) -> dict[str, Any]:
        return {
            "cycles": self.cycles,
            "stats": dict(self.stats),
            "weights": dict(self.weights),
            "sim_first": self.sim_first,
            "agents": [a.info() for a in self.agents],
            "cooldowns": len(self.cooldown),
            "pending": len(self._pending_exec),
        }


__all__ = ["Agent", "Blackboard", "Executor", "Supervisor", "Veto", "WorldView", "field"]
