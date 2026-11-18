"""Unit tests for the Nightshift business-case model (stdlib unittest).

    cd business-case && python -m unittest -v test_model
"""
from __future__ import annotations

import ast
import json
import math
import os
import sys
import unittest

import model

HERE = os.path.dirname(os.path.abspath(__file__))


class RecordingDict(dict):
    """Dict that records which keys were read (used to prove every assumption is consumed by the model)."""

    reads: set = set()

    def __getitem__(self, key):
        RecordingDict.reads.add(key)
        return super().__getitem__(key)


class ModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.A = model.load_assumptions()
        cls.out = model.compute_all(cls.A)
        cls.base = cls.out["scenarios"]["base"]

    # ------------------------------------------------------------------ reproducibility & purity
    def test_outputs_json_is_current(self):
        with open(os.path.join(HERE, "outputs.json"), encoding="utf-8") as fh:
            saved = json.load(fh)
        self.assertEqual(json.loads(json.dumps(self.out)), saved, "outputs.json is stale: run `python model.py`")

    def test_deterministic(self):
        again = model.compute(self.A, "base")
        self.assertEqual(json.dumps(again, sort_keys=True), json.dumps(self.base, sort_keys=True))

    def test_pure_standard_library(self):
        with open(os.path.join(HERE, "model.py"), encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        mods = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                mods.update(n.name.split(".")[0] for n in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                mods.add(node.module.split(".")[0])
        self.assertTrue(mods <= set(sys.stdlib_module_names) | {"__future__"}, mods)

    def test_prices_match_snapshot(self):
        path = os.path.join(HERE, "prices", "prices-snapshot.json")
        with open(path, encoding="utf-8") as fh:
            snap = json.load(fh)
        self.assertEqual(snap["retrieved_on"], self.A["meta"]["price_basis"]["retrieved_on"])
        self.assertEqual(set(snap["items"]), set(self.A["prices"]))
        for pid, item in snap["items"].items():
            self.assertAlmostEqual(item["retailPrice"], self.A["prices"][pid]["price"], places=12, msg=pid)
            self.assertEqual(item["meterId"], self.A["prices"][pid]["meter_id"], pid)

    def test_every_assumption_and_price_is_used(self):
        RecordingDict.reads = set()
        real = model.resolve

        def spy(assumptions, scenario="base", overrides=None):
            A, P = real(assumptions, scenario, overrides)
            return RecordingDict(A), P

        model.resolve = spy
        try:
            model.compute(self.A, "base", with_sensitivity=False)
        finally:
            model.resolve = real
        unused = set(self.A["assumptions"]) - RecordingDict.reads
        self.assertEqual(unused, set(), f"assumptions never read by the model: {sorted(unused)}")
        used_prices = {ln["price_id"] for ln in self.base["acr"]["line_items"]} | {ln["price_id"] for ln in self.base["expansion"]["acr"]["line_items"]}
        unused_prices = set(self.A["prices"]) - used_prices
        self.assertEqual(unused_prices, {"iot_ops_essentials_node_hour"}, "only the (documented) Essentials SKU price may be unused")

    # ------------------------------------------------------------------ brief anchors
    def test_reference_customer_matches_brief(self):
        r = self.base["inputs"]["resolved"]
        self.assertEqual(r["plants_total"], 8)
        self.assertEqual(r["revenue_usd"], 2_000_000_000)
        self.assertEqual(r["plants_total"] * r["assets_per_plant"], 3200)
        self.assertEqual(self.base["plants"]["live_by_year_end"], [2, 5, 8])
        self.assertEqual(self.base["horizon_years"], 3)
        self.assertEqual(self.base["currency"], "USD")

    def test_interface_keys(self):
        for key in ("scenario", "currency", "horizon_years", "inputs", "benefits", "costs", "roi", "acr", "sensitivity"):
            self.assertIn(key, self.base)
        self.assertEqual(set(self.base["benefits"]) >= {"by_category", "total_by_year", "total"}, True)
        self.assertEqual(set(self.base["costs"]) >= {"azure_by_family", "other_by_category", "total_by_year", "total"}, True)
        self.assertEqual(set(self.base["roi"]) >= {"net_benefit_by_year", "cumulative", "npv", "discount_rate", "roi_pct", "payback_months", "irr_pct"}, True)
        self.assertEqual(set(self.base["acr"]) >= {"by_year", "by_family", "run_rate_year3", "tiers", "pull_through_ratio"}, True)
        self.assertEqual(list(self.out["scenarios"]), ["conservative", "base", "upside"])

    # ------------------------------------------------------------------ internal consistency
    def test_sums_are_consistent(self):
        for name, r in self.out["scenarios"].items():
            ben = r["benefits"]
            for y in range(3):
                self.assertAlmostEqual(sum(v[y] for v in ben["by_category"].values()), ben["total_by_year"][y], delta=0.01, msg=name)
            self.assertAlmostEqual(sum(ben["total_by_year"]), ben["total"], delta=0.05)
            cost = r["costs"]
            for y in range(3):
                parts = sum(v[y] for v in cost["azure_by_family"].values()) + sum(v[y] for v in cost["other_by_category"].values())
                self.assertAlmostEqual(parts, cost["total_by_year"][y], delta=0.05, msg=name)
                self.assertAlmostEqual(ben["total_by_year"][y] - cost["total_by_year"][y], r["roi"]["net_benefit_by_year"][y], delta=0.05)
            run = 0.0
            for y in range(3):
                run += r["roi"]["net_benefit_by_year"][y]
                self.assertAlmostEqual(run, r["roi"]["cumulative"][y], delta=0.05)
            self.assertAlmostEqual(r["acr"]["by_year"][2], sum(v[2] for v in r["acr"]["by_family"].values()), delta=0.05)
            self.assertEqual(r["acr"]["by_year"], r["costs"]["azure_total_by_year"])

    def test_npv_is_zero_at_irr_and_equals_net_at_zero_rate(self):
        A, P = model.resolve(self.A, "base")
        sim = model._simulate(A, P, 60)
        flows = [sum(sim["benefit"][c][m] for c, _ in model.BENEFIT_CATEGORIES) - sum(sim["azure"][f][m] for f, _ in model.AZURE_FAMILIES)
                 - sum(sim["other"][c][m] for c, _ in model.OTHER_COST_CATEGORIES) for m in range(36)]
        irr = self.base["roi"]["irr_pct"] / 100.0
        self.assertAlmostEqual(model._npv(flows, irr), 0.0, delta=50.0)
        self.assertAlmostEqual(model._npv(flows, A["discount_rate"]), self.base["roi"]["npv"], delta=1.0)
        zero = model.compute(self.A, "base", {"discount_rate": 0.0}, with_sensitivity=False)
        self.assertAlmostEqual(zero["roi"]["npv"], zero["roi"]["net_total"], delta=1.0)

    def test_payback_consistent_with_cumulative_cash(self):
        pb = self.base["roi"]["payback_months"]
        self.assertTrue(0 < pb < 36)
        A, P = model.resolve(self.A, "base")
        sim = model._simulate(A, P, 60)
        net = [sum(sim["benefit"][c][m] for c, _ in model.BENEFIT_CATEGORIES) - sum(sim["azure"][f][m] for f, _ in model.AZURE_FAMILIES)
               - sum(sim["other"][c][m] for c, _ in model.OTHER_COST_CATEGORIES) for m in range(60)]
        cum = 0.0
        for m in range(int(pb) - 1):
            cum += net[m]
        self.assertLess(cum, 0.0)
        self.assertGreaterEqual(sum(net[: int(math.ceil(pb)) + 1]), 0.0)

    # ------------------------------------------------------------------ scenarios
    def test_scenarios_are_ordered(self):
        c, b, u = (self.out["scenarios"][k] for k in ("conservative", "base", "upside"))
        self.assertLess(c["roi"]["npv"], b["roi"]["npv"])
        self.assertLess(b["roi"]["npv"], u["roi"]["npv"])
        self.assertLess(c["benefits"]["total"], b["benefits"]["total"])
        self.assertLess(b["benefits"]["total"], u["benefits"]["total"])
        self.assertLess(c["acr"]["by_year"][2], b["acr"]["by_year"][2])
        self.assertLess(b["acr"]["by_year"][2], u["acr"]["by_year"][2])
        self.assertGreater(c["roi"]["payback_months"], b["roi"]["payback_months"])
        self.assertGreater(b["roi"]["payback_months"], u["roi"]["payback_months"])
        self.assertGreater(b["roi"]["npv"], 0)

    def test_base_has_no_scenario_overrides(self):
        spec = self.A["assumptions"]
        for k, v in self.base["inputs"]["resolved"].items():
            self.assertEqual(v, spec[k]["base"], k)

    # ------------------------------------------------------------------ overrides
    def test_override_changes_results_in_expected_direction(self):
        base_npv = self.base["roi"]["npv"]
        hi = model.compute(self.A, "base", {"downtime_cost_per_line_hour_usd": 8000}, with_sensitivity=False)
        lo = model.compute(self.A, "base", {"downtime_cost_per_line_hour_usd": 2500}, with_sensitivity=False)
        self.assertGreater(hi["roi"]["npv"], base_npv)
        self.assertLess(lo["roi"]["npv"], base_npv)
        self.assertEqual(hi["inputs"]["overrides"], {"downtime_cost_per_line_hour_usd": 8000})
        more_plants = model.compute(self.A, "base", {"plants_total": 12, "revenue_usd": 3_000_000_000}, with_sensitivity=False)
        self.assertEqual(more_plants["plants"]["live_by_year_end"][-1], 12)
        self.assertGreater(more_plants["acr"]["run_rate_year3"], self.base["acr"]["run_rate_year3"])
        higher_rate = model.compute(self.A, "base", {"discount_rate": 0.15}, with_sensitivity=False)
        self.assertLess(higher_rate["roi"]["npv"], base_npv)
        slow = model.compute(self.A, "base", {"benefit_ramp": [0.1, 0.3, 0.5]}, with_sensitivity=False)
        self.assertLess(slow["roi"]["npv"], base_npv)

    def test_price_override(self):
        cheaper = model.compute(self.A, "base", {"price.fabric_cu_hour": 0.095}, with_sensitivity=False)
        self.assertLess(cheaper["acr"]["run_rate_by_family"]["fabric"], self.base["acr"]["run_rate_by_family"]["fabric"] * 0.7)
        discount = model.compute(self.A, "base", {"azure_price_multiplier": 0.5}, with_sensitivity=False)
        self.assertAlmostEqual(discount["acr"]["run_rate_year3"], self.base["acr"]["run_rate_year3"] * 0.5, delta=2.0)

    def test_invalid_overrides_are_rejected(self):
        for bad in ({"nope": 1}, {"discount_rate": 3.0}, {"plants_total": 0}, {"benefit_ramp": [0.1, 0.2]}, {"discount_rate": "x"}, {"price.nope": 1}, {"price.fabric_cu_hour": -1}):
            with self.assertRaises(ValueError, msg=str(bad)):
                model.compute(self.A, "base", bad, with_sensitivity=False)
        with self.assertRaises(ValueError):
            model.compute(self.A, "optimistic")

    # ------------------------------------------------------------------ ACR
    def test_run_rate_equals_customer_tier_and_line_items(self):
        acr = self.base["acr"]
        tiers = {t["id"]: t for t in acr["tiers"]}
        self.assertEqual(list(tiers), ["pilot", "plant_1", "customer", "enterprise_25"])
        self.assertAlmostEqual(tiers["customer"]["total"], acr["run_rate_year3"], delta=0.5)
        self.assertAlmostEqual(sum(ln["annual"] for ln in acr["line_items"]), acr["run_rate_year3"], delta=1.0)
        for fam, total in acr["run_rate_by_family"].items():
            self.assertAlmostEqual(sum(ln["annual"] for ln in acr["line_items"] if ln["family"] == fam), total, delta=1.0, msg=fam)
        for ln in acr["line_items"]:
            if ln["kind"] != "uplift":
                self.assertAlmostEqual(ln["quantity"] * ln["unit_price"], ln["annual"], delta=max(0.01, abs(ln["annual"]) * 1e-6), msg=ln["id"])

    def test_tier_economics(self):
        t = {x["id"]: x for x in self.base["acr"]["tiers"]}
        self.assertLess(t["pilot"]["total"], t["plant_1"]["total"])
        self.assertLess(t["plant_1"]["total"], t["customer"]["total"])
        self.assertLess(t["customer"]["total"], t["enterprise_25"]["total"])
        self.assertLess(t["enterprise_25"]["per_plant"], t["plant_1"]["per_plant"], "shared platform should dilute per-plant ACR")
        self.assertEqual(t["pilot"]["assets_per_plant"], 50)

    def test_pull_through_definition(self):
        acr = self.base["acr"]
        fam = acr["run_rate_by_family"]
        core = fam["ai_foundry"] + fam["azure_ml"]
        self.assertAlmostEqual(acr["pull_through_ratio"], (acr["run_rate_year3"] - core) / core, places=6)
        self.assertAlmostEqual(sum(a["share"] for a in acr["attach"].values()), 1.0, places=6)

    def test_ramp_in_acr(self):
        y = self.base["acr"]["by_year"]
        self.assertLess(y[0], y[1])
        self.assertLess(y[1], y[2])
        self.assertLess(y[2], self.base["acr"]["run_rate_year3"])

    def test_opportunity_block(self):
        o = self.base["acr"]["opportunity"]
        self.assertAlmostEqual(o["addressable_plants_eu"], 30_000_000 * 0.483 / 400 * 0.30, delta=1.0)
        self.assertAlmostEqual(o["acr_at_penetration_year5"], o["potential_acr_at_full_penetration"] * o["penetration_year5"], delta=10.0)

    # ------------------------------------------------------------------ benefits
    def test_benefit_formulas(self):
        A, _ = model.resolve(self.A, "base")
        gross, adj, derived = model._plant_benefits(A)
        plant_rev = 2e9 / 8
        self.assertAlmostEqual(derived["plant_revenue_usd"], plant_rev)
        self.assertAlmostEqual(derived["downtime_hours_avoided_per_plant_year"], 5 * 6000 * 0.054 * 0.20, places=6)
        self.assertAlmostEqual(derived["downtime_cost_per_line_hour_usd"], plant_rev / 30000 * 0.5, places=6)
        self.assertAlmostEqual(gross["downtime"], derived["downtime_hours_avoided_per_plant_year"] * derived["downtime_cost_per_line_hour_usd"], places=4)
        self.assertAlmostEqual(gross["scrap"], plant_rev * 0.02 * 0.12, places=4)
        self.assertAlmostEqual(adj["downtime"], gross["downtime"] * 0.8, places=4)
        self.assertTrue(all(0 < adj[c] < gross[c] for c, _ in model.BENEFIT_CATEGORIES))
        self.assertNotIn("working_capital", self.base["benefits"]["by_category"], "working-capital release must stay a memo item")

    def test_zero_benefit_case_has_no_payback_or_irr(self):
        zero = {"downtime_reduction_pct": 0, "maintenance_cost_reduction_pct": 0, "oee_performance_uplift_pts": 0, "scrap_reduction_pct": 0, "energy_saving_pct": 0,
                "indirect_labour_productivity_gain_pct": 0, "inventory_reduction_pct": 0, "expedite_reduction_pct": 0, "late_delivery_reduction_pct": 0}
        r = model.compute(self.A, "base", zero, with_sensitivity=False)
        self.assertEqual(r["benefits"]["total"], 0)
        self.assertLess(r["roi"]["npv"], 0)
        self.assertIsNone(r["roi"]["payback_months"])
        self.assertIsNone(r["roi"]["irr_pct"])

    def test_edge_configurations(self):
        one = model.compute(self.A, "base", {"plants_total": 1, "revenue_usd": 250_000_000}, with_sensitivity=False)
        self.assertEqual(one["plants"]["live_by_year_end"][-1], 1)
        self.assertGreater(one["acr"]["run_rate_year3"], 0)
        five_year = model.compute({**self.A, "meta": {**self.A["meta"], "horizon_years": 5}}, "base", with_sensitivity=False)
        self.assertEqual(len(five_year["roi"]["cumulative"]), 5)
        self.assertEqual(five_year["plants"]["live_by_year_end"][-1], 8)

    # ------------------------------------------------------------------ sensitivity
    def test_sensitivity_tornado(self):
        s = self.base["sensitivity"]
        self.assertGreaterEqual(len(s), 10)
        swings = [r["swing"] for r in s]
        self.assertEqual(swings, sorted(swings, reverse=True))
        ids = [r["id"] for r in s]
        self.assertIn("benefit_ramp", ids[:3])
        self.assertNotIn("downtime_cost_per_line_hour_usd", ids)
        for r in s:
            self.assertAlmostEqual(r["swing"], abs(r["npv_high"] - r["npv_low"]), delta=0.01)
        self.assertTrue(self.base["acr_sensitivity"])


class ExpansionLeverTests(unittest.TestCase):
    """Expansion levers E1-E5: OFF in Base and Conservative, ON in Upside, switchable through overrides, each with its own cost and benefit."""

    @classmethod
    def setUpClass(cls):
        cls.A = model.load_assumptions()
        cls.out = model.compute_all(cls.A)
        cls.base, cls.cons, cls.up = (cls.out["scenarios"][k] for k in ("base", "conservative", "upside"))
        cls.keys = [p + "_adoption" for _, p, _ in model.EXPANSION_LEVERS]

    def run_base(self, **overrides):
        return model.compute(self.A, "base", overrides, with_sensitivity=False)

    # ------------------------------------------------------------------ Base is untouched
    def test_base_golden_values_are_unchanged(self):
        """The levers must not move the Base case (engineering vendors the model and pins these numbers)."""
        self.assertAlmostEqual(self.base["roi"]["npv"], 8259298.701, delta=0.01)
        self.assertAlmostEqual(self.base["benefits"]["total"], 21389998.5, delta=0.01)
        self.assertAlmostEqual(self.base["costs"]["total"], 10476907.15, delta=0.01)
        self.assertAlmostEqual(self.base["acr"]["by_year"][2], 677151.2704, delta=0.01)
        self.assertAlmostEqual(self.base["acr"]["run_rate_year3"], 910013.9192, delta=0.01)
        self.assertAlmostEqual(self.cons["acr"]["run_rate_year3"], 734941.7691, delta=0.01)

    def test_levers_are_off_in_base_and_conservative_and_on_in_upside(self):
        for r in (self.base, self.cons):
            self.assertEqual(set(r["acr"]["lever_adoption"]), set(model.LEVER_IDS))
            self.assertTrue(all(v == 0 for v in r["acr"]["lever_adoption"].values()))
            self.assertEqual(list(r["benefits"]["by_category"]), [c for c, _ in model.BENEFIT_CATEGORIES], "Base shape must stay the ten core categories")
            for lid in model.LEVER_IDS:
                self.assertEqual(r["acr"]["by_lever"][lid], [0, 0, 0])
                self.assertEqual(r["acr"]["run_rate_by_lever"][lid], 0)
            self.assertTrue(all(ln["lever"] == "core" for ln in r["acr"]["line_items"]))
        self.assertTrue(all(v > 0 for v in self.up["acr"]["lever_adoption"].values()))
        for cat, _ in model.EXPANSION_BENEFIT_CATEGORIES:
            self.assertIn(cat, self.up["benefits"]["by_category"])
            self.assertIn(cat, self.up["benefits"]["category_labels"])
            self.assertIn(cat, self.up["benefits"]["confidence"])
        self.assertGreater(self.up["acr"]["by_year"][2], 1.5 * self.base["acr"]["by_year"][2])

    def test_upside_sums_stay_consistent(self):
        for r in (self.up, self.base["expansion"]):
            ben = r["benefits"] if "benefits" in r else None
            y3 = r["acr"]["by_year"]
            by_lever = r["acr"]["by_lever"]
            for y in range(3):
                self.assertAlmostEqual(sum(v[y] for v in by_lever.values()), y3[y], delta=0.5)
            self.assertAlmostEqual(sum(r["acr"]["run_rate_by_lever"].values()), r["acr"]["run_rate"] if "run_rate" in r["acr"] else r["acr"]["run_rate_year3"], delta=0.5)
            for y in range(3):
                self.assertAlmostEqual(sum(v[y] for v in ben["by_category"].values()), ben["total_by_year"][y], delta=0.01)
        up_lines = self.up["acr"]["line_items"]
        self.assertAlmostEqual(sum(ln["annual"] for ln in up_lines), self.up["acr"]["run_rate_year3"], delta=1.0)
        for ln in up_lines:
            if ln["kind"] != "uplift":
                self.assertAlmostEqual(ln["quantity"] * ln["unit_price"], ln["annual"], delta=max(0.01, abs(ln["annual"]) * 1e-6), msg=ln["id"])

    # ------------------------------------------------------------------ switchable through overrides
    def test_each_lever_can_be_switched_on_alone(self):
        base = self.base
        for (lid, prefix, _), key in zip(model.EXPANSION_LEVERS, self.keys):
            r = self.run_base(**{key: 1.0})
            self.assertGreater(r["acr"]["run_rate_year3"], base["acr"]["run_rate_year3"], lid)
            self.assertGreater(r["acr"]["by_year"][2], base["acr"]["by_year"][2], lid)
            self.assertGreater(r["benefits"]["total"] + r["benefits"]["steady_state_at_all_plants_risk_adjusted"], base["benefits"]["total"] + base["benefits"]["steady_state_at_all_plants_risk_adjusted"], lid)
            self.assertGreater(r["costs"]["total"], base["costs"]["total"], lid)
            self.assertGreater(r["acr"]["run_rate_by_lever"][lid], 0, lid)
            for other in model.LEVER_IDS:
                if other != lid:
                    self.assertEqual(r["acr"]["run_rate_by_lever"][other], 0, f"{lid} must not leak into {other}")
            self.assertAlmostEqual(r["acr"]["run_rate_by_lever"]["core"], base["acr"]["run_rate_year3"], delta=0.5)
            self.assertAlmostEqual(r["acr"]["run_rate_year3"], base["acr"]["run_rate_year3"] + r["acr"]["run_rate_by_lever"][lid], delta=0.5)

    def test_adoption_scales_consumption_and_benefit(self):
        half = self.run_base(exp_vision_adoption=0.5)
        full = self.run_base(exp_vision_adoption=1.0)
        self.assertAlmostEqual(full["acr"]["run_rate_by_lever"]["E1"], 2 * half["acr"]["run_rate_by_lever"]["E1"], delta=1.0)
        self.assertGreater(full["benefits"]["by_category"]["labour"][2], half["benefits"]["by_category"]["labour"][2])
        self.assertGreater(half["benefits"]["by_category"]["labour"][2], self.base["benefits"]["by_category"]["labour"][2])

    def test_lever_override_validation(self):
        for bad in ({"exp_vision_adoption": 1.5}, {"exp_hf_adoption": -0.1}, {"exp_sim_adoption": "all"}, {"exp_benefit_ramp": [0.4, 0.8]}, {"exp_dp_fabric_cu_per_plant": -1}):
            with self.assertRaises(ValueError, msg=str(bad)):
                self.run_base(**bad)
        r = self.run_base(exp_sec_adoption=1.0, **{"price.azure_firewall_premium_deployment_hour": 3.5})
        self.assertGreater(r["acr"]["run_rate_by_lever"]["E5"], self.run_base(exp_sec_adoption=1.0)["acr"]["run_rate_by_lever"]["E5"])

    def test_specific_drivers_move_the_right_lever(self):
        lo = self.run_base(exp_vision_adoption=1.0, exp_vision_cameras_per_plant=20)
        hi = self.run_base(exp_vision_adoption=1.0, exp_vision_cameras_per_plant=60)
        self.assertGreater(hi["acr"]["run_rate_by_lever"]["E1"], lo["acr"]["run_rate_by_lever"]["E1"])
        stream = self.run_base(exp_hf_adoption=1.0, exp_hf_duty_cycle=1.0)
        snap = self.run_base(exp_hf_adoption=1.0)
        self.assertGreater(stream["acr"]["run_rate_by_lever"]["E2"], 3 * snap["acr"]["run_rate_by_lever"]["E2"], "continuous raw streaming must multiply E2")
        fabric_small = self.run_base(exp_dp_adoption=1.0, exp_dp_fabric_cu_enterprise=0, exp_dp_fabric_cu_per_plant=0)
        fabric_big = self.run_base(exp_dp_adoption=1.0)
        self.assertGreater(fabric_big["acr"]["run_rate_by_family"]["fabric"], fabric_small["acr"]["run_rate_by_family"]["fabric"])
        sim = self.run_base(exp_sim_adoption=1.0, exp_sim_rollouts_per_decision=128)
        self.assertGreater(sim["acr"]["run_rate_by_lever"]["E3"], self.run_base(exp_sim_adoption=1.0)["acr"]["run_rate_by_lever"]["E3"])

    # ------------------------------------------------------------------ the expansion block
    def test_expansion_block_structure_and_arithmetic(self):
        for name, r in self.out["scenarios"].items():
            ex = r["expansion"]
            tiers = {t["id"]: t for t in ex["tiers"]}
            self.assertEqual(list(tiers), ["pilot", "plant_1", "customer", "enterprise_25", "fleet"])
            self.assertEqual(tiers["fleet"]["plants"], 100)
            for t in ex["tiers"]:
                w, wl = t["without_levers"], t["with_levers"]
                self.assertAlmostEqual(sum(wl["by_lever"].values()), wl["total"], delta=0.5, msg=f"{name}/{t['id']}")
                self.assertAlmostEqual(wl["by_lever"]["core"], w["total"], delta=0.5, msg=f"{name}/{t['id']}")
                self.assertAlmostEqual(wl["per_plant"] * t["plants"], wl["total"], delta=0.5)
                self.assertAlmostEqual(wl["per_asset_year"] * t["plants"] * t["assets_per_plant"], wl["total"], delta=0.5)
                self.assertGreaterEqual(wl["total"], w["total"])
            self.assertEqual(tiers["pilot"]["with_levers"]["total"], tiers["pilot"]["without_levers"]["total"], "a single-line pilot has no levers")
            self.assertGreater(tiers["fleet"]["with_levers"]["total"], tiers["enterprise_25"]["with_levers"]["total"])
            self.assertGreater(tiers["customer"]["uplift_multiple"], 1.5)
            path = ex["path"]
            self.assertEqual([p["id"] for p in path], ["core", *model.LEVER_IDS, "expansion", "enterprise_25", "fleet"])
            self.assertAlmostEqual(path[0]["value"] + sum(p["value"] for p in path[1:6]), path[6]["value"], delta=0.5)
            self.assertAlmostEqual(path[6]["value"], ex["acr"]["run_rate"], delta=0.5)
        e = self.base["expansion"]
        self.assertAlmostEqual(e["headline"]["acr_run_rate"], self.base["acr"]["run_rate_year3"] + sum(v for k, v in e["acr"]["run_rate_by_lever"].items() if k != "core"), delta=0.5)
        self.assertAlmostEqual(self.up["expansion"]["headline"]["npv"], self.up["roi"]["npv"], delta=1.0, msg="Upside already has the levers on")
        self.assertAlmostEqual(self.up["expansion"]["headline"]["acr_run_rate"], self.up["acr"]["run_rate_year3"], delta=1.0)

    def test_expansion_view_reaches_a_multi_million_run_rate(self):
        e = self.base["expansion"]
        customer = next(t for t in e["tiers"] if t["id"] == "customer")
        fleet = next(t for t in e["tiers"] if t["id"] == "fleet")
        self.assertGreater(customer["with_levers"]["total"], 1.8 * self.base["acr"]["run_rate_year3"])
        self.assertGreater(fleet["with_levers"]["total"], 15e6)
        self.assertGreater(self.up["acr"]["run_rate_year3"], 2.0e6)

    def test_each_lever_has_its_own_cost_and_benefit(self):
        for lv in self.base["expansion"]["levers"]:
            p = lv["per_deploying_plant"]
            self.assertGreater(p["azure_run_cost"], 0, lv["id"])
            self.assertGreater(p["other_run_cost"], 0, lv["id"])
            self.assertGreater(p["benefit"], 0, lv["id"])
            self.assertGreater(p["one_time_cost"], 0, lv["id"])
            self.assertAlmostEqual(p["net"], p["benefit"] - p["azure_run_cost"] - p["other_run_cost"], delta=0.5)
            self.assertTrue(lv["note"])
            by_year = lv["by_year"]
            for y in range(3):
                self.assertAlmostEqual(by_year["net"][y], by_year["benefit"][y] - by_year["azure"][y] - by_year["other_cost"][y], delta=0.5)

    def test_roi_stays_coherent(self):
        """E1-E4 must pay back in under two years once running; E5 is a documented risk/compliance lever with a modest or negative net."""
        by_id = {lv["id"]: lv for lv in self.base["expansion"]["levers"]}
        for lid in ("E1", "E2", "E3", "E4"):
            pb = by_id[lid]["per_deploying_plant"]["payback_months"]
            self.assertIsNotNone(pb, lid)
            self.assertLess(pb, 24, lid)
        self.assertLess(by_id["E5"]["per_deploying_plant"]["net"], 0.25 * by_id["E5"]["per_deploying_plant"]["benefit"] + 1)
        # benefits of the levers appear in the customer totals, so ROI is never inflated by consumption alone
        full_off = self.run_base()
        full_on = self.run_base(**{k: 1.0 for k in self.keys})
        self.assertGreater(full_on["benefits"]["steady_state_at_all_plants_risk_adjusted"], 1.2 * full_off["benefits"]["steady_state_at_all_plants_risk_adjusted"])
        self.assertGreater(full_on["costs"]["total"], full_off["costs"]["total"] + (full_on["acr"]["by_year"][0] - full_off["acr"]["by_year"][0]))
        self.assertGreater(full_on["memo"]["five_year"]["npv"], full_off["memo"]["five_year"]["npv"] - 3e6, "levers must not destroy value over five years")

    def test_lever_line_items_are_priced_and_tagged(self):
        lever_lines = [ln for ln in self.up["acr"]["line_items"] if ln["lever"] != "core"]
        self.assertEqual({ln["lever"] for ln in lever_lines}, set(model.LEVER_IDS))
        for ln in lever_lines:
            if ln["kind"] != "uplift":
                self.assertIn(ln["price_id"] or "none", [*self.A["prices"], "none"], ln["id"])
                self.assertAlmostEqual(ln["unit_price"], self.A["prices"][ln["price_id"]]["price"] if ln["price_id"] else ln["unit_price"], places=9, msg=ln["id"])
        new_prices = {"vm_nc24ads_a100_v4_hour", "expressroute_1gbps_metered_circuit_month", "expressroute_metered_data_out_gb", "azure_firewall_premium_deployment_hour",
                      "azure_firewall_premium_data_processed_gb", "defender_servers_p2_node_hour"}
        self.assertTrue(new_prices <= {ln["price_id"] for ln in lever_lines}, "every new meter is used by a lever line")

    def test_sensitivity_includes_lever_drivers_only_when_levers_are_on(self):
        base_ids = {r["id"] for r in self.base["sensitivity"]} | {r["id"] for r in self.base["acr_sensitivity"]}
        self.assertFalse([i for i in base_ids if i.startswith("exp_")])
        up_ids = {r["id"] for r in self.up["sensitivity"]} | {r["id"] for r in self.up["acr_sensitivity"]}
        self.assertTrue([i for i in up_ids if i.startswith("exp_")])


if __name__ == "__main__":
    unittest.main()
