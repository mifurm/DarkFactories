"""Unit tests for the business-case model (stdlib unittest): python -m unittest business-case/test_model.py -v"""
import copy
import json
import math
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import model  # noqa: E402
import refresh_prices  # noqa: E402

A = model.load_assumptions(HERE / "assumptions.json")
BASE = model.compute(A, "base")


def close(a, b, rel=1e-9, abs_=1e-6):
    return abs(a - b) <= max(abs_, rel * max(abs(a), abs(b)))


class TestAssumptionsFile(unittest.TestCase):
    def test_entries_are_complete_and_consistent(self):
        for key, e in A["assumptions"].items():
            with self.subTest(key=key):
                for field in ("label", "unit", "value", "base", "low", "high", "rationale", "source", "flag", "kind", "favourable"):
                    self.assertIn(field, e)
                self.assertEqual(e["value"], e["base"])
                self.assertIn(e["flag"], ("customer_input", "sourced", "assumption"))
                self.assertIn(e["kind"], ("customer_input", "outcome", "cost", "usage", "finance", "market"))
                self.assertIn(e["favourable"], ("high", "low", "neutral"))
                if isinstance(e["base"], list):
                    self.assertEqual(len(e["base"]), model.HORIZON if key != "opportunity_penetration_levels" else 3)
                    self.assertEqual(len(e["low"]), len(e["base"]))
                    self.assertEqual(len(e["high"]), len(e["base"]))
                elif isinstance(e["base"], (int, float)):
                    self.assertLessEqual(e["low"], e["high"])

    def test_every_unit_price_is_documented(self):
        for key, e in A["unit_prices"].items():
            with self.subTest(key=key):
                self.assertIn("label", e)
                self.assertIn("unit", e)
                self.assertTrue(("value" in e) or ("tiers" in e) or ("datazone" in e and "global" in e))
                self.assertTrue(e.get("source") or e.get("ref"))

    def test_unit_prices_match_the_api_snapshot(self):
        snap = json.loads((HERE / "pricing_snapshot.json").read_text(encoding="utf-8"))
        self.assertEqual(refresh_prices.verify_snapshot(A, snap), [])

    def test_datazone_costs_more_than_global(self):
        for key, e in A["unit_prices"].items():
            if "datazone" in e:
                self.assertGreaterEqual(e["datazone"], e["global"], key)


class TestInterfaceAndDeterminism(unittest.TestCase):
    def test_required_keys(self):
        r = BASE
        for k in ("scenario", "currency", "horizon_years", "inputs", "benefits", "costs", "roi", "acr", "sensitivity"):
            self.assertIn(k, r)
        self.assertEqual(r["scenario"], "base")
        self.assertEqual(r["currency"], "USD")
        self.assertEqual(r["horizon_years"], 3)
        for k in ("by_category", "total_by_year", "total"):
            self.assertIn(k, r["benefits"])
        for k in ("azure_by_family", "other_by_category", "total_by_year", "total"):
            self.assertIn(k, r["costs"])
        for k in ("net_benefit_by_year", "cumulative", "npv", "discount_rate", "roi_pct", "payback_months", "irr_pct"):
            self.assertIn(k, r["roi"])
        for k in ("by_year", "by_family", "run_rate_year3", "tiers", "pull_through_ratio"):
            self.assertIn(k, r["acr"])
        self.assertIsInstance(r["sensitivity"], list)
        self.assertEqual(set(r["acr"]["by_family"]), set(model.FAMILY_KEYS))
        self.assertEqual(len(r["acr"]["by_year"]), model.HORIZON + 1)
        self.assertEqual([t["seats"] for t in r["acr"]["tiers"]], [50, 500, 1500, 10000])

    def test_compute_all_has_three_scenarios(self):
        out = model.compute_all(A)
        self.assertEqual(list(out), ["conservative", "base", "upside"])
        for s, r in out.items():
            self.assertEqual(r["scenario"], s)

    def test_deterministic_and_pure(self):
        snapshot = copy.deepcopy(A)
        r1, r2 = model.compute(A, "base"), model.compute(A, "base")
        self.assertEqual(json.dumps(r1, sort_keys=True), json.dumps(r2, sort_keys=True))
        self.assertEqual(A, snapshot, "compute() must not mutate the assumptions")

    def test_outputs_json_is_current(self):
        stored = json.loads((HERE / "outputs.json").read_text(encoding="utf-8"))
        fresh = json.loads(json.dumps(model._round_tree(model.build_outputs(A))))
        self.assertEqual(stored, fresh, "outputs.json is stale - run: python model.py")

    def test_outputs_md_is_current(self):
        outputs = model._round_tree(model.build_outputs(A))
        self.assertEqual((HERE / "outputs.md").read_text(encoding="utf-8"), model.render_markdown(A, outputs))

    def test_reference_scenario_numbers_are_reproducible_within_half_a_percent(self):
        stored = json.loads((HERE / "outputs.json").read_text(encoding="utf-8"))["scenarios"]["base"]
        r = model.compute(A, "base")
        for path in (("roi", "npv"), ("roi", "roi_pct"), ("roi", "payback_months"), ("acr", "run_rate_year3")):
            a, b = r[path[0]][path[1]], stored[path[0]][path[1]]
            self.assertLessEqual(abs(a - b), 0.005 * abs(b), path)


