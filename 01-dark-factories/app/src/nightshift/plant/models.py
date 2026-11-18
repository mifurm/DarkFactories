"""Shared domain objects of the swarm: actions, proposals, plans, decisions and the EUR utility used for arbitration."""

from __future__ import annotations

import itertools
from dataclasses import asdict, dataclass, field
from typing import Any

_ids = itertools.count(1)


def next_id(prefix: str) -> str:
    return f"{prefix}-{next(_ids):05d}"


def reset_ids() -> None:
    global _ids
    _ids = itertools.count(1)


@dataclass
class Action:
    """A plant control action (see Plant.apply) plus the asset it mainly affects."""

    kind: str
    params: dict[str, Any] = field(default_factory=dict)
    target: str | None = None

    def to_sim(self) -> dict[str, Any]:
        return {"kind": self.kind, **self.params}

    def public(self) -> dict[str, Any]:
        return {"kind": self.kind, "params": self.params, "target": self.target}


# decision classes the policy engine governs (see policy/default_policy.yaml)
DECISION_CLASSES = (
    "maintenance.schedule",
    "maintenance.remote_clear",
    "schedule.replan",
    "schedule.expedite",
    "setpoint.adjust",
    "quality.containment",
    "energy.load_shift",
    "energy.defer_job",
    "materials.expedite",
    "materials.reorder",
    "amr.dispatch",
    "safety.protective_stop",
    "safety.restart",
    "process.recipe",
    "copilot.proposal",
    "energy.standby",
)

IMPACT_KEYS = ("maintenance_eur", "due_date_eur", "quality_eur", "energy_eur", "throughput_eur")


@dataclass
class Proposal:
    agent: str
    decision_class: str
    title: str
    actions: list[Action]
    rationale: str
    created_t: int
    expires_t: int
    evidence: list[dict[str, Any]] = field(default_factory=list)
    impact: dict[str, float] = field(default_factory=dict)  # EUR by category + optional physical units
    risk: float = 0.2
    cost_eur: float = 0.0
    assets: list[str] = field(default_factory=list)
    claims: list[str] = field(default_factory=list)  # resource keys used for conflict detection
    correlation: str = ""
    priority: int = 2
    horizon_min: int = 300  # how far the twin looks ahead when validating this proposal
    counterfactual: dict[str, Any] = field(default_factory=dict)
    expect: dict[str, Any] = field(default_factory=dict)  # what outcome to verify later
    id: str = field(default_factory=lambda: next_id("P"))
    status: str = "new"
    utility: float = 0.0
    utility_breakdown: dict[str, float] = field(default_factory=dict)
    narrative: str = ""

    def value_eur(self, weights: dict[str, float] | None = None) -> float:
        w = weights or {}
        return sum(float(self.impact.get(k, 0.0)) * w.get(k, 1.0) for k in IMPACT_KEYS)

    def public(self) -> dict[str, Any]:
        d = asdict(self)
        d["actions"] = [a.public() for a in self.actions]
        return d


@dataclass
class Plan:
    """Proposals that belong together (same correlation id) are arbitrated, validated and decided as one unit."""

    id: str
    trigger: str
    proposals: list[Proposal]
    utility: float = 0.0
    status: str = "new"
    whatif: dict[str, Any] | None = None
    decision: dict[str, Any] | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def actions(self) -> list[Action]:
        return [a for p in self.proposals for a in p.actions]

    @property
    def assets(self) -> list[str]:
        out: list[str] = []
        for p in self.proposals:
            for a in p.assets:
                if a not in out:
                    out.append(a)
        return out

    @property
    def cost_eur(self) -> float:
        return sum(p.cost_eur for p in self.proposals)

    @property
    def risk(self) -> float:
        return max((p.risk for p in self.proposals), default=0.0)

    @property
    def decision_class(self) -> str:
        return self.proposals[0].decision_class if self.proposals else "copilot.proposal"

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "trigger": self.trigger,
            "status": self.status,
            "utility": round(self.utility, 1),
            "decision_class": self.decision_class,
            "assets": self.assets,
            "cost_eur": self.cost_eur,
            "risk": self.risk,
            "proposals": [p.public() for p in self.proposals],
            "whatif": self.whatif,
            "decision": self.decision,
            "notes": self.notes,
        }
