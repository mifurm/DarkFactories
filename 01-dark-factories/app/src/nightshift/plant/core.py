"""PlantCore: one plant with its simulator, ledger, policy, inbox, twin, agent swarm and supervisor (synchronous, no I/O).

Used directly by the A/B replay and the tests (headless) and wrapped by PlantRuntime for the live, streaming plant."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from nightshift.features.df03_twin.twin import Twin
from nightshift.features.df04_swarm.core import Agent, Supervisor, WorldView
from nightshift.features.df05_maintenance.agent import PdMAgent
from nightshift.features.df05_maintenance.anomaly import SignatureLibrary
from nightshift.features.df06_quality.agent import QualityAgent
from nightshift.features.df07_planner.agent import PlannerAgent
from nightshift.features.df08_materials.agent import MaterialsAgent
from nightshift.features.df09_energy.agent import EnergyAgent
from nightshift.features.df10_safety.agent import SafetyAgent
from nightshift.features.df11_process.agent import ProcessAgent
from nightshift.features.df12_policy.engine import PolicyEngine
from nightshift.features.df13_inbox.inbox import Inbox
from nightshift.features.df14_ledger.ledger import Ledger
from nightshift.sim.config import PlantConfig, build_plant_config
from nightshift.sim.plant import Plant

ALL_AGENTS = ("maintenance", "quality", "planner", "materials", "energy", "safety", "process")
DEFAULT_AGENTS = ("maintenance", "quality", "planner", "materials", "energy", "safety")
AGENT_INTERVAL = 5


class PlantCore:
    def __init__(
        self,
        cfg: PlantConfig | str = "KAT-1",
        seed: int = 20261117,
        *,
        swarm: bool = True,
        agents: set[str] | tuple[str, ...] | None = None,
        sim_first: str = "surrogate",
        headless_latency: int | None = None,
        chaos_per_day: float = 0.0,
        writer: Any = None,
        metrics: Any = None,
        on_event: Callable[[str, dict[str, Any]], None] | None = None,
        library: SignatureLibrary | None = None,
        policy: PolicyEngine | None = None,
        initial_orders: int | None = None,
    ) -> None:
        self.cfg = build_plant_config(cfg) if isinstance(cfg, str) else cfg
        self.plant_id = self.cfg.plant_id
        self.plant = Plant(self.cfg, seed, chaos_per_day=chaos_per_day, initial_orders=initial_orders)
        self.ledger = Ledger(self.plant_id, writer=writer)
        self.policy = policy or PolicyEngine()
        self.inbox = Inbox(self.plant_id)
        self.twin = Twin(self.plant)
        self.swarm = swarm
        self.event_log: list[dict[str, Any]] = []
        self.library = library or SignatureLibrary()
        enabled = set(agents) if agents is not None else set(DEFAULT_AGENTS)
        self.pdm = PdMAgent(self.library)
        self.quality = QualityAgent()
        self.planner = PlannerAgent()
        self.materials = MaterialsAgent()
        self.energy = EnergyAgent()
        self.safety = SafetyAgent(self.policy, self.plant_id)
        self.process = ProcessAgent(self.twin)
        self.agents: list[Agent] = [
            self.safety,
            self.pdm,
            self.quality,
            self.planner,
            self.materials,
            self.energy,
            self.process,
        ]
        for a in self.agents:
            a.enabled = swarm and a.name in enabled
        self.supervisor = Supervisor(
            self.plant,
            self.ledger,
            self.policy,
            self.inbox,
            self.agents,
            safety=self.safety,
            twin=self.twin,
            sim_first=sim_first,
            headless_approval_latency=headless_latency,
            on_event=on_event or (lambda k, d: None),
            metrics=metrics,
        )
        if swarm and "safety" in enabled:
            self.plant.safety_mode = "agent"
        if swarm and "planner" in enabled:
            self.plant.dispatch_rule = "plan"
        if swarm and "quality" in enabled:
            self.plant.manual_qc = False

    # ------------------------------------------------------------------ stepping
    def tick(self) -> list[dict[str, Any]]:
        p = self.plant
        p.step()
        events = p.drain_events()
        self.event_log.extend(e for e in events if e["kind"] != "order_released")
        del self.event_log[:-4000]
        if self.swarm:
            self.supervisor.on_plant_events(events)
            self.supervisor.housekeeping()
            if p.t % AGENT_INTERVAL == 0:
                self.supervisor.cycle()
        return events

    def run(self, minutes: int) -> None:
        for _ in range(int(minutes)):
            self.tick()

    def world(self) -> WorldView:
        return WorldView(self.plant)

    def human_t(self) -> int:
        """Clock used for approval SLAs (see Supervisor._ht)."""
        return self.supervisor._ht()

    # ------------------------------------------------------------------ views for the API / UI
    def set_agent_enabled(self, name: str, enabled: bool) -> bool:
        for a in self.agents:
            if a.name == name:
                a.enabled = enabled
                if name == "safety":
                    self.plant.safety_mode = "agent" if enabled else "hardwired"
                if name == "planner":
                    self.plant.dispatch_rule = "plan" if enabled else "fifo"
                return True
        return False
