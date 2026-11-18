"""Fleet (DF-22): owns every simulated plant of the process, fleet KPIs, benchmarking and cross-plant playbook sharing."""

from __future__ import annotations

import statistics
from typing import TYPE_CHECKING, Any

import numpy as np

from nightshift.features.df05_maintenance.anomaly import Signature, SignatureLibrary
from nightshift.plant.runtime import PlantRuntime

if TYPE_CHECKING:  # pragma: no cover
    from nightshift.core.runtime import Runtime


class Fleet:
    def __init__(self, rt: Runtime) -> None:
        self.rt = rt
        self.plants: dict[str, PlantRuntime] = {}
        self.playbooks: list[dict[str, Any]] = []
        self._pb_seq = 0
        self.primary_id = rt.settings.primary_plant

    async def start(self) -> None:
        s = self.rt.settings
        for i, pid in enumerate(s.plants):
            pr = PlantRuntime(self.rt, pid, seed=s.seed + 101 * i, speed=s.sim_speed, library=SignatureLibrary())
            self.plants[pid] = pr
            await pr.start(autostart=s.sim_autostart)

    async def stop(self) -> None:
        for p in self.plants.values():
            await p.stop()

    def on_tick(self, plant: PlantRuntime) -> None:
        return None

    @property
    def primary(self) -> PlantRuntime:
        return self.plants.get(self.primary_id) or next(iter(self.plants.values()))

    def get(self, plant_id: str | None) -> PlantRuntime:
        if not plant_id:
            return self.primary
        if plant_id not in self.plants:
            raise KeyError(plant_id)
        return self.plants[plant_id]

    def summary(self) -> list[dict[str, Any]]:
        return [
            {
                "id": p.plant_id,
                "name": p.cfg.name,
                "location": p.cfg.location,
                "profile": p.cfg.profile,
                "assets": len(p.cfg.assets),
            }
            for p in self.plants.values()
        ]

    # ------------------------------------------------------------------ benchmarking
    def compare(self) -> dict[str, Any]:
        rows = [p.summary() for p in self.plants.values()]
        keys = ("oee", "otif", "throughput_uph", "kwh_per_unit", "co2_per_unit_kg", "scrap_pct", "downtime_min")
        lower_better = {"kwh_per_unit", "co2_per_unit_kg", "scrap_pct", "downtime_min"}
        med: dict[str, float | None] = {}
        for k in keys:
            vals = [r[k] for r in rows if r.get(k) is not None]
            med[k] = statistics.median(vals) if vals else None
        for r in rows:
            r["rank"] = {}
            for k in keys:
                vals = sorted([x[k] for x in rows if x.get(k) is not None], reverse=k not in lower_better)
                r["rank"][k] = vals.index(r[k]) + 1 if r.get(k) is not None and r[k] in vals else None
        notes = []
        for k in ("oee", "kwh_per_unit", "downtime_min"):
            vals = [(r["id"], r[k]) for r in rows if r.get(k) is not None]
            if len(vals) >= 2 and med[k]:
                best = (min if k in lower_better else max)(vals, key=lambda v: v[1])
                gap = (best[1] - med[k]) / abs(med[k])
                notes.append(
                    f"{best[0]} leads on {k.replace('_', ' ')} ({gap:+.0%} vs fleet median) - candidate for playbook sharing."
                )
        return {"plants": rows, "median": med, "notes": notes}

    def fleet_totals(self) -> dict[str, Any]:
        rows = [p.summary() for p in self.plants.values()]
        return {
            "plants": len(rows),
            "assets": sum(r["assets"] for r in rows),
            "pending_approvals": sum(r["pending_approvals"] for r in rows),
            "mean_oee": float(np.mean([r["oee"] for r in rows if r.get("oee") is not None] or [0.0])),
        }

    # ------------------------------------------------------------------ playbook sharing
    def learn_signature(self, plant_id: str, asset: str, note: str = "") -> dict[str, Any]:
        """Turn the current anomaly residual of an asset into a reusable failure signature (shared with the fleet)."""
        p = self.get(plant_id)
        m = p.pdm.models.get(asset)
        if m is None or not m.ready:
            raise ValueError(f"{asset} has no learned baseline yet")
        vec = np.array(m.ewma, dtype=float)
        norm = float(np.linalg.norm(vec))
        if norm < 1.0:
            raise ValueError(f"{asset} shows no anomaly to learn from (residual norm {norm:.2f} < 1)")
        base = max(
            p.library.items, key=lambda s: float(np.dot(vec / norm, np.array(s.vector) / np.linalg.norm(s.vector)))
        )
        self._pb_seq += 1
        sig = Signature(
            name=f"{base.name}-variant-{self._pb_seq}",
            vector=tuple(float(x) for x in (vec / norm)),  # type: ignore[arg-type]
            description=note or f"Learned at {plant_id} on {asset} (residual direction of a {base.name} incident).",
            source=f"learned:{plant_id}",
            model=dict(base.model),
            actionable=base.actionable,
        )
        pb = {
            "id": f"PB-{self._pb_seq:03d}",
            "from_plant": plant_id,
            "asset": asset,
            "signature": sig.public(),
            "t": p.plant.t,
            "adopted_by": [],
        }
        self.playbooks.append(pb)
        p.library.add(sig)
        p.ledger.append(
            "system",
            f"Playbook {pb['id']} learned from {asset}: {sig.name}",
            agent="fleet",
            assets=[asset],
            outcome="playbook_learned",
            payload={"signature": sig.public()},
            sim_t=p.plant.t,
        )
        return pb

    def adopt(self, playbook_id: str, plant_id: str) -> dict[str, Any]:
        pb = next((x for x in self.playbooks if x["id"] == playbook_id), None)
        if pb is None:
            raise KeyError(playbook_id)
        target = self.get(plant_id)
        sd = pb["signature"]
        sig = Signature(
            sd["name"], tuple(sd["vector"]), sd["description"], sd["source"], dict(sd["model"]), bool(sd["actionable"])
        )  # type: ignore[arg-type]
        added = target.library.add(sig)
        if added and plant_id not in pb["adopted_by"]:
            pb["adopted_by"].append(plant_id)
            target.ledger.append(
                "system",
                f"Playbook {pb['id']} adopted from {pb['from_plant']}: {sig.name}",
                agent="fleet",
                outcome="playbook_adopted",
                payload={"signature": sd},
                sim_t=target.plant.t,
            )
        return {**pb, "added": added}
