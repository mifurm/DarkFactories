"""Materials & Logistics agent (DF-08): inventory cover vs supplier ETA, expedite / alternate source, AMR kitting priority and
spare-part staging."""

from __future__ import annotations

from typing import Any

from nightshift.features.df04_swarm.core import Agent, Blackboard, WorldView
from nightshift.plant.models import Action, Proposal


class MaterialsAgent(Agent):
    name = "materials"
    role = "Materials & Logistics"
    decision_classes = ("materials.expedite", "materials.reorder", "amr.dispatch")

    def __init__(self) -> None:
        super().__init__()
        self.rate: dict[str, float] = {}  # consumption per minute over a 45-150 min window
        self.hist: dict[str, list[tuple[int, float, float]]] = {}
        self.recv: dict[str, float] = {}
        self.risks: dict[str, dict[str, Any]] = {}
        self.last_prio_t = -999

    def on_event(self, ev: dict[str, Any], w: Any, board: Blackboard) -> None:
        if ev["kind"] == "material_received":
            self.recv[ev["material"]] = self.recv.get(ev["material"], 0.0) + float(ev["qty"])

    def _consumption(self, w: WorldView) -> None:
        for k, m in w.inventory.items():
            h = self.hist.setdefault(k, [])
            h.append((w.t, m["on_hand"], self.recv.get(k, 0.0)))
            del h[:-30]
            t0, oh0, rc0 = h[0]
            if w.t - t0 >= 45:
                self.rate[k] = max(0.0, (oh0 - m["on_hand"] + (self.recv.get(k, 0.0) - rc0)) / (w.t - t0))

    def _committed(self, w: WorldView) -> dict[str, float]:
        """MRP view: material still required by the open order book (units left at the consuming operation x BOM)."""
        req: dict[str, float] = {}
        for o in w.open_orders():
            prod = w.cfg.products[o.sku]
            for op in o.ops:
                if op.finished_t is not None:
                    continue
                for mat, q in prod.bom.items():
                    if w.A["materials"][mat]["stage"] == op.stage:
                        req[mat] = req.get(mat, 0.0) + max(0.0, o.qty - op.done) * q
        return req

    def _burn_rate(self, w: WorldView, mat: str) -> float:
        """Effective consumption per minute when the consuming stage runs at ~60 % utilisation."""
        stage = w.A["materials"][mat]["stage"]
        per_machine = []
        for prod in w.cfg.products.values():
            if mat in prod.bom and stage in prod.cycle:
                per_machine.append(prod.bom[mat] / prod.cycle[stage])
        return 0.6 * len(w.pools.get(stage, ())) * (sum(per_machine) / len(per_machine) if per_machine else 0.0)

    def perceive(self, w: WorldView, board: Blackboard) -> list[Proposal]:
        self._consumption(w)
        props: list[Proposal] = []
        costs = w.A["costs"]
        committed = self._committed(w)
        for k, m in w.inventory.items():
            rate = self._burn_rate(w, k)
            if rate <= 1e-9:
                continue
            etas = sorted(o[0] for o in m["on_order"])
            first_eta = (etas[0] - w.t) if etas else max(0.0, (m["on_hand"] - m["min"]) / rate) + m["lead_h"] * 60
            demand = min(committed.get(k, 0.0), rate * max(first_eta, 0.0))
            shortfall = demand - m["on_hand"]
            cover = m["on_hand"] / rate  # minutes of production at the effective burn rate
            gap = first_eta - cover
            self.risks[k] = {
                "material": k,
                "cover_min": round(cover),
                "next_eta_min": round(first_eta),
                "gap_min": round(gap),
                "rate_per_h": round(rate * 60, 2),
                "committed": round(committed.get(k, 0.0), 1),
                "shortfall": round(max(0.0, shortfall), 1),
                "at_risk": shortfall > 0 and gap > 0,
            }
            if shortfall <= 0.04 * m["max"] or gap <= 30 or w.t % 5:
                continue
            qty = float(min(m["max"] - m["on_hand"], max(shortfall * 1.2, 0.3 * m["max"])))
            options = []
            for mode, factor, prem in (
                ("expedite", 0.35, costs["expedite_premium"]),
                ("alt_source", 0.6, costs["alt_source_premium"]),
            ):
                eta = max(120.0, m["lead_h"] * 60 * factor)
                options.append((mode, eta, qty * m["price_eur"] * prem, eta <= cover))
            ok = [o for o in options if o[3]]
            mode, eta, cost, covers = min(ok, key=lambda o: o[2]) if ok else min(options, key=lambda o: o[1])
            stage = m["stage"]
            n_mach = len(w.pools.get(stage, ()))
            loss_rate = sum(w.spec(a).params["loss_eur_per_min"] for a in w.pools.get(stage, ()))
            outage_min = max(0.0, min(first_eta, 12 * 60) - cover)
            avoided = outage_min * loss_rate * 0.6
            props.append(
                self.prop(
                    w,
                    "materials.expedite",
                    f"{mode.replace('_', ' ').title()} {k} ({qty:.0f} {m['unit']})",
                    [Action("expedite_material", {"material": k, "qty": qty, "mode": mode}, None)],
                    f"{k}: {m['on_hand']:.0f} {m['unit']} on hand = {cover / 60:.1f} h of cover, the open orders still need {committed.get(k, 0.0):.0f} {m['unit']}, "
                    f"but the next supplier delivery is ~{first_eta / 60:.1f} h away (shortfall ~{shortfall:.0f} {m['unit']}; {n_mach} {stage} machine(s) would starve "
                    f"~{gap / 60:.1f} h before it arrives). {mode.replace('_', ' ')} lands in ~{eta / 60:.1f} h for EUR {cost:,.0f} premium"
                    f"{'' if covers else ' (cannot fully close the gap - Planner will re-sequence)'}.",
                    assets=[],
                    claims=[f"material:{k}"],
                    risk=0.12,
                    cost_eur=cost,
                    expires_t=w.t + 90,
                    priority=1,
                    impact={"throughput_eur": round(avoided, 0)},
                    counterfactual={
                        "stockout_in_min": round(cover),
                        "starved_machines": n_mach,
                        "avoided_loss_eur": round(avoided, 0),
                    },
                )
            )
        props += self._amr_priority(w)
        return props

    def _amr_priority(self, w: WorldView) -> list[Proposal]:
        reqs = w.amr_requests()
        if len(reqs) < 2 or w.t - self.last_prio_t < 15:
            return []
        scores: dict[str, float] = {}
        for _, mid in reqs:
            a = w.asset(mid)
            crit = 2.0 if w.spec(mid).type in ("ASM", "TEST", "PACK") else 1.0
            urgency = 6.0 * max(0.0, (40.0 - a.kit) / 40.0)
            scores[mid] = round(crit + urgency, 2)
        self.last_prio_t = w.t
        return [
            self.prop(
                w,
                "amr.dispatch",
                f"Prioritise AMR kit deliveries ({len(scores)} cells waiting)",
                [Action("set_amr_priority", {"scores": scores}, None)],
                "Several cells are waiting for kits; deliveries are ordered by cell criticality (bottleneck stages first) and remaining kit minutes instead of request order.",
                assets=[],
                claims=["amr:priority"],
                risk=0.03,
                cost_eur=0.0,
                expires_t=w.t + 20,
                impact={"throughput_eur": 60.0 * len(scores)},
            )
        ]

    def respond(self, w: WorldView, board: Blackboard, proposals: list[Proposal]) -> list[Proposal]:
        out: list[Proposal] = []
        for p in proposals:
            if p.decision_class != "maintenance.schedule":
                continue
            act = p.actions[0].params
            aid = act["asset"]
            spare = act.get("spare")
            if not spare:
                continue
            out.append(
                self.prop(
                    w,
                    "amr.dispatch",
                    f"Stage spare {spare} at {aid}",
                    [Action("stage_spare", {"asset": aid, "spare": spare}, aid)],
                    f"Maintenance on {aid} starts {max(0, act['start_t'] - w.t)} min from now; an AMR pre-stages the {spare} at the cell so the technician window is not lost to a delivery.",
                    assets=[],
                    claims=[f"amr:stage:{aid}"],
                    correlation=p.correlation,
                    risk=0.03,
                    cost_eur=0.0,
                    expires_t=p.expires_t,
                    impact={"maintenance_eur": 150.0},
                )
            )
        return out

    def summary(self, w: WorldView) -> dict[str, Any]:
        inv = []
        for k, m in w.inventory.items():
            inv.append(
                {
                    "material": k,
                    "unit": m["unit"],
                    "on_hand": round(m["on_hand"], 1),
                    "min": m["min"],
                    "max": m["max"],
                    "lead_h": m["lead_h"],
                    "on_order": [
                        {"eta_min": round(o[0] - w.t), "qty": round(o[1]), "source": o[2]} for o in m["on_order"]
                    ],
                    "risk": self.risks.get(k),
                }
            )
        spares = [
            {"part": k, "on_hand": s["on_hand"], "min": s["min"], "lead_h": s["lead_h"], "price_eur": s["price_eur"]}
            for k, s in w.spares.items()
        ]
        amr = [{"id": a, **{k: getattr(w.asset(a), k) for k in ("state", "battery")}} for a in w.amr_ids()]
        cells = [{"id": a, "kit_min": round(w.asset(a).kit, 1)} for a in w.ids("CNC", "PRESS", "ASM", "TEST", "PACK")]
        return {"inventory": inv, "spares": spares, "amr": amr, "cells": cells, "amr_queue": len(w.amr_requests())}