class TestFinancialIdentities(unittest.TestCase):
    def test_benefit_and_cost_totals(self):
        b, c, roi = BASE["benefits"], BASE["costs"], BASE["roi"]
        for t in range(model.HORIZON + 1):
            self.assertTrue(close(sum(b["by_category"][k][t] for k in model.BENEFIT_KEYS), b["total_by_year"][t]))
            azure = sum(c["azure_by_family"][f][t] for f in model.FAMILY_KEYS)
            other = sum(c["other_by_category"][k][t] for k in model.OTHER_COST_KEYS)
            self.assertTrue(close(azure + other, c["total_by_year"][t]))
            self.assertTrue(close(b["total_by_year"][t] - c["total_by_year"][t], roi["net_benefit_by_year"][t]))
        self.assertTrue(close(sum(b["total_by_year"]), b["total"]))
        self.assertTrue(close(sum(c["total_by_year"]), c["total"]))
        self.assertTrue(close(sum(roi["net_benefit_by_year"]), roi["cumulative"][-1]))
        self.assertEqual(b["total_by_year"][0], 0.0)

    def test_npv_roi_and_irr_formulas(self):
        roi, r = BASE["roi"], BASE["roi"]["discount_rate"]
        manual = sum(cf / (1 + r) ** t for t, cf in enumerate(roi["net_benefit_by_year"]))
        self.assertTrue(close(manual, roi["npv"]))
        expected_roi = (BASE["benefits"]["total"] - BASE["costs"]["total"]) / BASE["costs"]["total"] * 100
        self.assertTrue(close(expected_roi, roi["roi_pct"]))
        irr = roi["irr_pct"] / 100.0
        self.assertLess(abs(model._npv(irr, roi["net_benefit_by_year"])), 1.0)

    def test_irr_helper_known_values(self):
        self.assertTrue(close(model._irr([-100.0, 110.0]), 0.10, abs_=1e-6))
        self.assertTrue(close(model._irr([-100.0, 0.0, 121.0]), 0.10, abs_=1e-6))
        self.assertIsNone(model._irr([100.0, 110.0]))
        self.assertIsNone(model._irr([-100.0, -10.0]))

    def test_payback_helper(self):
        self.assertEqual(model._payback_months(0.0, [1, 1, 1], [0, 0, 0]), 0.0)
        quick = model._payback_months(100.0, [600.0, 600.0, 600.0], [0.0, 0.0, 0.0])
        slow = model._payback_months(400.0, [600.0, 600.0, 600.0], [0.0, 0.0, 0.0])
        self.assertTrue(0 < quick < slow < 36)
        self.assertIsNone(model._payback_months(1e9, [1.0, 1.0, 1.0], [0.0, 0.0, 0.0]))
        # benefits ramp up inside the year, so payback is later than a flat-spread assumption would give
        flat = 12.0 * 100.0 / 600.0
        self.assertGreater(quick, flat)

    def test_payback_includes_implementation_months(self):
        roi = BASE["roi"]
        self.assertTrue(close(roi["payback_months"], roi["payback_months_from_go_live"] + roi["implementation_months"]))

    def test_cumulative_turns_positive_when_payback_inside_horizon(self):
        roi = BASE["roi"]
        self.assertLess(roi["payback_months_from_go_live"], 36)
        self.assertGreater(roi["cumulative"][-1], 0)


