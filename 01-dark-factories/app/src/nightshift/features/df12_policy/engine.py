"""Policy-as-code engine (DF-12): autonomy dial, risk scoring, approval thresholds, blast radius, time-boxed grants,
break-glass, kill switch and hard guards. Pure and deterministic; enforced by the executor in the action path."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

from nightshift.plant.models import DECISION_CLASSES, Action, Plan

DEFAULT_POLICY_PATH = Path(__file__).with_name("default_policy.yaml")
LEVEL_NAMES = {
    0: "L0 Observe",
    1: "L1 Recommend",
    2: "L2 Approve-all",
    3: "L3 Auto low-risk",
    4: "L4 Supervised",
    5: "L5 Lights-out",
}


class Threshold(BaseModel):
    max_risk: float = Field(ge=0, le=1)
    max_assets: int = Field(ge=1)
    max_cost_eur: float = Field(ge=0)


class ClassRule(BaseModel):
    level: int = Field(ge=0, le=5)
    label: str = ""
    sim_first: bool = False
    sla_min: int = Field(default=30, ge=1)
    rate_per_hour: int = Field(default=12, ge=1)


class RiskWeights(BaseModel):
    w_risk: float = 0.6
    w_blast: float = 0.2
    w_cost: float = 0.2
    blast_assets_max: int = 8
    cost_max_eur: float = 10000


class PolicyRules(BaseModel):
    version: int = 1
    levels: dict[int, dict[str, str]] = Field(default_factory=dict)
    thresholds: dict[int, Threshold]
    risk_score: RiskWeights = RiskWeights()
    classes: dict[str, ClassRule]
    protected_assets: list[str] = Field(default_factory=list)
    forbidden: dict[str, list[float]] = Field(default_factory=dict)
    exempt_from_kill_switch: list[str] = Field(default_factory=list)

    @field_validator("classes")
    @classmethod
    def _known_classes(cls, v: dict[str, ClassRule]) -> dict[str, ClassRule]:
        unknown = set(v) - set(DECISION_CLASSES)
        if unknown:
            raise ValueError(f"unknown decision classes: {sorted(unknown)}")
        return v

    @model_validator(mode="after")
    def _monotonic(self) -> PolicyRules:
        t = self.thresholds
        for lo, hi in ((3, 4), (4, 5)):
            if (
                lo in t
                and hi in t
                and (
                    t[lo].max_risk > t[hi].max_risk
                    or t[lo].max_assets > t[hi].max_assets
                    or t[lo].max_cost_eur > t[hi].max_cost_eur
                )
            ):
                raise ValueError(f"thresholds must be monotonic: L{lo} must not exceed L{hi}")
        return self


def load_rules(text: str | None = None) -> PolicyRules:
    raw = yaml.safe_load(text) if text is not None else yaml.safe_load(DEFAULT_POLICY_PATH.read_text())
    return PolicyRules.model_validate(raw)


@dataclass
class PolicyDecision:
    outcome: str  # auto_approve | require_approval | deny | observe | recommend
    level: int
    effective_level: int
    risk_score: float
    reasons: list[str] = field(default_factory=list)
    rules: list[dict[str, str]] = field(default_factory=list)
    sla_min: int = 30
    needs_sim_first: bool = False

    def public(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome,
            "level": self.level,
            "effective_level": self.effective_level,
            "level_name": LEVEL_NAMES.get(self.effective_level, ""),
            "risk_score": round(self.risk_score, 3),
            "reasons": self.reasons,
            "rules": self.rules,
            "sla_min": self.sla_min,
            "needs_sim_first": self.needs_sim_first,
        }


PROTECTED_KINDS = {
    "safe_stop",
    "schedule_maintenance",
    "set_speed",
    "set_setpoint",
    "set_recipe",
    "tool_change",
    "set_standby",
    "clear_jam",
    "apply_plan",
    "set_inline_inspect",
}


class PolicyEngine:
    def __init__(self, rules: PolicyRules | None = None) -> None:
        self.rules = rules or load_rules()
        self.levels: dict[str, int] = {c: r.level for c, r in self.rules.classes.items()}
        self.global_cap = 5
        self.kill_switch = False
        self.kill_info: dict[str, Any] = {}
        self.break_glass: list[dict[str, Any]] = []
        self.timeboxes: list[dict[str, Any]] = []
        self._auto_log: dict[str, list[int]] = {}
        self._grant_seq = 0
        self.version = self.rules.version
        self.changes: list[dict[str, Any]] = []

    # ------------------------------------------------------------------ dial & state
    def set_level(self, cls: str, level: int, actor: str = "system", now_t: int = 0) -> None:
        if cls not in self.rules.classes:
            raise ValueError(f"unknown decision class {cls!r}")
        if not 0 <= level <= 5:
            raise ValueError("level must be 0..5")
        self.changes.append({"t": now_t, "class": cls, "from": self.levels[cls], "to": level, "actor": actor})
        self.levels[cls] = level

    def set_global_cap(self, level: int, actor: str = "system", now_t: int = 0) -> None:
        if not 0 <= level <= 5:
            raise ValueError("level must be 0..5")
        self.changes.append({"t": now_t, "class": "*", "from": self.global_cap, "to": level, "actor": actor})
        self.global_cap = level

    def set_kill_switch(self, on: bool, reason: str = "", actor: str = "system", now_t: int = 0) -> None:
        self.kill_switch = bool(on)
        self.kill_info = {"on": bool(on), "reason": reason, "actor": actor, "t": now_t}

    def grant_break_glass(
        self, cls: str, level: int, minutes: int, reason: str, actor: str, now_t: int
    ) -> dict[str, Any]:
        if not reason.strip():
            raise ValueError("break-glass requires a reason")
        if cls != "*" and cls not in self.rules.classes:
            raise ValueError(f"unknown decision class {cls!r}")
        self._grant_seq += 1
        g = {
            "id": f"BG-{self._grant_seq:03d}",
            "class": cls,
            "level": level,
            "until_t": now_t + minutes,
            "reason": reason,
            "actor": actor,
            "t": now_t,
        }
        self.break_glass.append(g)
        return g

    def grant_timebox(
        self, cls: str, minutes: int, max_cost_eur: float, max_risk: float, actor: str, now_t: int
    ) -> dict[str, Any]:
        if cls not in self.rules.classes:
            raise ValueError(f"unknown decision class {cls!r}")
        self._grant_seq += 1
        g = {
            "id": f"TB-{self._grant_seq:03d}",
            "class": cls,
            "until_t": now_t + minutes,
            "max_cost_eur": max_cost_eur,
            "max_risk": max_risk,
            "actor": actor,
            "t": now_t,
        }
        self.timeboxes.append(g)
        return g

    def active_grants(self, now_t: int) -> dict[str, list[dict[str, Any]]]:
        return {
            "break_glass": [g for g in self.break_glass if g["until_t"] > now_t],
            "timeboxes": [g for g in self.timeboxes if g["until_t"] > now_t],
        }

    def effective_level(self, cls: str, now_t: int) -> int:
        lvl = self.levels.get(cls, 2)
        for g in self.break_glass:
            if g["until_t"] > now_t and g["class"] in ("*", cls):
                lvl = max(lvl, g["level"])
        return min(lvl, self.global_cap) if self.global_cap < 5 else lvl

    # ------------------------------------------------------------------ guards (hard rules, no override)
    def check_action(self, action: Action) -> list[dict[str, str]]:
        v: list[dict[str, str]] = []
        f = self.rules.forbidden
        p = action.params
        if (
            action.kind == "set_speed"
            and "speed_pct" in f
            and not f["speed_pct"][0] <= float(p.get("pct", 100)) <= f["speed_pct"][1]
        ):
            v.append(
                {
                    "rule": "forbidden_setpoint",
                    "severity": "deny",
                    "detail": f"speed {p.get('pct')}% outside {f['speed_pct']}",
                }
            )
        if action.kind in ("set_setpoint", "set_recipe"):
            name, val = p.get("name"), float(p.get("value", 0))
            key = {"offset_comp": "offset_sigma", "melt_temp_c": "melt_temp_c"}.get(str(name))
            if key and key in f and not f[key][0] <= val <= f[key][1]:
                v.append({"rule": "forbidden_setpoint", "severity": "deny", "detail": f"{name}={val} outside {f[key]}"})
        if action.target and action.target in self.rules.protected_assets and action.kind in PROTECTED_KINDS:
            v.append(
                {"rule": "protected_asset", "severity": "approve", "detail": f"{action.target} is a protected asset"}
            )
        return v

    def guard_for_execution(
        self, action: Action, decision_class: str, actor: str, human_approved: bool
    ) -> list[dict[str, str]]:
        """Re-checked by the executor right before touching the plant: defence in depth."""
        out = [x for x in self.check_action(action) if x["severity"] == "deny"]
        if self.kill_switch and decision_class not in self.rules.exempt_from_kill_switch:
            out.append({"rule": "kill_switch", "severity": "deny", "detail": "global kill switch is engaged"})
        if not human_approved:
            for x in self.check_action(action):
                if x["severity"] == "approve":
                    out.append({**x, "severity": "deny", "detail": x["detail"] + " - human approval required"})
        return out

    # ------------------------------------------------------------------ evaluation
    def risk_score(self, risk: float, n_assets: int, cost_eur: float) -> float:
        w = self.rules.risk_score
        blast = min(1.0, n_assets / max(1, w.blast_assets_max))
        cost = min(1.0, cost_eur / max(1.0, w.cost_max_eur))
        return min(1.0, w.w_risk * risk + w.w_blast * blast + w.w_cost * cost)

    def _rate_ok(self, cls: str, now_t: int) -> bool:
        log = [t for t in self._auto_log.get(cls, []) if now_t - t < 60]
        self._auto_log[cls] = log
        return len(log) < self.rules.classes[cls].rate_per_hour

    def record_auto(self, cls: str, now_t: int) -> None:
        self._auto_log.setdefault(cls, []).append(now_t)

    def evaluate(self, plan: Plan, now_t: int) -> PolicyDecision:
        cls = plan.decision_class
        rule = self.rules.classes.get(cls) or self.rules.classes["copilot.proposal"]
        level = self.levels.get(cls, 2)
        eff = self.effective_level(cls, now_t)
        score = self.risk_score(plan.risk, len(plan.assets), plan.cost_eur)
        dec = PolicyDecision(
            "require_approval", level, eff, score, sla_min=rule.sla_min, needs_sim_first=rule.sim_first and eff >= 3
        )
        if eff < level:
            dec.rules.append({"rule": "global_cap", "effect": f"level capped to L{eff}"})
        if self.kill_switch and cls not in self.rules.exempt_from_kill_switch:
            dec.outcome = "deny"
            dec.reasons.append("kill switch engaged - all autonomous actions halted")
            dec.rules.append({"rule": "kill_switch", "effect": "deny"})
            return dec
        forced_approval = False
        for a in plan.actions:
            for v in self.check_action(a):
                dec.rules.append({"rule": v["rule"], "effect": v["severity"]})
                dec.reasons.append(v["detail"])
                if v["severity"] == "deny":
                    dec.outcome = "deny"
                    return dec
                forced_approval = True
        if eff == 0:
            dec.outcome = "observe"
            dec.reasons.append("L0: observe only")
            return dec
        if eff == 1:
            dec.outcome = "recommend"
            dec.reasons.append("L1: recommendation for a human to execute")
            return dec
        if forced_approval and not (eff >= 5 and any(g["until_t"] > now_t for g in self.break_glass)):
            dec.reasons.append("protected asset: human approval required")
            return dec
        for g in self.timeboxes:
            if (
                g["class"] == cls
                and g["until_t"] > now_t
                and plan.cost_eur <= g["max_cost_eur"]
                and plan.risk <= g["max_risk"]
            ):
                dec.outcome = "auto_approve"
                dec.reasons.append(f"time-boxed auto-approval {g['id']} (until sim t+{g['until_t'] - now_t} min)")
                dec.rules.append({"rule": "timebox", "effect": g["id"]})
                return dec
        if eff == 2:
            dec.reasons.append("L2: every action needs approval")
            return dec
        th = self.rules.thresholds[eff]
        over = []
        if score > th.max_risk:
            over.append(f"risk score {score:.2f} > L{eff} limit {th.max_risk:.2f}")
        if len(plan.assets) > th.max_assets:
            over.append(f"blast radius {len(plan.assets)} assets > L{eff} limit {th.max_assets}")
        if plan.cost_eur > th.max_cost_eur:
            over.append(f"cost EUR {plan.cost_eur:.0f} > L{eff} limit {th.max_cost_eur:.0f}")
        if over:
            dec.reasons.extend(over)
            dec.rules.append({"rule": "threshold", "effect": "escalate"})
            return dec
        if not self._rate_ok(cls, now_t):
            dec.reasons.append(f"rate limit: more than {rule.rate_per_hour} auto-actions/hour for {cls}")
            dec.rules.append({"rule": "rate_limit", "effect": "escalate"})
            return dec
        dec.outcome = "auto_approve"
        dec.reasons.append(
            f"L{eff} auto-approve: risk {score:.2f}, {len(plan.assets)} asset(s), EUR {plan.cost_eur:.0f} within limits"
        )
        dec.rules.append({"rule": "autonomy_level", "effect": f"L{eff}"})
        return dec

    def matrix(self, cls: str, risk: float, n_assets: int, cost_eur: float, now_t: int = 0) -> dict[str, str]:
        """Outcome of one hypothetical plan at every autonomy level (what the Autonomy Dial would do)."""
        out = {}
        saved, cap = self.levels[cls], self.global_cap
        try:
            self.global_cap = 5
            for lvl in range(6):
                self.levels[cls] = lvl
                p = Plan("matrix", "matrix", [])
                p.proposals = [_Probe(cls, risk, n_assets, cost_eur)]  # type: ignore[list-item]
                out[f"L{lvl}"] = self.evaluate(p, now_t).outcome
        finally:
            self.levels[cls] = saved
            self.global_cap = cap
        return out

    def snapshot(self, now_t: int) -> dict[str, Any]:
        return {
            "version": self.version,
            "kill_switch": self.kill_switch,
            "kill_info": self.kill_info,
            "global_cap": self.global_cap,
            "levels": self.levels,
            "level_names": LEVEL_NAMES,
            "classes": {
                c: {**r.model_dump(), "effective_level": self.effective_level(c, now_t)}
                for c, r in self.rules.classes.items()
            },
            "thresholds": {str(k): v.model_dump() for k, v in self.rules.thresholds.items()},
            "protected_assets": self.rules.protected_assets,
            "forbidden": self.rules.forbidden,
            "grants": self.active_grants(now_t),
            "changes": self.changes[-20:],
        }


class _Probe:
    """Stand-in proposal for matrix() so a plan can be built from three numbers."""

    def __init__(self, cls: str, risk: float, n: int, cost: float) -> None:
        self.decision_class, self.risk, self.cost_eur = cls, risk, cost
        self.assets = [f"A{i}" for i in range(n)]
        self.actions: list[Action] = []
