"""Predictive Maintenance agent (DF-05): robust-z + EWMA + isolation forest, health index, RUL with a confidence band,
failure-signature library and automatic work orders booked into planned windows."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from nightshift.features.df04_swarm.core import Agent, Blackboard, WorldView
from nightshift.features.df05_maintenance.anomaly import (
    IsolationForest,
    Signature,
    SignatureLibrary,
    match_signatures,
    robust_stats,
    theil_sen,
)
from nightshift.plant.models import Action, Proposal

CHANNELS: dict[str, dict[str, str | None]] = {
    "CNC": {"vib": "vibration_rms", "temp": "bearing_temp_c", "load": "spindle_load_pct", "press": None},
    "PRESS": {"vib": "vibration_rms", "temp": "melt_temp_c", "load": "current_a", "press": "hydraulic_pressure_bar"},
    "ASM": {"vib": "vibration_rms", "temp": None, "load": "current_a", "press": None},
    "COMP": {"vib": "vibration_rms", "temp": "temperature_c", "load": "current_a", "press": "pressure_bar"},
    "CHILL": {"vib": "vibration_rms", "temp": None, "load": "current_a", "press": None},
}
TEMP_PRIOR = {"CNC": (20.0, 1.5), "COMP": (22.0, 1.5), "PRESS": (8.0, 1.5)}  # (gain, exponent) of temperature vs damage
BASELINE_CYCLES = 18
LAMBDA = 0.35


@dataclass
class AssetModel:
    base: list[tuple[float, float, float, float]] = field(default_factory=list)
    ready: bool = False
    mu: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    sd: tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0)
    iso: IsolationForest | None = None
    ewma: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0, 0.0])
    streak: int = 0
    alert_since: int | None = None
    hist: list[tuple[int, float]] = field(default_factory=list)
    last_maint_t: int = 0
    proposed_t: int = -(10**9)
    view: dict[str, Any] = field(default_factory=dict)


class PdMAgent(Agent):
    name = "maintenance"
    role = "Predictive Maintenance"
    decision_classes = ("maintenance.schedule", "maintenance.remote_clear")

    def __init__(self, library: SignatureLibrary | None = None) -> None:
        super().__init__()
        self.library = library or SignatureLibrary()
        self.models: dict[str, AssetModel] = {}
        self.jams: dict[str, int] = {}
        self.alert_log: list[dict[str, Any]] = []

    # ------------------------------------------------------------------ feature extraction
    def _features(self, w: WorldView, aid: str, ch: dict[str, str | None]) -> tuple[float, float, float, float] | None:
        spec = w.spec(aid)
        idle_kw = spec.params["power_kw"]["IDLE"]
        pw = w.series(aid, "power_kw", 5)
        run = pw > idle_kw * 1.5
        if run.sum() < 3:
            return None

        def mean(metric: str | None) -> float:
            if metric is None or not w.has_metric(aid, metric):
                return float("nan")
            s = w.series(aid, metric, 5)
            s = s[run[-len(s) :]] if len(s) == len(run) else s
            s = s[~np.isnan(s)]
            return float(s.mean()) if s.size else float("nan")

        return mean(ch["vib"]), mean(ch["temp"]), mean(ch["load"]), mean(ch["press"])

    def _learn(self, m: AssetModel, f: tuple[float, float, float, float]) -> None:
        m.base.append(f)
        if len(m.base) >= BASELINE_CYCLES:
            arr = np.array(m.base, dtype=float)
            mus, sds = [], []
            for k in range(4):
                col = arr[:, k]
                if np.isnan(col).all():
                    mus.append(0.0)
                    sds.append(1.0)
                    continue
                mu, sd = robust_stats(col)
                mus.append(mu)
                sds.append(max(sd, (0.03, 0.15, 0.5, 0.2)[k]))
            m.mu, m.sd = tuple(mus), tuple(sds)  # type: ignore[assignment]
            cols = [k for k in range(3) if not np.isnan(arr[:, k]).any()]
            m.iso = IsolationForest(n_trees=30, sample=min(32, len(arr)), seed=7).fit(arr[:, cols]) if cols else None
            m.view["iso_cols"] = cols
            m.ready = True

    # ------------------------------------------------------------------ main loop
    def perceive(self, w: WorldView, board: Blackboard) -> list[Proposal]:
        props: list[Proposal] = []
        estimates: dict[str, dict[str, float]] = {}
        booked = {wo.asset for wo in w.work_orders}
        for aid in w.ids(*CHANNELS):
            spec = w.spec(aid)
            ch = CHANNELS[spec.type]
            a = w.asset(aid)
            m = self.models.setdefault(aid, AssetModel(last_maint_t=a.last_maint_t))
            if a.last_maint_t != m.last_maint_t:  # serviced: relearn the healthy baseline
                self.models[aid] = m = AssetModel(last_maint_t=a.last_maint_t)
            if a.state == "DOWN":
                m.alert_since = None
                continue
            f = self._features(w, aid, ch)
            if f is None:
                continue
            if not m.ready:
                self._learn(m, f)
                m.view = {**m.view, "asset": aid, "status": "learning baseline", "baseline_cycles": len(m.base)}
                continue
            z = [0.0 if math.isnan(f[k]) else (f[k] - m.mu[k]) / m.sd[k] for k in range(4)]
            for k in range(4):
                m.ewma[k] = LAMBDA * z[k] + (1 - LAMBDA) * m.ewma[k]
            top = max(m.ewma[0], m.ewma[1] if not math.isnan(f[1]) else 0.0)
            iso = 0.0
            if m.iso is not None and top > 1.5:
                cols = m.view.get("iso_cols", [0, 1, 2])
                iso = float(m.iso.score(np.array([[f[k] for k in cols]]))[0])
            anomalous = top > 3.2 or (top > 2.2 and iso > 0.68)
            m.streak = m.streak + 1 if anomalous else 0
            if m.streak >= 2 and m.alert_since is None:
                m.alert_since = w.t
                m.hist = []
            if m.streak == 0 and m.alert_since is not None and top < 1.5:
                m.alert_since = None
            view = {
                "asset": aid,
                "status": "ok",
                "z": [round(x, 2) for x in m.ewma],
                "score": round(top, 2),
                "iso": round(iso, 3),
                "vib": round(f[0], 3),
                "temp": None if math.isnan(f[1]) else round(f[1], 2),
                "baseline": {"vib": round(m.mu[0], 3), "temp": round(m.mu[1], 2)},
                "health_est": None,
                "rul_min": None,
                "signature": None,
                "alert": False,
            }
            if m.alert_since is not None:
                est = self._estimate(w, aid, spec.type, f, m)
                view.update(est["view"])
                view["alert"] = True
                view["status"] = "alert"
                if est["rul"] is not None:
                    estimates[aid] = {"health": est["h"], "rate": est["rate"]}
                p = self._maybe_propose(w, board, aid, spec, a, m, f, est, booked)
                if p is not None:
                    props.append(p)
            m.view = {**m.view, **view}
        board.post("pdm.estimates", estimates)
        props += self._jam_proposals(w)
        return props

    # ------------------------------------------------------------------ prognostics
    def _estimate(
        self, w: WorldView, aid: str, atype: str, f: tuple[float, float, float, float], m: AssetModel
    ) -> dict[str, Any]:
        sig = next(s for s in self.library.items if s.name == "bearing_wear")
        k_v = sig.model.get("vib_k", 6.0)
        d0 = sig.model.get("d0", 0.11)
        d_v = math.sqrt(max(0.0, (f[0] - m.mu[0]) / k_v + d0 * d0))
        ests = [(d_v, 1.0)]
        prior = TEMP_PRIOR.get(atype)
        if prior and not math.isnan(f[1]):
            gain, ex = prior
            d_t = max(0.0, (f[1] - m.mu[1]) / gain + d0**ex) ** (1.0 / ex)
            ests.append((d_t, 1.0))
        d = min(0.99, sum(x * wgt for x, wgt in ests) / sum(wgt for _, wgt in ests))
        h = 1.0 - d
        m.hist.append((w.t, h))
        del m.hist[:-48]
        vec = (m.ewma[0], m.ewma[1], m.ewma[2], m.ewma[3])
        ranked = match_signatures(vec, self.library.items)
        best, sim = ranked[0]
        out: dict[str, Any] = {
            "view": {
                "health_est": round(h, 3),
                "signature": {"name": best.name, "similarity": round(sim, 2), "actionable": best.actionable},
                "signatures": [{"name": s.name, "similarity": round(x, 2)} for s, x in ranked[:3]],
            },
            "rul": None,
            "h": h,
            "rate": 0.0,
            "signature": best,
            "sim": sim,
        }
        pts = m.hist[-24:]
        if len(pts) >= 6:
            t = np.array([p[0] for p in pts], dtype=float)
            y = np.array([p[1] for p in pts], dtype=float)
            slope, lo, hi = theil_sen(t, y)
            fail_th = w.spec(aid).params["fail_threshold"]
            if slope < -1e-6:
                p50 = max(0.0, (h - fail_th) / -slope)
                # steeper decline (lo, more negative) -> shorter life
                p10 = max(0.0, (h - fail_th) / -min(lo, -1e-6)) if lo < 0 else p50
                p90 = (h - fail_th) / -max(hi, -1e-6) if hi < 0 else 72 * 60.0
                p90 = min(p90, 72 * 60.0)
                spread = (p90 - p10) / max(p50, 1.0)
                conf = "high" if spread < 0.8 else "medium" if spread < 1.6 else "low"
                out.update(rul=p50, rate=-slope)
                out["view"].update(
                    {
                        "rul_min": round(p50),
                        "rul_p10_min": round(min(p10, p50)),
                        "rul_p90_min": round(max(p90, p50)),
                        "confidence": conf,
                        "predicted_failure_t": int(w.t + p50),
                    }
                )
                out["p10"], out["p90"], out["conf"] = min(p10, p50), max(p90, p50), conf
        return out

    # ------------------------------------------------------------------ proposals
    def _maybe_propose(
        self,
        w: WorldView,
        board: Blackboard,
        aid: str,
        spec: Any,
        a: Any,
        m: AssetModel,
        f: Any,
        est: dict[str, Any],
        booked: set[str],
    ) -> Proposal | None:
        sig: Signature = est["signature"]
        if est["rul"] is None or aid in booked or w.t - m.proposed_t < 60:
            return None
        if not sig.actionable or est["sim"] < 0.55:
            board.post(f"pdm.suspect.{aid}", {"signature": sig.name, "similarity": est["sim"], "t": w.t})
            return None
        rul50, p10, p90 = est["rul"], est["p10"], est["p90"]
        params = spec.params
        duration = int(params.get("pm_duration_min", 45))
        lead = 25
        windows = [(s, e) for s, e in w.windows(int(p90) + 600) if s - w.t >= lead and e - w.t <= p10 * 0.9]
        if windows:
            start, end = windows[0]
            where = f"the planned changeover window {self._clock(w, start)}-{self._clock(w, end)}"
            disruption = 0.15
        else:
            start, end = w.t + lead, w.t + lead + duration
            where = f"a controlled stop at {self._clock(w, start)} (no planned window fits before the earliest likely failure)"
            disruption = 0.5
        spare = "SP-BEARING" if spec.type in ("CNC", "PRESS") and "SP-BEARING" in w.spares else None
        spare_ok = spare is None or w.spares[spare]["on_hand"] >= 1
        loss = params["loss_eur_per_min"]
        mttr = params["mttr_min"]
        repair = w.A["costs"]["repair_eur"]
        avoided = mttr * loss + (repair["unplanned"] - repair["planned"])
        planned_loss = duration * loss * disruption
        cost = repair["planned"] + (w.spares[spare]["price_eur"] if spare else 0.0)
        corr = f"MX-{aid}-{w.t}"
        z = m.ewma
        rationale = (
            f"{aid}: vibration {f[0]:.2f} mm/s ({z[0]:.1f} sigma over its healthy baseline {m.mu[0]:.2f})"
            + (f", temperature {f[1]:.1f} C ({z[1]:.1f} sigma)" if not math.isnan(f[1]) else "")
            + f". Signature '{sig.name}' (cosine {est['sim']:.2f}). Estimated health {est['h']:.2f}; remaining useful life "
            f"{rul50 / 60:.1f} h (P10-P90 {p10 / 60:.1f}-{p90 / 60:.1f} h, confidence {est['conf']}). "
            f"Booked into {where}; the work finishes before the earliest likely failure."
            + ("" if spare_ok else f" WARNING: spare {spare} out of stock - work will wait for the delivery.")
        )
        m.proposed_t = w.t
        board.post(
            "pdm.pending",
            {
                **board.get("pdm.pending", {}),
                aid: {"start": start, "end": end, "duration": duration, "corr": corr, "rul_p10": p10},
            },
        )
        self.alert_log.append({"t": w.t, "asset": aid, "rul_min": round(rul50), "signature": sig.name})
        return self.prop(
            w,
            "maintenance.schedule",
            f"Schedule {sig.name.replace('_', ' ')} maintenance on {aid}",
            [
                Action(
                    "schedule_maintenance",
                    {
                        "asset": aid,
                        "start_t": int(start),
                        "duration": duration,
                        "reason": f"PdM: {sig.name}, RUL {rul50 / 60:.1f} h",
                        "spare": spare,
                    },
                    aid,
                )
            ],
            rationale,
            expires_t=int(w.t + max(120, min(p10, 480))),
            horizon_min=int(min(960, max(300, rul50 + 120))),  # the twin must see the failure this repair prevents
            correlation=corr,
            assets=[aid],
            claims=[f"asset:{aid}:maintenance"],
            risk=0.15 if spare_ok else 0.45,
            cost_eur=cost,
            priority=1,
            evidence=[
                {
                    "type": "sensor",
                    "ref": f"{aid}/vibration_rms",
                    "value": round(f[0], 3),
                    "baseline": round(m.mu[0], 3),
                    "z": round(z[0], 2),
                },
                {
                    "type": "estimate",
                    "ref": f"{aid}/RUL",
                    "p50_min": round(rul50),
                    "p10_min": round(p10),
                    "p90_min": round(p90),
                },
            ],
            impact={"maintenance_eur": round(avoided, 0), "throughput_eur": -round(planned_loss, 0)},
            counterfactual={
                "predicted_failure_t": int(w.t + rul50),
                "avoided_downtime_min": mttr,
                "avoided_loss_eur": round(mttr * loss, 0),
                "rul_p50_min": round(rul50),
            },
            expect={"asset": aid, "kind": "maintenance", "predicted_failure_t": int(w.t + rul50)},
        )

    def _jam_proposals(self, w: WorldView) -> list[Proposal]:
        out = []
        for aid, t0 in list(self.jams.items()):
            a = w.asset(aid)
            if a.state != "DOWN":
                self.jams.pop(aid, None)
                continue
            if a.repair_left <= 15:
                continue
            self.jams.pop(aid, None)
            out.append(
                self.prop(
                    w,
                    "maintenance.remote_clear",
                    f"Remote-clear jam on {aid}",
                    [Action("clear_jam", {"asset": aid}, aid)],
                    f"{aid} stopped with a jam alarm {w.t - t0} min ago; a remote clear-and-restart sequence usually recovers it in ~12 min versus a technician visit.",
                    assets=[aid],
                    claims=[f"asset:{aid}:jam"],
                    risk=0.1,
                    cost_eur=0.0,
                    expires_t=w.t + 60,
                    impact={"maintenance_eur": round(a.repair_left * w.spec(aid).params["loss_eur_per_min"] * 0.8, 0)},
                )
            )
        return out

    def on_event(self, ev: dict[str, Any], w: Any, board: Blackboard) -> None:
        if ev["kind"] == "failure" and ev.get("cause") == "jam":
            self.jams[ev["asset"]] = ev["t"]

    @staticmethod
    def _clock(w: WorldView, t: int) -> str:
        from datetime import timedelta

        return (w.now + timedelta(minutes=t - w.t)).strftime("%H:%M")

    # ------------------------------------------------------------------ views
    def snapshot(self, w: WorldView) -> list[dict[str, Any]]:
        rows = []
        for aid, m in self.models.items():
            row = {"asset": aid, "type": w.spec(aid).type, "ready": m.ready, **m.view}
            row["state"] = w.asset(aid).state
            wos = [wo for wo in w.work_orders if wo.asset == aid]
            row["work_orders"] = [
                {"id": x.id, "start_t": x.start_t, "duration": x.duration, "status": x.status, "reason": x.reason}
                for x in wos
            ]
            rows.append(row)
        return rows