class TestScenarios(unittest.TestCase):
    def test_npv_orders_with_scenarios(self):
        npv = {s: model.compute(A, s)["roi"]["npv"] for s in model.ALL_SCENARIOS}
        self.assertLess(npv["stacked_downside"], npv["conservative"])
        self.assertLess(npv["conservative"], npv["base"])
        self.assertLess(npv["base"], npv["upside"])
        self.assertLess(npv["upside"], npv["stacked_upside"])
        self.assertGreater(npv["conservative"], 0, "the conservative case should still be positive")

    def test_acr_is_robust_across_scenarios(self):
        acr = {s: model.compute(A, s)["acr"]["run_rate_year3"] for s in model.SCENARIOS}
        self.assertLessEqual(acr["conservative"], acr["base"] * 1.0001)
        self.assertLess(abs(acr["upside"] - acr["base"]) / acr["base"], 0.15)

    def test_pick_blend_and_direction(self):
        e = {"kind": "outcome", "favourable": "high", "base": 10.0, "low": 6.0, "high": 20.0}
        self.assertEqual(model._pick(e, "base", 0.5), 10.0)
        self.assertEqual(model._pick(e, "conservative", 0.5), 8.0)
        self.assertEqual(model._pick(e, "upside", 0.5), 15.0)
        self.assertEqual(model._pick(e, "stacked_downside", 0.5), 6.0)
        cost = dict(e, kind="cost", favourable="low")
        self.assertEqual(model._pick(cost, "conservative", 0.5), 15.0)
        self.assertEqual(model._pick(cost, "upside", 0.5), 8.0)
        usage = dict(e, kind="usage")
        self.assertEqual(model._pick(usage, "conservative", 0.5), 10.0)
        ramp = {"kind": "outcome", "favourable": "high", "base": [0.2, 0.6], "low": [0.1, 0.4], "high": [0.3, 0.8]}
        self.assertEqual([round(v, 6) for v in model._pick(ramp, "conservative", 0.5)], [0.15, 0.5])

    def test_customer_facts_do_not_move_with_scenarios(self):
        c, u = model.compute(A, "conservative"), model.compute(A, "upside")
        for key in ("agents", "contacts_per_year", "attrition_rate", "loaded_cost_per_agent_usd", "rt_full_model_share"):
            self.assertEqual(c["inputs"]["assumptions"][key], u["inputs"]["assumptions"][key])


class TestOverrides(unittest.TestCase):
    def test_containment_override_moves_benefits_and_azure_mix(self):
        low = model.compute(A, "base", {"containment": 0.15})
        high = model.compute(A, "base", {"ai_containment_pct": 0.45})
        self.assertLess(low["roi"]["npv"], BASE["roi"]["npv"])
        self.assertGreater(high["roi"]["npv"], BASE["roi"]["npv"])
        self.assertGreater(high["acr"]["by_family"]["openai_realtime"][3], low["acr"]["by_family"]["openai_realtime"][3])

    def test_aliases(self):
        a = model.compute(A, "base", {"seats": 1800})
        b = model.compute(A, "base", {"agents": 1800})
        self.assertEqual(a["roi"]["npv"], b["roi"]["npv"])
        v = model.compute(A, "base", {"digital_share": 0.7})
        self.assertAlmostEqual(v["inputs"]["assumptions"]["voice_share_of_contacts"], 0.3)

    def test_cost_per_contact_override(self):
        r = model.compute(A, "base", {"cost_per_contact_usd": 8.01})
        self.assertAlmostEqual(r["inputs"]["derived"]["cost_per_contact_usd"], 8.01)
        self.assertGreater(r["roi"]["npv"], BASE["roi"]["npv"])
        self.assertAlmostEqual(r["inputs"]["derived"]["loaded_cost_per_agent_usd"] * 1500 / 18e6, 8.01)

    def test_ramp_override_and_validation(self):
        slow = model.compute(A, "base", {"adoption_ramp": [0.1, 0.3, 0.5]})
        self.assertLess(slow["roi"]["npv"], BASE["roi"]["npv"])
        with self.assertRaises(ValueError):
            model.compute(A, "base", {"adoption_ramp": [0.1, 0.3]})
        with self.assertRaises(ValueError):
            model.compute(A, "base", {"adoption_ramp": 0.5})
        with self.assertRaises(KeyError):
            model.compute(A, "base", {"not_a_driver": 1})
        with self.assertRaises(ValueError):
            model.compute(A, "bogus")

    def test_discount_rate_only_changes_npv(self):
        r = model.compute(A, "base", {"discount_rate": 0.2})
        self.assertLess(r["roi"]["npv"], BASE["roi"]["npv"])
        self.assertEqual(r["roi"]["roi_pct"], BASE["roi"]["roi_pct"])
        self.assertEqual(r["acr"]["run_rate_year3"], BASE["acr"]["run_rate_year3"])

    def test_overrides_do_not_leak(self):
        model.compute(A, "base", {"agents": 3000})
        self.assertEqual(model.compute(A, "base")["roi"]["npv"], BASE["roi"]["npv"])

    def test_tornado_uses_overrides_as_centre(self):
        r = model.compute(A, "base", {"containment": 0.2})
        top = r["sensitivity"][0]
        self.assertTrue(close(top["npv_at_high"] - top["delta_at_high"], r["roi"]["npv"]))


