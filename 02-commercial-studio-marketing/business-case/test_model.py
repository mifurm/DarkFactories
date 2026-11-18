"""Unit tests for the ROI / ACR model (stdlib unittest).  Run:  python -m unittest test_model -v"""
from __future__ import annotations

import ast
import copy
import json
import math
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import model  # noqa: E402


def _finite(obj) -> bool:
    if isinstance(obj, float):
        return math.isfinite(obj)
    if isinstance(obj, dict):
        return all(_finite(v) for v in obj.values())
    if isinstance(obj, (list, tuple)):
        return all(_finite(v) for v in obj)
    return True


def _read(name: str) -> str:
    with open(os.path.join(HERE, name), encoding="utf-8") as fh:
        return fh.read()


class AssumptionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.A = model.load_assumptions()

    def test_every_assumption_is_documented(self):
        sources = set(self.A["sources"]) | {"brief", "assumption"}
        for key, a in self.A["assumptions"].items():
            with self.subTest(key=key):
                for f in ("label", "unit", "group", "rationale", "flag", "source", "favourable"):
                    self.assertTrue(a.get(f), f"{key}.{f} missing")
                self.assertLessEqual(a["low"], a["base"], key)
                self.assertLessEqual(a["base"], a["high"], key)
                self.assertIn(a["flag"], {"brief", "sourced", "assumption"})
                self.assertIn(a["favourable"], {"high", "low", "neutral"})
                for token in [s.strip() for s in a["source"].split(";")]:
                    self.assertIn(token, sources, f"{key}: unknown source '{token}'")
                if a["flag"] == "sourced":
                    self.assertNotEqual(a["source"], "assumption")

    def test_all_model_keys_exist_and_mixes_sum_to_one(self):
        self.assertEqual([k for k in model.required_keys() if k not in self.A["assumptions"]], [])
        for kind in ("baseline", "studio"):
            self.assertAlmostEqual(sum(self.A["assumptions"][f"mix_{kind}_{c}"]["base"] for c in model.CLASSES), 1.0, places=9)

    def test_scenario_drivers_and_sensitivity_keys_exist(self):
        for k in self.A["meta"]["scenario_drivers"]:
            self.assertIn(k, self.A["assumptions"])
        for d in self.A["sensitivity_drivers"]:
            for k in d["keys"]:
                self.assertIn(k, self.A["assumptions"], d["id"])

    def test_pricing_snapshot_is_complete_and_consistent(self):
        items = self.A["pricing"]["items"]
        src = _read("model.py")
        used = set(re.findall(r'P\["([a-z0-9_]+)"\]', src))
        used |= {f"afd_{sku}_{m}" for sku in ("premium", "standard") for m in ("out_gb", "requests_10k", "base_month")}
        for fp in self.A["footprints"].values():
            used.add(fp["search_price_key"])
            if fp["apim_price_key"]:
                used.add(fp["apim_price_key"])
        used |= {"acr_standard_day", "acr_premium_day"}
        self.assertEqual(sorted(used - set(items)), [])
        for key, it in items.items():
            with self.subTest(key=key):
                self.assertGreater(it["price"], 0)
                self.assertAlmostEqual(it["price"], it["api_price"] * it["factor"], delta=1e-12 + 1e-9 * it["price"])
                for f in ("service", "meter", "region", "unit"):
                    self.assertTrue(it[f])
        meta = self.A["pricing"]["meta"]
        self.assertEqual(meta["currency"], "USD")
        self.assertRegex(meta["retrieved_at"], r"^\d{4}-\d{2}-\d{2}$")

    def test_model_is_pure_standard_library(self):
        tree = ast.parse(_read("model.py"))
        roots = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                roots.add(node.module.split(".")[0])
        self.assertTrue(roots <= set(sys.stdlib_module_names), roots - set(sys.stdlib_module_names))


class ModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.A = model.load_assumptions()
        cls.base = model.compute(cls.A, "base")

    def test_deterministic_and_case_insensitive(self):
        self.assertEqual(model.compute(self.A, "base"), model.compute(copy.deepcopy(self.A), "Base"))
        self.assertTrue(_finite(self.base))

    def test_result_contract(self):
        r = self.base
        for key in ("scenario", "currency", "horizon_years", "inputs", "benefits", "costs", "roi", "acr", "sensitivity"):
            self.assertIn(key, r)
        self.assertEqual((r["scenario"], r["currency"], r["horizon_years"], r["years"]), ("base", "USD", 3, [0, 1, 2, 3]))
        for key in ("by_category", "total_by_year", "total"):
            self.assertIn(key, r["benefits"])
        for key in ("azure_by_family", "other_by_category", "total_by_year", "total"):
            self.assertIn(key, r["costs"])
        for key in ("net_benefit_by_year", "cumulative", "npv", "discount_rate", "roi_pct", "payback_months", "irr_pct"):
            self.assertIn(key, r["roi"])
        for key in ("by_year", "by_family", "run_rate_year3", "tiers", "pull_through_ratio"):
            self.assertIn(key, r["acr"])
        self.assertEqual(set(r["benefits"]["by_category"]), set(model.BENEFIT_LABELS))
        self.assertEqual(set(r["acr"]["by_family"]), set(model.FAMILIES))
        self.assertEqual([t["tier"] for t in r["acr"]["tiers"]], list(model.TIERS))
        self.assertEqual(set(model.compute_all(self.A)["scenarios"]), {"conservative", "base", "upside"})

    def test_scenarios_are_ordered(self):
        res = [model.compute(self.A, s) for s in model.SCENARIOS]
        npvs = [r["roi"]["npv"] for r in res]
        self.assertLess(npvs[0], npvs[1])
        self.assertLess(npvs[1], npvs[2])
        acr = [r["acr"]["run_rate_year3"] for r in res]
        self.assertLess(acr[0], acr[1])
        self.assertLess(acr[1], acr[2])
        self.assertGreater(npvs[0], 0, "Conservative scenario is expected to remain NPV-positive with the shipped assumptions")

    def test_accounting_identities(self):
        r = self.base
        ben, cost, roi = r["benefits"], r["costs"], r["roi"]
        for t in range(4):
            self.assertAlmostEqual(sum(v[t] for v in ben["by_category"].values()), ben["total_by_year"][t], delta=0.05)
            azure = sum(v[t] for v in cost["azure_by_family"].values())
            other = sum(v[t] for v in cost["other_by_category"].values())
            self.assertAlmostEqual(azure + other, cost["total_by_year"][t], delta=0.05)
            self.assertAlmostEqual(azure, r["acr"]["by_year"][t], delta=0.05)
            self.assertAlmostEqual(ben["total_by_year"][t] - cost["total_by_year"][t], roi["net_benefit_by_year"][t], delta=0.05)
        self.assertAlmostEqual(sum(ben["total_by_year"]), ben["total"], delta=0.1)
        self.assertAlmostEqual(sum(cost["total_by_year"]), cost["total"], delta=0.1)
        run = 0.0
        for t, x in enumerate(roi["net_benefit_by_year"]):
            run += x
            self.assertAlmostEqual(run, roi["cumulative"][t], delta=0.1)
        npv = sum(x / (1 + roi["discount_rate"]) ** t for t, x in enumerate(roi["net_benefit_by_year"]))
        self.assertAlmostEqual(npv, roi["npv"], delta=1.0)
        self.assertAlmostEqual(roi["roi_pct"], (ben["total"] - cost["total"]) / cost["total"] * 100, places=2)
        self.assertEqual(ben["total_by_year"][0], 0)
        self.assertGreater(cost["total_by_year"][0], 0)

    def test_irr_and_payback_are_consistent(self):
        roi = self.base["roi"]
        irr = roi["irr_pct"] / 100.0
        npv_at_irr = sum(x / (1 + irr) ** t for t, x in enumerate(roi["net_benefit_by_year"]))
        self.assertAlmostEqual(npv_at_irr, 0.0, delta=50.0)
        months = roi["payback_months"]
        self.assertTrue(0 < months < 36)
        cum = roi["cumulative"]
        year = int(months // 12) + 1
        self.assertLess(cum[year - 1], 0)
        self.assertGreaterEqual(cum[year], 0)
        self.assertAlmostEqual(roi["breakeven_benefit_haircut_pct"], (1 - roi["pv_cost"] / roi["pv_benefit"]) * 100, places=3)

    def test_acr_structure(self):
        a = self.base["acr"]
        for t in range(4):
            self.assertAlmostEqual(sum(v[t] for v in a["by_family"].values()), a["by_year"][t], delta=0.05)
            self.assertAlmostEqual(a["direct_by_year"][t] + a["attach_by_year"][t], a["by_year"][t], delta=0.05)
        self.assertEqual(a["by_year"][0], 0)
        self.assertEqual(a["run_rate_year3"], a["by_year"][3])
        self.assertAlmostEqual(a["pull_through_ratio"], a["attach_by_year"][3] / a["direct_by_year"][3], places=4)
        self.assertLess(a["by_year"][1], a["by_year"][2])
        self.assertLess(a["by_year"][2], a["by_year"][3])
        runs = [t["acr_run_rate_usd"] for t in a["tiers"]]
        self.assertEqual(runs, sorted(runs))
        for t in a["tiers"]:
            self.assertAlmostEqual(sum(t["by_family"].values()), t["acr_run_rate_usd"], delta=0.05)
        self.assertEqual(a["pricing_basis"]["retrieved_at"], self.A["pricing"]["meta"]["retrieved_at"])

    def test_portfolio_and_tam(self):
        a = self.base["acr"]
        pf, tiers = a["portfolio"], {t["tier"]: t["acr_run_rate_usd"] for t in a["tiers"]}
        self.assertAlmostEqual(pf["acr_by_tier_by_year"]["pilot"][2], 16 * tiers["pilot"], delta=1.0)
        self.assertAlmostEqual(pf["acr_by_tier_by_year"]["one_brand"][2], (2 * 0.8 + 6 * 0.5) * tiers["one_brand"], delta=1.0)
        self.assertAlmostEqual(sum(pf["total_by_year"]), pf["cumulative_3yr"], delta=1.0)
        tam = a["tam"]
        ceiling = (1500 * 0.35 * tiers["one_brand"] + 1500 * 0.65 * tiers["global_portfolio"] + 40 * tiers["agency_network"])
        self.assertAlmostEqual(tam["annual_acr_ceiling_usd"], ceiling, delta=5.0)

    def test_unit_economics(self):
        ue = self.base["unit_economics"]
        by = ue["by_class"]
        for c in ("adapted_video", "static_social", "copy_crm"):
            self.assertGreater(by[c]["saving_pct"], 50)
        self.assertLess(by["hero_spot"]["saving_pct"], by["adapted_video"]["saving_pct"])
        self.assertLess(ue["azure_direct_cost_per_version"], ue["studio_all_in_cost_per_version"])
        self.assertLess(ue["studio_all_in_cost_per_version"], ue["agency_blended_cost_per_baseline_asset"])
        self.assertAlmostEqual(ue["azure_direct_cost_per_version"] * ue["versions"], self.base["acr"]["direct_by_year"][3], delta=1.0)

    def test_sensitivity_tornado(self):
        s = self.base["sensitivity"]
        self.assertGreaterEqual(len(s), 12)
        swings = [d["swing"] for d in s]
        self.assertEqual(swings, sorted(swings, reverse=True))
        for d in s:
            self.assertAlmostEqual(d["base_npv"], self.base["roi"]["npv"], delta=0.05)
            self.assertAlmostEqual(abs(d["npv_high"] - d["npv_low"]), d["swing"], delta=0.05)
        by_id = {d["id"]: d for d in s}
        self.assertLess(by_id["azure_consumption"]["swing"], 0.05 * by_id["agency_cost"]["swing"])

    def test_costs_include_azure_run_cost_from_acr(self):
        r = self.base
        self.assertGreater(r["roi"]["azure_share_of_cost_pct"], 0)
        self.assertLess(r["roi"]["azure_share_of_benefit_pct"], 15)
        self.assertEqual(r["costs"]["azure_total_by_year"], r["acr"]["by_year"])


class OverrideTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.A = model.load_assumptions()
        cls.base = model.compute(cls.A, "base")

    def cat(self, r, name, year=3):
        return r["benefits"]["by_category"][name][year]

    def test_media_spend_scales_roas_benefit_linearly(self):
        media = self.base["customer"]["media_spend_in_scope_usd"]
        r = model.compute(self.A, "base", {"media_spend_in_scope_usd": 2 * media})
        for y in (1, 2, 3):
            self.assertAlmostEqual(self.cat(r, "roas_uplift", y), 2 * self.cat(self.base, "roas_uplift", y), delta=1.0)

    def test_agency_cost_scale_doubles_production_benefit(self):
        r = model.compute(self.A, "base", {"agency_cost_scale": 2.0})
        self.assertAlmostEqual(self.cat(r, "production_adaptation") / self.cat(self.base, "production_adaptation"), 2.0, places=6)
        r2 = model.compute(self.A, "base", {"agency_cost_per_adapted_asset_usd": 6400})
        self.assertGreater(self.cat(r2, "production_adaptation"), self.cat(self.base, "production_adaptation"))

    def test_zero_adoption_has_no_benefits_and_no_payback(self):
        r = model.compute(self.A, "base", {"adoption_ramp": [0, 0, 0]})
        self.assertEqual(r["benefits"]["total"], 0)
        self.assertIsNone(r["roi"]["payback_months"])
        self.assertIsNone(r["roi"]["irr_pct"])
        self.assertLess(r["roi"]["npv"], 0)
        self.assertEqual(r["overrides"] if "overrides" in r else r["inputs"]["overrides"], {"adoption_ramp": [0.0, 0.0, 0.0]})

    def test_markets_drive_localisation(self):
        few = model.compute(self.A, "base", {"markets": 4})
        many = model.compute(self.A, "base", {"markets": 20})
        self.assertLess(self.cat(few, "localization"), self.cat(self.base, "localization"))
        self.assertGreater(self.cat(many, "localization"), self.cat(self.base, "localization"))
        self.assertLess(few["volumes"]["localized_versions_by_year"][3], many["volumes"]["localized_versions_by_year"][3])
        self.assertLess(few["acr"]["by_year"][3], many["acr"]["by_year"][3])

    def test_variants_have_diminishing_returns(self):
        b = {v: self.cat(model.compute(self.A, "base", {"variants_per_campaign": v}), "roas_uplift") for v in (4, 12, 24)}
        self.assertLess(b[4], b[12])
        self.assertLess(b[12], b[24])
        self.assertLess(b[24] - b[12], b[12] - b[4])

    def test_volume_beyond_coverage_adds_cost_not_benefit(self):
        r = model.compute(self.A, "base", {"annual_asset_volume": 100000})
        self.assertAlmostEqual(self.cat(r, "roas_uplift", 3), self.cat(self.base, "roas_uplift", 3), delta=1.0)
        self.assertGreater(r["acr"]["by_year"][3], self.base["acr"]["by_year"][3])
        small = model.compute(self.A, "base", {"annual_asset_volume": 5000})
        self.assertLess(self.cat(small, "roas_uplift", 3), self.cat(self.base, "roas_uplift", 3))

    def test_discount_rate_and_uplift_monotonic(self):
        lo = model.compute(self.A, "base", {"discount_rate": 0.05})["roi"]["npv"]
        hi = model.compute(self.A, "base", {"discount_rate": 0.20})["roi"]["npv"]
        self.assertGreater(lo, self.base["roi"]["npv"])
        self.assertLess(hi, self.base["roi"]["npv"])
        up = model.compute(self.A, "base", {"roas_uplift_pct": 0.10})["roi"]["npv"]
        self.assertGreater(up, self.base["roi"]["npv"])

    def test_azure_calibration_levers_move_acr_not_benefits(self):
        r = model.compute(self.A, "base", {"azure_consumption_scale": 2.0})
        self.assertGreater(r["acr"]["by_year"][3], self.base["acr"]["by_year"][3])
        self.assertLess(r["acr"]["by_year"][3], 2 * self.base["acr"]["by_year"][3])
        self.assertEqual(r["benefits"]["total"], self.base["benefits"]["total"])
        glob = model.compute(self.A, "base", {"ai_price_uplift_pct": 0.0})
        self.assertLess(glob["acr"]["by_family"]["azure_openai_text"][3], self.base["acr"]["by_family"]["azure_openai_text"][3])

    def test_invalid_overrides_are_rejected(self):
        for bad in ({"nope": 1}, {"markets": 0}, {"discount_rate": 0.9}, {"annual_asset_volume": "many"}, {"adoption_ramp": [0.1, 0.2]},
                    {"adoption_ramp": [0.1, 0.2, 1.5]}, {"roas_uplift_pct": float("nan")}, {"baseline_roas": True}, {"review_min_copy_crm": -1}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                model.compute(self.A, "base", bad)
        with self.assertRaises(ValueError):
            model.compute(self.A, "optimistic")

    def test_override_specs_are_consistent_with_assumptions(self):
        specs = model.override_specs()
        for key, spec in specs.items():
            with self.subTest(key=key):
                if spec["maps_to"]:
                    self.assertIn(spec["maps_to"], self.A["assumptions"])
                self.assertLess(spec["min"], spec["max"])
        calculator = {k for k, s in specs.items() if s["calculator"]}
        for needed in ("annual_asset_volume", "markets", "variants_per_campaign", "media_spend_in_scope_usd", "roas_uplift_pct",
                       "discount_rate", "adoption_ramp", "agency_cost_per_spot_usd", "agency_cost_per_adapted_asset_usd"):
            self.assertIn(needed, calculator)

    def test_advanced_override_by_assumption_key(self):
        r = model.compute(self.A, "base", {"review_min_adapted_video": 12})
        self.assertGreater(r["costs"]["other_by_category"]["review_creative_legal"][3], self.base["costs"]["other_by_category"]["review_creative_legal"][3])


class ExpansionLeverTests(unittest.TestCase):
    """Optional expansion levers E1-E4: off in Base (numbers unchanged), on in Upside, each with its own cost and benefit."""

    @classmethod
    def setUpClass(cls):
        cls.A = model.load_assumptions()
        cls.cons = model.compute(cls.A, "conservative")
        cls.base = model.compute(cls.A, "base")
        cls.up = model.compute(cls.A, "upside")
        cls.on = model.compute(cls.A, "base", {"expansion_scale": 1})

    def test_base_is_unchanged_release1_scope_when_levers_are_off(self):
        # Regression guard: these are the model v1.0.0 Base headline numbers; E1-E4 add nothing while their scale is 0.
        self.assertEqual({k: self.base["inputs"]["expansion"]["lever_scale"][k] for k in model.LEVERS}, {k: 0.0 for k in model.LEVERS})
        self.assertAlmostEqual(self.base["roi"]["npv"], 6979862.04, places=1)
        self.assertAlmostEqual(self.base["roi"]["payback_months"], 14.97, places=2)
        self.assertEqual([round(x) for x in self.base["acr"]["by_year"]], [0, 64541, 304893, 464798])
        for lv in model.LEVERS:
            self.assertEqual(sum(self.base["acr"]["by_lever"][lv]), 0.0)
            self.assertEqual(sum(self.base["benefits"]["by_category"][model.LEVER_BENEFIT_KEY[lv]]), 0.0)
        for k in ("expansion_integration", "expansion_run", "expansion_review"):
            self.assertEqual(sum(self.base["costs"]["other_by_category"][k]), 0.0)
        self.assertEqual([round(x) for x in self.cons["acr"]["by_lever"]["core"]], [round(x) for x in self.cons["acr"]["by_year"]])

    def test_upside_switches_all_levers_on_and_lifts_acr(self):
        self.assertEqual(set(self.up["inputs"]["expansion"]["lever_scale"].values()), {1.0})
        self.assertGreater(self.up["acr"]["run_rate_year3"], 1.8 * self.base["acr"]["run_rate_year3"])
        self.assertGreater(self.up["roi"]["npv"], self.base["roi"]["npv"])
        for lv in model.LEVERS:
            self.assertGreater(self.up["acr"]["by_lever"][lv][3], 0.0, lv)

    def test_acr_by_lever_adds_up_in_every_scenario(self):
        for r in (self.cons, self.base, self.up, self.on):
            for t in range(4):
                self.assertAlmostEqual(sum(v[t] for v in r["acr"]["by_lever"].values()), r["acr"]["by_year"][t], delta=0.05)
        fc = self.base["acr"]["expansion"]["full_expansion_case"]
        for t in range(4):
            self.assertAlmostEqual(sum(v[t] for v in fc["by_lever"].values()), fc["acr_by_year"][t], delta=0.05)

    def test_each_lever_carries_benefit_and_cost_and_roi_stays_coherent(self):
        r = self.on
        for lv in model.LEVERS:
            d = r["acr"]["expansion"]["levers"][lv]
            self.assertGreater(d["benefit_year3"], 0.0, lv)
            self.assertGreater(sum(d["non_azure_cost_by_year"]["integration"]), 0.0, lv)
            self.assertGreater(sum(d["acr_by_year"]), 0.0, lv)
        for t in range(4):
            self.assertAlmostEqual(r["roi"]["net_benefit_by_year"][t], r["benefits"]["total_by_year"][t] - r["costs"]["total_by_year"][t], delta=0.05)
            self.assertAlmostEqual(r["costs"]["total_by_year"][t], r["costs"]["azure_total_by_year"][t] + r["costs"]["other_total_by_year"][t], delta=0.05)
        # additive and independent: NPV gained equals the sum of the standalone lever NPVs
        gained = r["roi"]["npv"] - self.base["roi"]["npv"]
        self.assertAlmostEqual(gained, sum(d["npv"] for d in r["acr"]["expansion"]["levers"].values()), delta=1.0)
        # the Azure cost of the levers is part of Azure run cost, so the ROI statistics see it
        self.assertGreater(sum(r["costs"]["azure_total_by_year"]), sum(self.base["costs"]["azure_total_by_year"]))

    def test_full_expansion_case_equals_running_the_override(self):
        fc = self.base["acr"]["expansion"]["full_expansion_case"]
        self.assertAlmostEqual(fc["npv"], self.on["roi"]["npv"], delta=1.0)
        self.assertEqual([round(x) for x in fc["acr_by_year"]], [round(x) for x in self.on["acr"]["by_year"]])
        inc = fc["incremental_vs_this_scenario"]
        self.assertAlmostEqual(inc["acr_year3_usd"], self.on["acr"]["by_year"][3] - self.base["acr"]["by_year"][3], delta=1.0)
        # in Upside the levers are already on: nothing incremental
        self.assertAlmostEqual(self.up["acr"]["expansion"]["full_expansion_case"]["incremental_vs_this_scenario"]["npv_usd"], 0.0, delta=1.0)
        # the levers-off case is what the scenario was before expansion (and Base is already that)
        lo = self.up["acr"]["expansion"]["levers_off_case"]
        off = model.compute(self.A, "upside", {"expansion_scale": 0})
        self.assertAlmostEqual(lo["npv"], off["roi"]["npv"], delta=1.0)
        self.assertAlmostEqual(self.up["roi"]["npv"] - lo["npv"], lo["incremental_of_levers_in_this_scenario"]["npv_usd"], delta=1.0)
        self.assertAlmostEqual(self.base["acr"]["expansion"]["levers_off_case"]["npv"], self.base["roi"]["npv"], delta=0.01)

    def test_override_keys_switch_and_scale_levers(self):
        one = model.compute(self.A, "base", {"e2_scale": 1})
        self.assertGreater(one["acr"]["by_lever"]["e2"][3], 0.0)
        self.assertEqual(sum(one["acr"]["by_lever"]["e1"]), 0.0)
        half = model.compute(self.A, "base", {"e4_scale": 0.5})
        full = model.compute(self.A, "base", {"e4_scale": 1.0})
        self.assertAlmostEqual(half["acr"]["by_lever"]["e4"][3], 0.5 * full["acr"]["by_lever"]["e4"][3], delta=full["acr"]["by_lever"]["e4"][3] * 0.02)
        # master switch is overridden by an explicit per-lever key; zero in Upside turns every lever off
        mixed = model.compute(self.A, "base", {"expansion_scale": 1, "e1_scale": 0})
        self.assertEqual(sum(mixed["acr"]["by_lever"]["e1"]), 0.0)
        self.assertGreater(sum(mixed["acr"]["by_lever"]["e3"]), 0.0)
        off = model.compute(self.A, "upside", {"expansion_scale": 0})
        self.assertEqual([round(x) for x in off["acr"]["by_year"]], [round(x) for x in off["acr"]["by_lever"]["core"]])
        self.assertLess(off["acr"]["run_rate_year3"], self.up["acr"]["run_rate_year3"])
        # volumes, prices and ramps are overridable and move the right lines
        more = model.compute(self.A, "base", {"expansion_scale": 1, "catalog_skus": 24000})
        self.assertGreater(more["acr"]["by_lever"]["e2"][3], self.on["acr"]["by_lever"]["e2"][3] * 1.5)
        self.assertEqual(more["acr"]["by_lever"]["e1"], self.on["acr"]["by_lever"]["e1"])
        video = model.compute(self.A, "base", {"expansion_scale": 1, "video_seconds_per_hero_master": 80})
        self.assertGreater(video["acr"]["by_lever"]["e1"][3], self.on["acr"]["by_lever"]["e1"][3])
        slow = model.compute(self.A, "base", {"expansion_scale": 1, "expansion_ramp": [0.0, 0.2, 0.5]})
        self.assertLess(slow["acr"]["by_lever"]["e4"][3], self.on["acr"]["by_lever"]["e4"][3])
        self.assertEqual(slow["acr"]["by_lever"]["e4"][1], 0.0)

    def test_invalid_expansion_overrides_are_rejected(self):
        for bad in ({"e1_scale": 1.5}, {"expansion_scale": -0.1}, {"e3_scale": "all"}, {"expansion_ramp": [0.1, 0.5]},
                    {"expansion_ramp": [0.1, 0.5, 2.0]}, {"catalog_skus": 0}, {"personalization_multiplier": 1000}, {"e2_skus": -5}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                model.compute(self.A, "base", bad)

    def test_more_scale_means_more_acr_benefit_and_cost(self):
        low, high = model.compute(self.A, "base", {"expansion_scale": 0.4}), self.on
        self.assertLess(low["acr"]["run_rate_year3"], high["acr"]["run_rate_year3"])
        self.assertLess(low["benefits"]["total"], high["benefits"]["total"])
        self.assertLess(low["costs"]["total"], high["costs"]["total"])

    def test_enterprise_scale_tier_and_unit_economics(self):
        tiers = {t["tier"]: t for t in self.base["acr"]["tiers"]}
        ent, gp = tiers["enterprise_scale"], tiers["global_portfolio"]
        self.assertGreater(ent["acr_run_rate_usd"], 2.0 * gp["acr_run_rate_usd"])
        ex = ent["expansion"]
        self.assertEqual(set(ex["by_lever_usd"]), set(model.LEVERS))
        self.assertTrue(all(v > 0 for v in ex["by_lever_usd"].values()))
        self.assertAlmostEqual(ex["core_run_rate_usd"] + sum(ex["by_lever_usd"].values()), ent["acr_run_rate_usd"], delta=1.0)
        ue = ex["unit_economics"]
        video, image, version = ue["generative_video"], ue["catalog_image"], ue["personalized_version"]
        self.assertGreater(video["azure_cost_per_kept_second_usd"], video["list_price_per_generated_second_usd"], "takes are billed per generated second")
        self.assertGreaterEqual(image["azure_all_in_cost_per_kept_image_usd"], image["azure_variable_cost_per_kept_image_usd"])
        self.assertGreaterEqual(version["azure_all_in_cost_per_version_usd"], version["azure_variable_cost_per_version_usd"])
        self.assertLess(image["azure_all_in_cost_per_kept_image_usd"], image["avoided_baseline_cost_per_image_usd"])
        self.assertEqual(self.base["acr"]["expansion"]["enterprise_unit_economics"], ue)
        # existing tiers are unchanged by the new tier
        self.assertEqual([round(tiers[k]["acr_run_rate_usd"]) for k in ("pilot", "one_brand", "global_portfolio", "agency_network")], [20386, 101262, 514367, 2045195])

    def test_enterprise_and_reference_paths_add_up(self):
        for key in ("enterprise_path", "reference_customer_path"):
            steps = self.base["acr"]["expansion"][key]
            self.assertEqual(steps[0]["kind"], "total")
            self.assertEqual(steps[-1]["kind"], "total")
            self.assertAlmostEqual(steps[0]["acr_usd"] + sum(s["acr_usd"] for s in steps[1:-1]), steps[-1]["acr_usd"], delta=2.0)
            self.assertAlmostEqual(steps[-2]["cumulative_usd"], steps[-1]["acr_usd"], delta=2.0)
        self.assertEqual([s["id"] for s in self.base["acr"]["expansion"]["enterprise_path"]][1:-1], ["breadth", "e1", "e2", "e3", "e4"])

    def test_video_prices_come_from_the_retail_snapshot_and_availability_is_flagged(self):
        items = self.A["pricing"]["items"]
        self.assertLess(items["video_sora2_sec"]["price"], items["video_sora2_pro_hires_sec"]["price"])
        self.assertIn("deprecated in swedencentral", items["video_sora2_sec"]["note"])
        ref = self.base["acr"]["expansion"]["video_price_reference"]
        self.assertTrue(any(p["product"] == "Azure Fal" for p in ref), "partner video models from the Foundry catalog are shown as a reference")
        self.assertTrue(all(p["list_price_usd_per_second"] > 0 for p in ref))
        # a higher video price lifts only E1
        pricey = copy.deepcopy(self.A)
        pricey["pricing"]["items"]["video_sora2_pro_hires_sec"]["price"] = 1.0
        r = model.compute(pricey, "base", {"expansion_scale": 1})
        self.assertGreater(r["acr"]["by_lever"]["e1"][3], self.on["acr"]["by_lever"]["e1"][3])
        self.assertEqual(r["acr"]["by_lever"]["e2"], self.on["acr"]["by_lever"]["e2"])

    def test_scenario_summary_and_tam_expose_expansion(self):
        summary = model.compute_all(self.A)["meta"]["summary"]
        for s in model.SCENARIOS:
            for key in ("acr_by_lever_year3", "full_expansion_acr_by_year", "full_expansion_npv", "enterprise_tier_acr_run_rate_usd"):
                self.assertIn(key, summary[s])
        tam = self.base["acr"]["tam"]
        self.assertGreater(tam["expansion"]["annual_acr_ceiling_with_expansion_usd"], tam["annual_acr_ceiling_usd"])

    def test_lever_payback_helper(self):
        self.assertEqual(model._lever_payback([0, -100, 50, 100]), 30.0)
        self.assertEqual(model._lever_payback([0, 10, 20, 30]), 0.0)
        self.assertIsNone(model._lever_payback([0, -10, -5, -1]))


class OutputsParityTests(unittest.TestCase):
    def test_outputs_json_is_in_sync_with_assumptions(self):
        path = os.path.join(HERE, "outputs.json")
        self.assertTrue(os.path.exists(path), "run `python model.py` to create outputs.json")
        on_disk = json.loads(_read("outputs.json"))
        fresh = json.loads(json.dumps(model.compute_all(model.load_assumptions())))
        self.assertEqual(on_disk["meta"]["assumptions_sha256"], fresh["meta"]["assumptions_sha256"], "assumptions.json changed - re-run `python model.py`")
        self.assertEqual(on_disk, fresh)

    def test_markdown_report_renders(self):
        A = model.load_assumptions()
        md = model.render_markdown(model.compute_all(A), A)
        for needle in ("Scenario summary", "Azure Consumed Revenue by service family", "Sensitivity", "Assumption register", "Unit economics"):
            self.assertIn(needle, md)


if __name__ == "__main__":
    unittest.main(verbosity=2)
