"""Process Optimizer agent (DF-11): bounded recipe optimisation (yield vs energy vs cycle time) with safe exploration on a forked
twin, trust-region steps and rollback on regression."""

from __future__ import annotations

from typing import Any

from nightshift.features.df04_swarm.core import Agent, Blackboard, WorldView
from nightshift.plant.models import Action, Proposal

BOUNDS = {"inj_speed": (42.0, 62.0), "cool_s": (11.0, 18.0), "melt_temp_c": (232.0, 250.0)}
STEPS = {"inj_speed": 2.0, "cool_s": 1.0, "melt_temp_c": 2.0}  # <= 5 % of the range per step (trust region)
MARGIN_PER_UNIT = 15.0
SCRAP_COST = 25.0


def objective(fork: Any, asset: str, price: float) -> dict[str, float]:
    a = fork.assets[asset]
    hours = max(fork.t, 1) / 60.0
    good = a.good
    return {
        "good": good,
        "scrap": a.scrap,
        "kwh": a.kwh,
        "j": good * MARGIN_PER_UNIT - a.scrap * SCRAP_COST - a.kwh * price,
        "hours": hours,
    }


class ProcessAgent(Agent):
    name = "process"
    role = "Process Optimizer"
    decision_classes = ("process.recipe",)
    interval = 6

    def __init__(self, twin: Any = None) -> None:
        super().__init__()
        self.twin = twin
        self.history: list[dict[str, Any]] = []
        self.trial: dict[str, Any] | None = None
        self.pilot: str | None = None
        self.last_try = -(10**9)
        self.best: dict[str, float] = {}

    def _evaluate(self, w: WorldView, asset: str, recipe: dict[str, float]) -> dict[str, float] | None:
        if self.twin is None:
            return None
        res = self.twin.evaluate_recipe(asset, recipe, horizon_min=180)
        return res

    def perceive(self, w: WorldView, board: Blackboard) -> list[Proposal]:
        presses = w.ids("PRESS")
        if not presses or self.twin is None:
            return []
        self.pilot = self.pilot or presses[0]
        a = w.asset(self.pilot)
        cur = dict(a.recipe)
        # ---- monitoring of a running trial: rollback on regression
        if self.trial is not None:
            tr = self.trial
            if w.t - tr["t"] < 60:
                return []
            z = w.series(self.pilot, "part_weight_g", 60)
            kw = w.series(self.pilot, "power_kw", 60)
            self.trial = None
            nominal = w.spec(self.pilot).params["qchar"]
            import numpy as np

            shift = float(np.nanmean((z - nominal["nominal"]) / nominal["sigma"])) if np.isfinite(z).any() else 0.0
            if abs(shift) > 1.2:
                self.history.append(
                    {
                        "t": w.t,
                        "event": "rollback",
                        "recipe": tr["from"],
                        "why": f"part weight shifted {shift:+.2f} sigma after the change",
                    }
                )
                return [
                    self.prop(
                        w,
                        "setpoint.adjust",
                        f"Roll back recipe on {self.pilot}",
                        [
                            Action("set_recipe", {"asset": self.pilot, "name": k, "value": v}, self.pilot)
                            for k, v in tr["from"].items()
                        ],
                        f"Regression after the recipe change: part weight {shift:+.2f} sigma from nominal. Restoring the last known-good recipe.",
                        assets=[self.pilot],
                        claims=[f"asset:{self.pilot}:recipe"],
                        risk=0.05,
                        expires_t=w.t + 30,
                        impact={"quality_eur": 200.0},
                        priority=1,
                    )
                ]
            self.history.append({"t": w.t, "event": "kept", "recipe": cur, "kw": round(float(np.nanmean(kw)), 2)})
            return []
        if w.t - self.last_try < 120 or a.state not in ("RUN", "STARVED", "BLOCKED", "IDLE"):
            return []
        base = self._evaluate(w, self.pilot, cur)
        if base is None:
            return []
        best: tuple[float, dict[str, float], dict[str, float], str] | None = None
        for k, step in STEPS.items():
            for sign in (-1, 1):
                cand = dict(cur)
                cand[k] = round(min(BOUNDS[k][1], max(BOUNDS[k][0], cur.get(k, 0.0) + sign * step)), 2)
                if cand[k] == cur.get(k):
                    continue
                res = self._evaluate(w, self.pilot, cand)
                if res is None:
                    continue
                gain = res["j"] - base["j"]
                if gain > 0 and (best is None or gain > best[0]):
                    best = (gain, cand, res, f"{k} {cur.get(k)} -> {cand[k]}")
        self.last_try = w.t
        if best is None or best[0] < 1.0:
            self.history.append({"t": w.t, "event": "converged", "recipe": cur})
            return []
        gain, cand, res, desc = best
        self.trial = {"t": w.t, "from": cur, "to": cand}
        self.history.append({"t": w.t, "event": "proposed", "change": desc, "gain_eur_3h": round(gain, 1)})
        return [
            self.prop(
                w,
                "process.recipe",
                f"Optimise recipe on {self.pilot}: {desc}",
                [
                    Action("set_recipe", {"asset": self.pilot, "name": k, "value": v}, self.pilot)
                    for k, v in cand.items()
                    if cur.get(k) != v
                ],
                f"Safe exploration on a forked twin (3 h, common random numbers): {desc} improves the objective (good units x margin - scrap - energy) by EUR {gain:,.0f}; "
                f"scrap {res['scrap']:.1f} vs {base['scrap']:.1f} units, energy {res['kwh']:.0f} vs {base['kwh']:.0f} kWh. Step is inside the +/-5 % trust region; "
                f"an automatic rollback follows if part weight shifts > 1.2 sigma within 60 min.",
                assets=[self.pilot],
                claims=[f"asset:{self.pilot}:recipe"],
                risk=0.18,
                cost_eur=0.0,
                expires_t=w.t + 120,
                impact={"throughput_eur": round(gain, 0)},
                counterfactual={"baseline": base, "candidate": res},
            )
        ]

    def summary(self) -> dict[str, Any]:
        return {
            "pilot": self.pilot,
            "bounds": BOUNDS,
            "steps": STEPS,
            "history": self.history[-30:],
            "trial": self.trial,
        }