class TestAcrModel(unittest.TestCase):
    def test_family_and_line_item_totals_reconcile(self):
        acr = BASE["acr"]
        for t in range(model.HORIZON + 1):
            self.assertTrue(close(sum(acr["by_family"][f][t] for f in model.FAMILY_KEYS), acr["by_year"][t]))
        self.assertTrue(close(sum(i["azure_usd"] for i in acr["line_items_year3"]), acr["run_rate_year3"]))
        total_all = sum(i["usd"] for i in acr["line_items_year3"])
        self.assertTrue(close(total_all - acr["run_rate_year3"], acr["communications_outside_azure_by_year"][3]))
        for it in acr["line_items_year3"]:
            self.assertTrue(close(it["usd"], it["quantity"] * it["unit_price"] * it["factor"], rel=1e-9, abs_=1e-3), it["name"])

    def test_realtime_cost_per_minute_matches_hand_calculation(self):
        ov = {"rt_full_model_share": 0.0, "rt_fallback_pipeline_share": 0.0}
        r = model.compute(A, "base", ov)
        p, pr = r["inputs"]["assumptions"], model.resolve_prices(A, "datazone")
        items = [i for i in r["acr"]["line_items_year3"] if i["family"] == "openai_realtime"]
        minutes = r["volumes"]["ai_voice_minutes"][3]
        model_cost = sum(i["usd"] for i in items) / minutes
        new_in = 10 * 60 * p["rt_customer_speech_share"]
        new_out = 20 * 60 * p["rt_agent_speech_share"]
        manual = ((new_in + new_out) * pr["rt_mini_audio_in"] + new_out * pr["rt_mini_audio_out"]
                  + p["rt_turns_per_min"] * p["rt_avg_audio_context_tokens"] * pr["rt_mini_audio_cached"]
                  + p["rt_turns_per_min"] * p["rt_system_tokens"] * pr["rt_mini_text_cached"]
                  + p["rt_turns_per_min"] * p["rt_reasoning_tokens_per_turn"] * pr["rt_mini_text_out"]
                  + p["rt_tool_text_in_tokens_per_min"] * pr["rt_mini_text_in"]
                  + new_in * pr["transcribe_audio_in"] + p["speech_text_tokens_per_min"] * p["rt_customer_speech_share"] * pr["transcribe_text_out"]) / 1e6
        self.assertTrue(close(model_cost, manual, rel=1e-9), (model_cost, manual))
        self.assertTrue(0.01 < manual < 0.06, "gpt-realtime-2.1-mini should cost a few cents per minute")

    def test_global_deployment_is_cheaper_than_datazone(self):
        g = model.compute(A, "base", {"openai_deployment_type": "global"})
        self.assertLess(g["acr"]["run_rate_year3"], BASE["acr"]["run_rate_year3"])

    def test_communications_share_only_reclassifies_cost(self):
        full = model.compute(A, "base", {"comms_azure_billed_share": 1.0})
        self.assertGreater(full["acr"]["run_rate_year3"], BASE["acr"]["run_rate_year3"])
        self.assertTrue(close(full["costs"]["total"], BASE["costs"]["total"]))
        self.assertTrue(close(full["roi"]["npv"], BASE["roi"]["npv"]))
        self.assertTrue(close(full["acr"]["run_rate_year3"] - BASE["acr"]["run_rate_year3"], BASE["acr"]["communications_outside_azure_by_year"][3]))

    def test_usage_multiplier_scales_every_azure_line(self):
        r = model.compute(A, "base", {"azure_usage_multiplier": 2.0})
        self.assertTrue(close(r["acr"]["run_rate_year3"], 2 * BASE["acr"]["run_rate_year3"]))

    def test_tiers_scale_and_amortise_fixed_cost(self):
        tiers = BASE["acr"]["tiers"]
        totals = [t["annual_acr_usd"] for t in tiers]
        per_seat = [t["acr_per_seat_per_month_usd"] for t in tiers]
        self.assertEqual(totals, sorted(totals))
        self.assertEqual(per_seat, sorted(per_seat, reverse=True))
        ref = tiers[2]
        self.assertTrue(close(ref["annual_acr_usd"], BASE["acr"]["run_rate_year3"], rel=1e-6))

    def test_variable_lines_scale_with_volume_fixed_do_not(self):
        double = model.compute(A, "base", {"contacts_per_year": 36_000_000, "agents": 1500})
        a, b = BASE["acr"]["line_items_year3"], double["acr"]["line_items_year3"]
        for x, y in zip(a, b):
            if not x["fixed"] and x["family"] in ("openai_realtime", "content_safety"):
                self.assertTrue(close(y["quantity"], 2 * x["quantity"], rel=1e-9), x["name"])

    def test_language_tier_pricing(self):
        tiers = [(0, 1.0), (500, 0.75), (2500, 0.3), (10000, 0.25)]
        self.assertTrue(close(model._tiered_cost(tiers, 400_000), 400.0))
        self.assertTrue(close(model._tiered_cost(tiers, 1_000_000), 500 + 500 * 0.75))
        self.assertTrue(close(model._tiered_cost(tiers, 3_000_000), 500 + 2000 * 0.75 + 500 * 0.3))
        self.assertTrue(close(model._tiered_cost(tiers, 20_000_000), 500 + 2000 * 0.75 + 7500 * 0.3 + 10000 * 0.25))

    def test_capacity_sizing_ladder(self):
        self.assertEqual(model._next_in_ladder(1, model.FABRIC_CU_LADDER), 2)
        self.assertEqual(model._next_in_ladder(19.1, model.FABRIC_CU_LADDER), 32)
        self.assertEqual(model._next_in_ladder(10 ** 6, model.FABRIC_CU_LADDER), 2048)

    def test_pull_through_and_groups(self):
        acr = BASE["acr"]
        ai = sum(acr["by_group"]["ai"][3:])
        attach = sum(acr["by_group"][g][3] for g in ("comms", "data", "platform"))
        self.assertTrue(close(attach / ai, acr["pull_through_ratio"]))


