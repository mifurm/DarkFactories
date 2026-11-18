"""Safety & Compliance Sentinel (DF-10): zone intrusion handling, veto over every other agent, forbidden-setpoint guards,
protected-asset rules, simulated cyber-hygiene posture and immutable audit hooks (via the ledger)."""

from __future__ import annotations

from typing import Any

import numpy as np

from nightshift.features.df04_swarm.core import Agent, Blackboard, Veto, WorldView
from nightshift.features.df12_policy.engine import PolicyEngine
from nightshift.plant.models import Action, Plan, Proposal

CYBER_CHECKS = [
    ("PLC firmware at vendor-recommended level", "patching", 3),
    ("Default credentials removed on PLC/HMI", "identity", 5),
    ("OPC UA anonymous access disabled", "identity", 4),
    ("OT/IT segmentation (Purdue L3.5 DMZ) enforced", "network", 5),
    ("Remote access only via MFA + jump host", "identity", 5),
    ("Defender for IoT sensor monitoring the cell network", "monitoring", 3),
    ("USB / removable-media policy on engineering stations", "endpoint", 2),
    ("PLC program backups verified < 30 days", "resilience", 3),
    ("Time synchronisation (NTP) on all controllers", "hygiene", 1),
    ("HMI/SCADA OS patch level < 60 days", "patching", 3),
    ("Certificates valid > 30 days (OPC UA / MQTT)", "pki", 2),
    ("Controller logs forwarded to SIEM", "monitoring", 3),
]


def cyber_posture(plant_id: str, seed: int = 7) -> dict[str, Any]:
    """Simulated posture: deterministic per plant, a few failing/warning controls so the finding list is non-trivial."""
    rng = np.random.default_rng(sum(map(ord, plant_id)) * 131 + seed)
    checks: list[dict[str, Any]] = []
    for name, domain, weight in CYBER_CHECKS:
        r = float(rng.random())
        status = "pass" if r > 0.30 else "warn" if r > 0.12 else "fail"
        checks.append({"check": name, "domain": domain, "weight": weight, "status": status})
    total = sum(c["weight"] for c in checks)
    got = sum(c["weight"] * {"pass": 1.0, "warn": 0.5, "fail": 0.0}[c["status"]] for c in checks)
    return {
        "score": round(100 * got / total, 1),
        "checks": checks,
        "simulated": True,
        "note": "Simulated posture - in production fed by Defender for IoT / Defender for Cloud.",
    }


class SafetyAgent(Agent):
    name = "safety"
    role = "Safety & Compliance Sentinel"
    decision_classes = ("safety.protective_stop", "safety.restart")

    def __init__(self, policy: PolicyEngine, plant_id: str = "KAT-1") -> None:
        super().__init__()
        self.policy = policy
        self.cyber = cyber_posture(plant_id)
        self.stopped_zones: set[str] = set()
        self.intrusions: list[dict[str, Any]] = []
        self.vetoes: list[dict[str, Any]] = []

    # ------------------------------------------------------------------ intrusion handling
    def perceive(self, w: WorldView, board: Blackboard) -> list[Proposal]:
        props: list[Proposal] = []
        zones = {w.spec(a).zone for a in w.ids()}
        for z in sorted(zones):
            occ, wait = w.zone_state(z)
            members = [m for m in w.zone_members(z) if w.spec(m).type in ("CNC", "PRESS", "ASM", "TEST", "PACK")]
            if occ > 0 and z not in self.stopped_zones and members:
                self.stopped_zones.add(z)
                self.intrusions.append({"t": w.t, "zone": z, "event": "intrusion", "occupied_min": occ})
                props.append(
                    self.prop(
                        w,
                        "safety.protective_stop",
                        f"Protective stop of zone {z}",
                        [Action("safe_stop", {"zone": z}, members[0])],
                        f"Personnel detected in {z} (area scanner). Machines {', '.join(members)} stopped and locked out; verified restart follows clearance.",
                        assets=members[:8],
                        claims=[f"zone:{z}:stop"],
                        risk=0.02,
                        cost_eur=0.0,
                        expires_t=w.t + 15,
                        priority=1,
                        impact={"throughput_eur": 0.0},
                        counterfactual={"hazard": "unguarded motion with a person in the cell"},
                    )
                )
            elif occ <= 0 and wait > 0 and z in self.stopped_zones and members:
                self.stopped_zones.discard(z)
                self.intrusions.append({"t": w.t, "zone": z, "event": "cleared"})
                props.append(
                    self.prop(
                        w,
                        "safety.restart",
                        f"Verified restart of zone {z}",
                        [Action("resume", {"zone": z}, members[0])],
                        f"Zone {z} has been clear for the verification interval; remote restart replaces the manual reset walk (25 min in the hard-wired baseline).",
                        assets=members[:8],
                        claims=[f"zone:{z}:restart"],
                        risk=0.04,
                        cost_eur=0.0,
                        expires_t=w.t + 15,
                        priority=1,
                        impact={"throughput_eur": round(len(members) * 25 * 4.0, 0)},
                    )
                )
            elif occ <= 0 and wait <= 0:
                self.stopped_zones.discard(z)
        return props

    # ------------------------------------------------------------------ veto
    def review(self, plan: Plan, w: WorldView) -> list[Veto]:
        out: list[Veto] = []
        for a in plan.actions:
            asset = a.target or a.params.get("asset")
            if asset and asset in w._p.assets:
                zone = w.spec(asset).zone
                occ, wait = w.zone_state(zone)
                if occ > 0 and a.kind not in ("safe_stop",):
                    out.append(
                        Veto(
                            self.name,
                            "zone_occupied",
                            f"personnel in {zone} ({occ:.0f} more min): {a.kind} on {asset} not allowed",
                        )
                    )
            for v in self.policy.check_action(a):
                if v["severity"] == "deny":
                    out.append(Veto(self.name, v["rule"], v["detail"]))
        if out:
            self.stats["vetoes"] = self.stats.get("vetoes", 0) + 1
            self.vetoes.append({"plan": plan.id, "reason": out[0].reason, "rule": out[0].rule})
            del self.vetoes[:-50]
        return out

    def check(self, action: Action, w: WorldView | None = None) -> list[dict[str, str]]:
        """Guard tester used by the UI/API: returns violations for one candidate action."""
        res = self.policy.check_action(action)
        if w is not None:
            asset = action.target or action.params.get("asset")
            if asset and asset in w._p.assets:
                occ, _ = w.zone_state(w.spec(asset).zone)
                if occ > 0:
                    res.append(
                        {"rule": "zone_occupied", "severity": "deny", "detail": f"personnel in {w.spec(asset).zone}"}
                    )
        return res

    def summary(self, w: WorldView) -> dict[str, Any]:
        zones = []
        for z in sorted({w.spec(a).zone for a in w.ids()}):
            occ, wait = w.zone_state(z)
            zones.append(
                {
                    "zone": z,
                    "members": w.zone_members(z),
                    "occupied": occ > 0,
                    "occupied_min": occ,
                    "restart_wait_min": wait,
                    "locked_out": any(w.asset(m).safe_stop for m in w.zone_members(z)),
                }
            )
        return {
            "zones": zones,
            "intrusions": self.intrusions[-20:],
            "vetoes": self.vetoes[-20:],
            "cyber": self.cyber,
            "rules": {
                "forbidden": self.policy.rules.forbidden,
                "protected_assets": self.policy.rules.protected_assets,
                "exempt_from_kill_switch": self.policy.rules.exempt_from_kill_switch,
            },
        }
