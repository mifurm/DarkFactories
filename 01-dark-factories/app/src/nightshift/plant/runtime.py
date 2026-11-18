"""PlantRuntime: the live, streaming plant (asyncio loop, SSE publishing, persistence, narration, handovers) on top of PlantCore."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any

from nightshift.core.llm import narrate
from nightshift.features.df05_maintenance.anomaly import SignatureLibrary
from nightshift.features.df13_inbox.inbox import TeamsNotifier
from nightshift.features.df19_kpi.engine import KpiEngine
from nightshift.plant.core import AGENT_INTERVAL, PlantCore
from nightshift.sim.config import PRODUCTION_TYPES
from nightshift.sim.faults import SCENARIO_INFO, fault_catalog, scenario_steps
from nightshift.sim.plant import ActionRejected

if TYPE_CHECKING:  # pragma: no cover
    from nightshift.core.runtime import Runtime

log = logging.getLogger("nightshift.plant")
COMMISSION_MIN = 180
MAX_SPEED = 30.0
SHIFT_STARTS = (6 * 60, 14 * 60, 22 * 60)


class PlantRuntime(PlantCore):
    def __init__(
        self,
        rt: Runtime,
        plant_id: str,
        seed: int,
        *,
        speed: float = 1.0,
        chaos_per_day: float = 3.0,
        library: SignatureLibrary | None = None,
        policy: Any = None,
    ) -> None:
        self.rt = rt
        self.hub = rt.hub
        self._init_args = dict(plant_id=plant_id, seed=seed, library=library, policy=policy)
        super().__init__(
            plant_id,
            seed,
            swarm=True,
            sim_first="full",
            chaos_per_day=0.0,
            writer=rt.writer,
            metrics=rt.metrics,
            on_event=self._on_swarm_event,
            library=library,
            policy=policy,
        )
        self.live_chaos = chaos_per_day
        self.speed = max(0.0, min(speed, MAX_SPEED))
        self.paused = False
        self._acc = 0.0
        self._task: asyncio.Task | None = None
        self._last_pub = 0.0
        self._last_hour = 0
        self.alerts: list[dict[str, Any]] = []
        self.activity: list[dict[str, Any]] = []
        self.reports: list[dict[str, Any]] = []
        self.pending_reports = 0
        self.teams = TeamsNotifier(rt.settings.teams_webhook_url)
        self.last_card: dict[str, Any] | None = None
        self._narr_queue: asyncio.Queue[str] = asyncio.Queue(maxsize=3)
        self._narr_task: asyncio.Task | None = None
        self._last_narr = 0.0
        self.narrations: list[dict[str, Any]] = []
        self.extras: dict[str, Any] = {}
        self.ledger.listeners.append(self._on_ledger)
        self.started = False
        self._wall0 = time.monotonic()
        self._install_human_clock()

    def _install_human_clock(self) -> None:
        factor = self.rt.settings.approval_clock_factor
        self.supervisor.human_clock = (
            (lambda: int((time.monotonic() - self._wall0) / 60.0 * factor)) if factor > 0 else None
        )

    # ------------------------------------------------------------------ lifecycle
    async def start(self, autostart: bool = True) -> None:
        try:
            await self.ledger.load_head(self.rt.repo)
            doc = await self.rt.repo.get("state", f"policy-{self.plant_id}", "policy")
            if doc:
                for cls, lvl in doc.get("levels", {}).items():
                    if cls in self.policy.levels:
                        self.policy.levels[cls] = int(lvl)
                self.policy.global_cap = int(doc.get("global_cap", 5))
                if doc.get("kill_switch"):
                    self.policy.set_kill_switch(
                        True, doc.get("kill_info", {}).get("reason", "restored after restart"), "restore", 0
                    )
        except Exception as exc:
            log.warning("ledger head / policy state not loaded (%s); starting fresh", type(exc).__name__)
        self.ledger.append(
            "system",
            f"Plant {self.plant_id} commissioned: {len(self.cfg.assets)} assets, swarm of {len([a for a in self.agents if a.enabled])} agents",
            agent="system",
            sim_t=0,
            sim_time=self.plant.now.isoformat(timespec="minutes"),
            payload={"seed": self.plant.seed, "agents": [a.name for a in self.agents if a.enabled]},
        )
        self.run(COMMISSION_MIN)  # agents learn healthy baselines; no faults during commissioning
        self.plant.chaos_per_day = self.live_chaos
        self.supervisor.sim_first = "full"
        self._narr_task = asyncio.create_task(self._narration_worker(), name=f"narr-{self.plant_id}")
        if autostart:
            self._task = asyncio.create_task(self._loop(), name=f"plant-{self.plant_id}")
        self.started = True

    async def stop(self) -> None:
        for t in (self._task, self._narr_task):
            if t:
                t.cancel()
        for t in (self._task, self._narr_task):
            if t:
                try:
                    await t
                except (asyncio.CancelledError, Exception):
                    pass

    async def reset(self) -> None:
        """Re-seed the demo: new simulator + swarm state; the ledger hash chain continues (history is never rewritten)."""
        head, nxt, anchor = self.ledger.head, self.ledger.last_seq + 1, self.ledger.anchor_hash
        old_entries, first_seq = list(self.ledger._entries), self.ledger._first_seq
        inbox_items = self.inbox.items
        PlantCore.__init__(
            self,
            self.plant_id,
            self._init_args["seed"],
            swarm=True,
            sim_first="full",
            chaos_per_day=0.0,
            writer=self.rt.writer,
            metrics=self.rt.metrics,
            on_event=self._on_swarm_event,
            library=self._init_args["library"],
            policy=self._init_args["policy"],
        )
        (
            self.ledger._entries,
            self.ledger._first_seq,
            self.ledger._head,
            self.ledger._next_seq,
            self.ledger.anchor_hash,
        ) = old_entries, first_seq, head, nxt, anchor
        self.ledger.listeners.append(self._on_ledger)
        self.inbox.items = inbox_items
        self._install_human_clock()
        self.ledger.append(
            "system", "Demo state reset (re-seeded simulator); ledger chain continues", agent="system", sim_t=0
        )
        self.run(COMMISSION_MIN)
        self.plant.chaos_per_day = self.live_chaos
        self.supervisor.sim_first = "full"
        self.alerts.clear()
        self.activity.clear()

    # ------------------------------------------------------------------ main loop
    async def _loop(self) -> None:
        last = time.monotonic()
        while True:
            await asyncio.sleep(0.2)
            now = time.monotonic()
            dt, last = now - last, now
            if self.paused or self.speed <= 0:
                if now - self._last_pub > 1.0:
                    self._publish_tick()
                continue
            self._acc += dt * self.speed
            n = int(self._acc)
            self._acc -= n
            for _ in range(min(n, 150)):
                self.live_tick()
            if now - self._last_pub >= 1.0:
                self._publish_tick()

    def live_tick(self) -> list[dict[str, Any]]:
        events = self.tick()
        p = self.plant
        for ev in events:
            if ev["kind"] in (
                "failure",
                "fault_injected",
                "repaired",
                "zone_clear",
                "zone_restart",
                "maintenance_start",
                "maintenance_done",
                "order_done",
                "tool_change",
            ):
                self._remember(ev)
        if p.t // 60 > self._last_hour:
            self._last_hour = p.t // 60
            self._hourly()
        mod = p.minute_of_day()
        if mod in SHIFT_STARTS and p.t > COMMISSION_MIN:
            self.pending_reports += 1
        self.rt.fleet and self.rt.fleet.on_tick(self)
        return events

    def _remember(self, ev: dict[str, Any]) -> None:
        item = {**ev, "sim_time": self.plant.now.isoformat(timespec="minutes")}
        self.alerts.append(item)
        del self.alerts[:-120]
        self.hub.publish(f"{self.plant_id}/alert", item)

    def _hourly(self) -> None:
        p = self.plant
        try:
            k = KpiEngine.compute(p, 60)
            doc = {
                "id": f"kpi-{p.t:08d}",
                "pk": self.plant_id,
                "t": p.t,
                "sim_time": p.now.isoformat(timespec="minutes"),
                "plant_kpi": _json_safe(k["plant_kpi"]),
                "impact_eur": k["impact_eur"],
            }
            self.rt.writer.enqueue("kpi", doc)
            for s in (
                self.cfg.assets if self.plant_id == self.rt.settings.primary_plant else ()
            ):  # per-asset aggregates: primary plant only (cost)
                metrics = {}
                for m in s.sensors:
                    agg = p.store.aggregates(s.id, m, bucket=60, buckets=1)
                    if agg and agg[0]["mean"] is not None:
                        metrics[m] = {
                            kk: round(vv, 3)
                            for kk, vv in agg[0].items()
                            if kk in ("mean", "min", "max") and vv is not None
                        }
                self.rt.writer.enqueue(
                    "telemetry",
                    {
                        "id": f"{s.id}-{p.t:08d}",
                        "pk": self.plant_id,
                        "asset": s.id,
                        "t": p.t,
                        "metrics": metrics,
                        "ttl": 3 * 86400,
                    },
                )
        except Exception as exc:
            log.warning("hourly persistence failed: %s", exc)

    # ------------------------------------------------------------------ events out
    def _on_ledger(self, e: dict[str, Any]) -> None:
        self.hub.publish(
            f"{self.plant_id}/ledger",
            {
                k: e[k]
                for k in (
                    "seq",
                    "sim_time",
                    "sim_t",
                    "kind",
                    "agent",
                    "asset",
                    "summary",
                    "outcome",
                    "decision_class",
                    "corr",
                )
            },
        )
        if e["kind"] in (
            "proposal",
            "decision",
            "action",
            "veto",
            "arbitration",
            "outcome",
            "whatif",
            "narration",
            "override",
        ):
            self.activity.append({k: e[k] for k in ("seq", "sim_time", "kind", "agent", "asset", "summary", "outcome")})
            del self.activity[:-200]

    def _on_swarm_event(self, kind: str, data: dict[str, Any]) -> None:
        self.hub.publish(f"{self.plant_id}/agent", {"event": kind, **data})
        if kind in ("executed", "inbox") and data.get("plan"):
            try:
                self._narr_queue.put_nowait(data["plan"])
            except asyncio.QueueFull:
                pass
        if kind == "inbox":
            item = self.inbox.get(data["item"])
            if item is not None:
                self.rt.writer.enqueue("approvals", {"id": item.id, "pk": self.plant_id, **item.public()})
                asyncio.get_event_loop().create_task(
                    self._notify(item)
                ) if self.teams.configured else self._card_preview(item)

    def _card_preview(self, item: Any) -> None:
        from nightshift.features.df13_inbox.inbox import adaptive_card

        self.last_card = adaptive_card(item)

    async def _notify(self, item: Any) -> None:
        self._card_preview(item)
        await self.teams.notify(item)

    # ------------------------------------------------------------------ narration (LLM, budget-aware, deterministic fallback)
    async def _narration_worker(self) -> None:
        while True:
            plan_id = await self._narr_queue.get()
            wait = 75 - (time.monotonic() - self._last_narr)
            if wait > 0:
                await asyncio.sleep(wait)
            plan = self.supervisor.plans.get(plan_id)
            if plan is None or not self.rt.settings.llm_narration:
                continue
            self._last_narr = time.monotonic()
            facts = {
                "plan": plan.public()["proposals"][0]["title"],
                "status": plan.status,
                "decision": plan.decision,
                "proposals": [
                    {
                        "agent": p.agent,
                        "title": p.title,
                        "rationale": p.rationale,
                        "impact": p.impact,
                        "risk": p.risk,
                        "cost_eur": p.cost_eur,
                        "utility_eur": round(p.utility, 1),
                    }
                    for p in plan.proposals
                ],
                "whatif": (plan.whatif or {}).get("explanation"),
            }
            text = await narrate(
                self.rt.llm,
                "swarm.negotiation",
                facts,
                "In 2-3 sentences explain to the plant manager how the agents negotiated this plan, which objectives traded off, and why the policy decided as it did.",
                lambda f: f"{f['plan']}: " + " ".join(p["rationale"] for p in f["proposals"][:2])[:400],
                max_tokens=350,
            )
            entry = self.ledger.append(
                "narration",
                text.text[:600],
                agent="supervisor-llm" if text.source == "azure" else "supervisor",
                assets=plan.assets,
                decision_class=plan.decision_class,
                corr=plan.id,
                outcome=text.source,
                sim_t=self.plant.t,
                sim_time=self.plant.now.isoformat(timespec="minutes"),
                payload={"model": text.model, "tokens": text.tokens},
            )
            self.narrations.append({"plan": plan.id, "text": text.text, "source": text.source, "seq": entry["seq"]})
            del self.narrations[:-50]
            plan.proposals[0].narrative = text.text

    # ------------------------------------------------------------------ control surface
    def set_speed(self, speed: float) -> float:
        self.speed = max(0.0, min(float(speed), MAX_SPEED))
        return self.speed

    def step_minutes(self, minutes: int) -> int:
        n = max(1, min(int(minutes), 720))
        for _ in range(n):
            self.live_tick()
        self._publish_tick(force=True)
        return n

    def inject(self, kind: str, **params: Any) -> dict[str, Any]:
        f = self.plant.inject_fault(kind, source="console", **params)
        self.ledger.append(
            "system",
            f"Fault injected via console: {kind} on {f.target}",
            agent="console",
            assets=[f.target] if f.target in self.plant.assets else [],
            outcome="fault_injected",
            payload={"fault": f.id, "kind": kind, "params": f.params},
            sim_t=self.plant.t,
            sim_time=self.plant.now.isoformat(timespec="minutes"),
        )
        return {"id": f.id, "kind": kind, "target": f.target, "params": f.params, "t": self.plant.t}

    def run_scenario(self, name: str) -> dict[str, Any]:
        steps = scenario_steps(name, self.cfg)
        for at, kind, params in steps:
            self.plant.schedule_fault(self.plant.t + at, kind, **params)
        self.ledger.append(
            "system",
            f"Scenario started: {name} - {SCENARIO_INFO[name]}",
            agent="console",
            outcome="scenario",
            payload={"steps": len(steps)},
            sim_t=self.plant.t,
            sim_time=self.plant.now.isoformat(timespec="minutes"),
        )
        return {
            "scenario": name,
            "steps": [{"at_min": a, "kind": k, "params": p} for a, k, p in steps],
            "description": SCENARIO_INFO[name],
        }

    def catalog(self) -> dict[str, Any]:
        return {
            "faults": fault_catalog(self.cfg),
            "scenarios": [{"id": k, "description": v} for k, v in SCENARIO_INFO.items()],
        }

    def direct_action(self, action: dict[str, Any], actor: str) -> dict[str, Any]:
        """Human control action (Control Tower): goes through the same guards as the agents (kill switch, forbidden setpoints)."""
        from nightshift.plant.models import Action

        a = Action(str(action.get("kind")), {k: v for k, v in action.items() if k != "kind"}, action.get("asset"))
        viol = self.policy.guard_for_execution(a, "copilot.proposal", actor, human_approved=True)
        if viol:
            self.ledger.append(
                "action",
                f"Manual action {a.kind} blocked: {viol[0]['detail']}",
                agent=actor,
                assets=[a.target] if a.target else [],
                outcome="blocked",
                payload={"violations": viol},
                sim_t=self.plant.t,
            )
            raise ActionRejected(viol[0]["detail"])
        res = self.plant.apply(a.to_sim(), actor=actor)
        self.ledger.append(
            "action",
            f"Manual action {a.kind} by {actor}",
            agent=actor,
            assets=[a.target] if a.target else [],
            outcome="executed",
            payload={"params": a.params, "result": res},
            sim_t=self.plant.t,
            sim_time=self.plant.now.isoformat(timespec="minutes"),
        )
        return res

    # ------------------------------------------------------------------ views
    def snapshot(self, full: bool = False) -> dict[str, Any]:
        p = self.plant
        assets = [p.asset_public(s.id) for s in self.cfg.assets]
        k = KpiEngine.compute(p, 480)["plant_kpi"]
        small = {
            m: k[m]
            for m in (
                "oee",
                "availability",
                "performance",
                "quality",
                "throughput_uph",
                "units_good",
                "otif",
                "scrap_pct",
                "downtime_min",
                "energy_kwh",
                "kwh_per_unit",
                "co2_per_unit_kg",
                "tardiness_h",
                "overdue_orders",
                "failures",
                "mtbf_h",
                "mttr_min",
                "energy_cost_eur",
                "peak_kw",
            )
        }
        zones = {z: {"occupied": v["occ"] > 0, "wait": v["wait"]} for z, v in p.zones.items()}
        out = {
            "plant": {
                "id": self.plant_id,
                "name": self.cfg.name,
                "location": self.cfg.location,
                "profile": self.cfg.profile,
            },
            "t": p.t,
            "sim_time": p.now.isoformat(timespec="minutes"),
            "speed": self.speed,
            "paused": self.paused,
            "kill_switch": self.policy.kill_switch,
            "kill_info": self.policy.kill_info,
            "global_cap": self.policy.global_cap,
            "price_eur_kwh": round(p.price_now or p.tariff_at(p.t), 4),
            "carbon_g_kwh": round(p.carbon_now or p.carbon_at(p.t)),
            "total_kw": round(p.total_kw, 1),
            "assets": assets,
            "kpi": _json_safe(small),
            "zones": zones,
            "inbox": self.inbox.stats(self.human_t()),
            "ledger": {"entries": self.ledger.last_seq, "head": self.ledger.head[:12]},
            "open_orders": len(p.open_orders()),
            "supervisor": {k2: v for k2, v in self.supervisor.stats.items()},
            "in_window": p.in_planned_window(p.t),
            "agents": [{"name": a.name, "role": a.role, "enabled": a.enabled} for a in self.agents],
        }
        if full:
            out["alerts"] = self.alerts[-40:]
            out["activity"] = self.activity[-60:]
        return out

    def _publish_tick(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_pub < 0.9:
            return
        self._last_pub = now
        self.hub.publish(f"{self.plant_id}/tick", self.snapshot())

    def summary(self) -> dict[str, Any]:
        p = self.plant
        k = KpiEngine.compute(p, 480)["plant_kpi"]
        return {
            "id": self.plant_id,
            "name": self.cfg.name,
            "location": self.cfg.location,
            "profile": self.cfg.profile,
            "assets": len(self.cfg.assets),
            "sim_time": p.now.isoformat(timespec="minutes"),
            "oee": k["oee"],
            "otif": k["otif"],
            "throughput_uph": k["throughput_uph"],
            "downtime_min": k["downtime_min"],
            "kwh_per_unit": k["kwh_per_unit"],
            "co2_per_unit_kg": k["co2_per_unit_kg"],
            "scrap_pct": k["scrap_pct"],
            "pending_approvals": len(self.inbox.pending()),
            "kill_switch": self.policy.kill_switch,
        }

    @property
    def production_assets(self) -> list[str]:
        return [s.id for s in self.cfg.assets if s.type in PRODUCTION_TYPES]


def _json_safe(d: dict[str, Any]) -> dict[str, Any]:
    return {k: (None if isinstance(v, float) and v != v else v) for k, v in d.items()}


__all__ = ["AGENT_INTERVAL", "PlantRuntime"]