class TestUnitEconomics(unittest.TestCase):
    def test_ai_is_cheaper_than_human_per_resolved_contact(self):
        ue = BASE["unit_economics"]
        self.assertLess(ue["all_in_ai_cost_per_resolved_contact_usd"], ue["human_cost_per_resolved_contact_usd"])
        self.assertGreater(ue["human_to_ai_cost_ratio_per_resolved_contact"], 2.0)
        self.assertLess(ue["azure_cost_per_voice_ai_minute_usd"], ue["platform_cost_per_voice_ai_minute_usd"])
        self.assertTrue(close(ue["human_cost_per_contact_usd"], 1500 * 67000 / 18e6))
        self.assertTrue(close(BASE["inputs"]["derived"]["baseline_annual_human_cost_usd"], 1500 * 67000))

    def test_implied_capacity_is_consistent_with_agents(self):
        d, p = BASE["inputs"]["derived"], BASE["inputs"]["assumptions"]
        minutes = p["contacts_per_year"] * d["weighted_aht_min"]
        productive_per_agent = 1800 * (1 - 0.30) * 0.82 * 60  # paid hours x (1 - shrinkage) x occupancy
        implied_agents = minutes / productive_per_agent
        self.assertLess(abs(implied_agents - p["agents"]) / p["agents"], 0.05)

    def test_benchmark_cross_check(self):
        # Gartner (2019 poll) reported $8.01 per live contact; the model's baseline must be below it (conservative)
        self.assertLess(BASE["unit_economics"]["human_cost_per_contact_usd"], 8.01)

    def test_year3_blended_reduction_is_below_gartner_30_percent_cost_reduction_claim(self):
        self.assertLess(BASE["unit_economics"]["blended_cost_reduction_pct"], 30.0)


class TestTornado(unittest.TestCase):
    def test_sorted_and_directional(self):
        rows = BASE["sensitivity"]
        swings = [r["swing"] for r in rows]
        self.assertEqual(swings, sorted(swings, reverse=True))
        by_key = {r["assumption"]: r for r in rows}
        self.assertGreater(by_key["ai_containment_pct"]["npv_at_high"], by_key["ai_containment_pct"]["npv_at_low"])
        self.assertGreater(by_key["azure_usage_multiplier"]["npv_at_low"], by_key["azure_usage_multiplier"]["npv_at_high"])
        self.assertNotIn("global_contact_center_agents", by_key)
        self.assertNotIn("comms_azure_billed_share", by_key, "reclassification does not change NPV")

    def test_top_driver_is_a_business_outcome(self):
        self.assertIn(BASE["sensitivity"][0]["assumption"], ("ai_containment_pct", "agents", "loaded_cost_per_agent_usd"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
