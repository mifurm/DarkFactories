"""Quality Guardian agent (DF-06): SPC (X-bar/R, Cpk, Western Electric), drift detection, bounded setpoint compensation,
lot containment and tool-change booking; vision inspection lives in vision.py."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from nightshift.features.df04_swarm.core import Agent, Blackboard, WorldView
from nightshift.features.df06_quality import spc
from nightshift.features.df06_quality.vision import ReviewItem
from nightshift.plant.models import Action, Proposal
from nightshift.sim.plant import p_defect

N = 5
COMP_TRIGGER = 0.8
COMP_MAX = 2.0


@dataclass
class QState:
    buf: list[float] = field(default_factory=list)
    zs: list[float] = field(default_factory=list)
    rs: list[float] = field(default_factory=list)
    ts: list[int] = field(default_factory=list)
    violations: list[dict[str, Any]] = field(default_factory=list)
    good_streak: int = 0
    last_offset: float = 0.0
    cpk: float | None = None


class QualityAgent(Agent):
    name = "quality"
    role = "Quality Guardian"
    decision_classes = ("setpoint.adjust", "quality.containment", "maintenance.schedule")

    def __init__(self) -> None:
        super().__init__()
        self.state: dict[str, QState] = {}
        self.review_queue: list[ReviewItem] = []
        self.vision_log: list[dict[str, Any]] = []
        self.interventions: list[dict[str, Any]] = []
        self.offset_hist: dict[str, list[tuple[int, float]]] = {}

    # ------------------------------------------------------------------ SPC update
    def _update(self, w: WorldView, aid: str, spec: Any, st: QState) -> None:
        q = spec.params["qchar"]
        s = w.series(aid, q["metric"], N)
        s = s[~np.isnan(s)]
        st.buf.extend(float(x) for x in s)
        while len(st.buf) >= N:
            grp = np.array(st.buf[:N])
            del st.buf[:N]
            st.zs.append(float((grp.mean() - q["nominal"]) / q["sigma"]))
            st.rs.append(float((grp.max() - grp.min()) / q["sigma"]))
            st.ts.append(w.t)
        del st.zs[:-60], st.rs[:-60], st.ts[:-60]
        if len(st.zs) >= 4:
            z = np.array(st.zs[-25:])
            st.violations = spc.western_electric(z, 0.0, 1.0 / math.sqrt(N))
            mean = float(np.mean(st.zs[-10:]))
            sig = float(np.mean(st.rs[-10:]) / spc.D2[N])
            st.cpk = spc.cpk(mean, max(sig, 1e-6), -5.0, 5.0)

    def perceive(self, w: WorldView, board: Blackboard) -> list[Proposal]:
        props: list[Proposal] = []
        booked = {wo.asset for wo in w.work_orders}
        for aid in w.ids("CNC", "PRESS", "ASM"):
            spec = w.spec(aid)
            if "qchar" not in spec.params:
                continue
            st = self.state.setdefault(aid, QState())
            a = w.asset(aid)
            if abs(a.offset - st.last_offset) > 1e-9 and a.offset == 0.0:  # tool change / repair reset the process
                st.zs, st.rs, st.buf = [], [], []
            st.last_offset = a.offset
            self._update(w, aid, spec, st)
            if len(st.zs) < 4 or a.state not in ("RUN", "STARVED", "BLOCKED"):
                continue
            dev = float(np.mean(st.zs[-3:]))  # effective (post-compensation) shift estimate in sigma
            last3 = np.array(st.zs[-3:])
            persistent = bool((np.sign(last3) == np.sign(dev)).all() and (np.abs(last3) > 0.45).all())
            ooc = bool(st.violations)
            suspect = board.get(f"pdm.suspect.{aid}")
            hint = f" Temperature signature suggests {suspect['signature'].replace('_', ' ')}." if suspect else ""
            st.good_streak = st.good_streak + 1 if abs(dev) < 0.7 else 0
            # ---- 1. bounded compensation
            if abs(dev) >= COMP_TRIGGER and persistent and abs(a.offset + dev) <= COMP_MAX:
                new = float(np.clip(round(a.offset + dev, 2), -COMP_MAX, COMP_MAX))
                saved = self._scrap_value(w, aid, spec, dev, 0.2)
                props.append(
                    self.prop(
                        w,
                        "setpoint.adjust",
                        f"Compensate process shift on {aid} ({a.offset:+.2f} -> {new:+.2f} sigma)",
                        [Action("set_setpoint", {"asset": aid, "name": "offset_comp", "value": new}, aid)],
                        f"{aid}: last 3 subgroup means sit {dev:+.2f} sigma from nominal"
                        + (f" (Western Electric: {st.violations[0]['detail']})" if ooc else "")
                        + f"; Cpk {st.cpk:.2f}. A bounded offset ({new:+.2f} sigma, limit +/-{COMP_MAX}) re-centres the process.{hint}",
                        assets=[aid],
                        claims=[f"asset:{aid}:offset"],
                        risk=0.12,
                        cost_eur=0.0,
                        expires_t=w.t + 30,
                        priority=1,
                        evidence=[
                            {
                                "type": "spc",
                                "ref": f"{aid}/{spec.params['qchar']['metric']}",
                                "shift_sigma": round(dev, 2),
                                "cpk": round(st.cpk or 0, 2),
                            }
                        ],
                        impact={"quality_eur": round(saved, 0)},
                        counterfactual={
                            "scrap_rate_without": round(p_defect(dev), 4),
                            "scrap_rate_with": round(p_defect(0.2), 4),
                        },
                    )
                )
                self.interventions.append(
                    {"t": w.t, "asset": aid, "kind": "compensation", "dev": round(dev, 2), "offset": new}
                )
            # ---- 2. containment (100 % inline inspection) while out of control and compensation cannot cope
            elif (abs(dev) >= 1.6 or (ooc and abs(dev) >= 1.2)) and not a.inline_inspect:
                props.append(
                    self.prop(
                        w,
                        "quality.containment",
                        f"Contain suspect output of {aid} (100 % inline inspection)",
                        [Action("set_inline_inspect", {"asset": aid, "on": True}, aid)],
                        f"{aid} is {dev:+.2f} sigma off-centre with {'rule ' + str(st.violations[0]['rule']) + ' firing' if ooc else 'no more compensation range'}; "
                        f"switching to 100 % inline inspection stops defective units from travelling downstream and escaping to customers.",
                        assets=[aid],
                        claims=[f"asset:{aid}:containment"],
                        risk=0.08,
                        cost_eur=20.0,
                        expires_t=w.t + 30,
                        priority=1,
                        impact={"quality_eur": round(self._escape_value(w, aid, spec, dev), 0)},
                        counterfactual={
                            "escape_risk_per_hour": round(self._units_per_h(w, aid, spec) * p_defect(dev) * 0.05, 2)
                        },
                    )
                )
                self.interventions.append({"t": w.t, "asset": aid, "kind": "containment_on", "dev": round(dev, 2)})
            elif a.inline_inspect and st.good_streak >= 4:
                props.append(
                    self.prop(
                        w,
                        "quality.containment",
                        f"Release containment on {aid}: process back in control",
                        [Action("set_inline_inspect", {"asset": aid, "on": False}, aid)],
                        f"{aid} has been within 0.7 sigma of nominal for {st.good_streak} consecutive subgroups.",
                        assets=[aid],
                        claims=[f"asset:{aid}:containment"],
                        risk=0.05,
                        expires_t=w.t + 30,
                        impact={"throughput_eur": 40.0},
                    )
                )
            # ---- 3. tool change as soon as compensation is about to run out (rate-based) or the process cannot be held in control
            hist = self.offset_hist.setdefault(aid, [])
            hist.append((w.t, abs(a.offset)))
            del hist[:-12]
            old = next((o for t0, o in hist if w.t - t0 <= 40), hist[0][1])
            rate = max(0.0, (abs(a.offset) - old) / max(1.0, min(40.0, w.t - hist[0][0] or 1.0)))
            exhaust_min = (COMP_MAX - abs(a.offset)) / rate if rate > 1e-4 else 10**6
            if (
                ((abs(a.offset) >= 0.9 and exhaust_min < 90) or abs(dev) >= 1.5 or abs(a.offset) >= 1.7)
                and aid not in booked
                and spec.type in ("CNC", "PRESS")
            ):
                dur = int(spec.params["tool_change_min"])
                windows = w.windows(240)
                if windows and windows[0][0] - w.t <= 45:
                    start, when = windows[0][0], "the next planned window"
                else:
                    start, when = w.t + 12, "a controlled stop"
                props.append(
                    self.prop(
                        w,
                        "maintenance.schedule",
                        f"Change tool on {aid} in {when}",
                        [
                            Action(
                                "schedule_maintenance",
                                {
                                    "asset": aid,
                                    "start_t": int(start),
                                    "duration": dur,
                                    "reason": "SPC: tool wear, compensation running out",
                                    "tool": True,
                                },
                                aid,
                            )
                        ],
                        f"{aid}: compensation is at {a.offset:+.2f} of +/-{COMP_MAX} sigma and rising ~{rate * 60:.2f} sigma/h (exhausted in ~{min(exhaust_min, 999):.0f} min); "
                        f"residual shift {dev:+.2f} sigma. A fresh tool restores the full capability margin before defects appear.",
                        assets=[aid],
                        claims=[f"asset:{aid}:maintenance"],
                        risk=0.1,
                        cost_eur=60.0,
                        correlation=f"TC-{aid}-{w.t}",
                        expires_t=w.t + 60,
                        priority=1,
                        impact={"quality_eur": round(self._scrap_value(w, aid, spec, 4.5, 0.2, hours=3.0), 0)},
                        expect={"asset": aid, "kind": "tool_change"},
                    )
                )
        return props

    # ------------------------------------------------------------------ value models
    @staticmethod
    def _units_per_h(w: WorldView, aid: str, spec: Any) -> float:
        return 60.0 / 3.0 if spec.type == "CNC" else 60.0 / 1.9 if spec.type == "PRESS" else 60.0 / 1.2

    def _scrap_value(self, w: WorldView, aid: str, spec: Any, dev: float, after: float, hours: float = 4.0) -> float:
        per_unit = 38.0
        return max(0.0, p_defect(dev) - p_defect(after)) * self._units_per_h(w, aid, spec) * hours * per_unit

    def _escape_value(self, w: WorldView, aid: str, spec: Any, dev: float, hours: float = 4.0) -> float:
        return p_defect(dev) * self._units_per_h(w, aid, spec) * hours * 0.05 * w.A["costs"]["escape_eur_per_unit"]

    # ------------------------------------------------------------------ views
    def chart(self, w: WorldView, aid: str) -> dict[str, Any]:
        spec = w.spec(aid)
        q = spec.params.get("qchar")
        st = self.state.get(aid)
        if q is None or st is None:
            return {"asset": aid, "available": False}
        a = w.asset(aid)
        lim = spc.control_plan_limits(0.0, 1.0, N)
        return {
            "asset": aid,
            "available": True,
            "metric": q["metric"],
            "nominal": q["nominal"],
            "sigma": q["sigma"],
            "n": N,
            "limits": {k: round(v, 3) for k, v in lim.items()},
            "points": [
                {"t": t, "z": round(z, 3), "r": round(r, 3)} for t, z, r in zip(st.ts, st.zs, st.rs, strict=False)
            ],
            "violations": st.violations,
            "cpk": None if st.cpk is None else round(st.cpk, 2),
            "offset": a.offset,
            "contained": a.inline_inspect,
            "state": a.state,
        }

    def summary(self, w: WorldView) -> list[dict[str, Any]]:
        out = []
        for aid in w.ids("CNC", "PRESS", "ASM"):
            st = self.state.get(aid)
            if st is None or "qchar" not in w.spec(aid).params:
                continue
            a = w.asset(aid)
            out.append(
                {
                    "asset": aid,
                    "cpk": None if st.cpk is None else round(st.cpk, 2),
                    "shift_sigma": round(float(np.mean(st.zs[-3:])), 2) if len(st.zs) >= 3 else None,
                    "offset": a.offset,
                    "contained": a.inline_inspect,
                    "violations": [v["rule"] for v in st.violations],
                    "subgroups": len(st.zs),
                    "status": "out of control" if st.violations else "in control",
                }
            )
        return out
