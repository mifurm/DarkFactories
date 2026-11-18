"""Analytics maths (brief §5): auto-QA agreement on labelled transcripts, Erlang-B/C against exact reference values, forecast MAPE on a seeded seasonal
series, staffing that meets the SLA target in simulation, VoC clustering/anomaly detection, CX-metric reconciliation and ROI parity with outputs.json."""

from __future__ import annotations

import hashlib
import json
import math
import time
from collections import defaultdict
from fractions import Fraction
from pathlib import Path

import numpy as np
import pytest

from concierge.engine import metrics as mx
from concierge.engine import qa as qa_engine
from concierge.engine import synth, voc, wfm
from concierge.engine.models import Conversation
from concierge.features.metrics.business_case import model as roi_model
from concierge.features.qa.labelled import CASES, build_case

BC = Path(roi_model.__file__).parent


# ----------------------------------------------------------------------------------------------------------------- QA
def test_auto_qa_agrees_with_reference_scores_on_labelled_transcripts():
    pairs, per = [], defaultdict(list)
    evidence_total = evidence_found = 0
    for case in CASES:
        conv = build_case(case)
        res = qa_engine.rule_score(conv)
        text = " ".join(m.text.lower() for m in conv.messages)
        for d in qa_engine.DIMENSIONS:
            pairs.append((res["dimensions"][d], case["ref"][d]))
            per[d].append((res["dimensions"][d], case["ref"][d]))
        for e in res["evidence"]:
            if e.get("quote"):
                evidence_total += 1
                evidence_found += e["quote"].lower()[:60] in text
    overall = qa_engine.agreement(pairs)
    assert len(CASES) >= 12 and overall["n"] == len(CASES) * 7
    assert overall["within1_pct"] >= 90 and overall["kappa"] >= 0.6 and overall["mae"] <= 0.5, overall
    assert all(qa_engine.agreement(p)["within1_pct"] >= 80 for p in per.values()), {d: qa_engine.agreement(p) for d, p in per.items()}
    assert evidence_total and evidence_found == evidence_total, "every evidence snippet exists in the transcript"


def test_qa_auto_fail_rules_and_bands():
    by_name = {c["name"]: c for c in CASES}
    missing = qa_engine.rule_score(build_case(by_name["missing_disclosure"]))
    assert "missing_ai_disclosure" in [f["rule"] for f in missing["auto_fail"]] and missing["dimensions"]["compliance"] == 1
    risky = qa_engine.rule_score(build_case(by_name["risky_promise_delivered"]))
    assert "risky_promise" in [f["rule"] for f in risky["auto_fail"]]
    good = qa_engine.rule_score(build_case(by_name["excellent_ai_resolution"]))
    assert not good["auto_fail"] and qa_engine.band(qa_engine.overall_score(good["dimensions"]), False) in ("excellent", "good")
    assert qa_engine.band(99, True) == "fail" and qa_engine.band(86, False) == "excellent" and qa_engine.band(49, False) == "poor"
    assert qa_engine.overall_score({d: 5 for d in qa_engine.DIMENSIONS}) == 100.0 and sum(qa_engine.WEIGHTS.values()) == 100


def test_kappa_and_agreement_arithmetic():
    assert qa_engine.weighted_kappa([1, 2, 3, 4, 5], [1, 2, 3, 4, 5]) == 1.0
    assert qa_engine.weighted_kappa([1, 5, 1, 5], [5, 1, 5, 1]) < 0
    a = qa_engine.agreement([(5, 5), (4, 5), (2, 5)])
    assert (a["n"], a["exact_pct"], a["within1_pct"]) == (3, 33.3, 66.7) and a["mae"] == pytest.approx(1.333, abs=1e-3)


async def test_qa_scores_every_conversation_with_evidence(svc):
    from conftest import otp_of, say

    conv = await svc.orchestrator.start(language="en", recording_consent="granted")
    await say(svc, conv.id, "Hi, where is my order CH-100232?")
    await say(svc, conv.id, f"My code is {otp_of(await svc.store.get(conv.id))}")
    await say(svc, conv.id, "No thanks, that's all.")
    await svc.drain()
    c = await svc.store.get(conv.id)
    assert c.qa and c.qa["overall"] >= 60 and set(c.qa["dimensions"]) == set(qa_engine.DIMENSIONS)
    assert c.qa["band"] in ("excellent", "good", "needs_improvement") and c.qa["scorer"] == "rules" and c.wrapup["disposition"] == c.qa["disposition"]


# -------------------------------------------------------------------------------------------------------- Erlang-B / C
def exact_erlang_b(n: int, a: int | Fraction) -> Fraction:
    a = Fraction(a)
    terms = [a**k / math.factorial(k) for k in range(n + 1)]
    return terms[n] / sum(terms)


def exact_erlang_c(n: int, a: int | Fraction) -> Fraction:
    a = Fraction(a)
    top = a**n / math.factorial(n) * Fraction(n) / (n - a)
    return top / (sum(a**k / math.factorial(k) for k in range(n)) + top)


@pytest.mark.parametrize(("n", "a"), [(1, 1), (2, 1), (3, 2), (5, 3), (10, 7), (15, 10), (22, 20), (40, 35), (120, 100)])
def test_erlang_b_and_c_match_exact_rational_arithmetic(n, a):
    assert wfm.erlang_b(n, a) == pytest.approx(float(exact_erlang_b(n, a)), rel=1e-9)
    if n > a:
        assert wfm.erlang_c(n, a) == pytest.approx(float(exact_erlang_c(n, a)), rel=1e-9)


def test_erlang_textbook_values_and_service_level_formulas():
    assert wfm.erlang_b(2, 1) == pytest.approx(0.2) and wfm.erlang_b(3, 2) == pytest.approx(4 / 19)
    assert wfm.erlang_c(2, 1) == pytest.approx(1 / 3)
    assert wfm.erlang_c(5, 6) == 1.0 and wfm.erlang_c(0, 1) == 1.0, "an overloaded queue always waits"
    a, aht, t = 10.0, 180.0, 20.0
    expected_sl = 1 - float(exact_erlang_c(12, 10)) * math.exp(-(12 - 10) * t / aht)
    assert wfm.service_level(12, a, aht, t) == pytest.approx(expected_sl, rel=1e-9)
    assert wfm.asa(12, a, aht) == pytest.approx(float(exact_erlang_c(12, 10)) * aht / 2, rel=1e-9)
    assert wfm.service_level(10, a, aht, t) == 0.0 and math.isinf(wfm.asa(10, a, aht))


def test_agents_required_is_the_smallest_staffing_that_meets_sl_and_occupancy():
    calls, aht = 100, 180.0  # 100 calls in 30 minutes -> 10 erlangs
    n = wfm.agents_required(calls, aht, sl_target=0.8, t_s=20, max_occupancy=0.9)
    a = calls * aht / wfm.INTERVAL_S
    assert wfm.service_level(n, a, aht, 20) >= 0.8 and a / n <= 0.9
    assert not (wfm.service_level(n - 1, a, aht, 20) >= 0.8 and a / (n - 1) <= 0.9), "one agent fewer must violate the target"
    assert wfm.agents_required(0, aht) == 0
    assert wfm.agents_required(200, aht) > wfm.agents_required(100, aht) > wfm.agents_required(10, aht)


# --------------------------------------------------------------------------------------- forecast, staffing, simulation
@pytest.fixture(scope="module")
def history():
    hist = synth.generate_wfm_history(synth.anchor_midnight(time.time()))
    by_queue: dict[str, list[dict]] = defaultdict(list)
    for d in hist:
        by_queue[d["queue"]].append(d)
    return {q: sorted(v, key=lambda d: d["date"]) for q, v in by_queue.items()}


def test_synthetic_history_is_seeded_and_covers_five_queues_for_90_days(history):
    assert set(history) == {"general", "delivery", "returns", "warranty", "billing"} and all(len(v) == 90 for v in history.values())
    anchor = synth.anchor_midnight(time.time())
    again = synth.generate_wfm_history(anchor)
    assert [d["total"] for d in again if d["queue"] == "general"] == [d["total"] for d in history["general"]], "deterministic for a given anchor"
    assert any(d.get("event") for d in history["general"]), "promotion days exist for the event-uplift logic"
    assert all(len(d["intervals"]) == 48 for d in history["general"])


@pytest.mark.parametrize("queue", ["general", "delivery", "returns"])
def test_forecast_backtest_beats_seasonal_naive_and_meets_mape_target(history, queue):
    bt = wfm.backtest(history[queue])
    s = bt["summary"]
    assert len(bt["folds"]) >= 3
    assert s["hw"]["mape_daily"] < 0.10, s
    assert s["hw"]["wape_interval"] < s["naive"]["wape_interval"] and s["hw"]["mape_daily"] < s["naive"]["mape_daily"]
    assert bt["improvement_pct"] >= 15 and bt["improvement_daily_pct"] >= 10, bt["improvement_pct"]


def test_holt_winters_recovers_a_clean_weekly_season_with_trend():
    season = [100, 120, 130, 125, 140, 80, 60]
    y = [season[i % 7] + 0.5 * i for i in range(70)]
    fc, params = wfm.holt_winters(y, 7, 7)
    truth = [season[i % 7] + 0.5 * i for i in range(70, 77)]
    assert np.mean([abs(f - t) / t for f, t in zip(fc, truth, strict=True)]) < 0.03
    assert set(params) == {"alpha", "beta", "gamma", "phi"} and all(0 < v <= 1 for v in params.values())


def test_staffing_plan_covers_requirement_and_meets_the_sla_in_simulation(history):
    days = history["general"]
    fc = wfm.forecast_days(days, 7)
    for offset in (1, 3, 5):
        d = fc["days"][offset]
        plan = wfm.plan_day(d["intervals"], 420.0, containment=0.3, sl_target=0.8, t_s=120, shrinkage=0.15)
        sched = wfm.build_schedule(plan["agents_required"])
        assert not sched["uncovered_intervals"] and all(c >= r for c, r in zip(sched["coverage"], sched["requirement"], strict=True))
        seats = [round(c * (1 - 0.15)) for c in sched["coverage"]]
        sim = wfm.simulate(plan["human_volume"], seats, plan["aht_human_s"], 120)
        assert sim["sl_mean"] >= 0.80, (offset, sim["sl_mean"])
    low = wfm.plan_day(fc["days"][2]["intervals"], 420.0, containment=0.6)
    high = wfm.plan_day(fc["days"][2]["intervals"], 420.0, containment=0.0)
    assert low["totals"]["agent_hours_required"] < high["totals"]["agent_hours_required"], "containment what-if reduces human capacity needs"
    assert low["totals"]["peak_ai_sessions"] > 0


def test_simulation_detects_understaffing():
    expected = [30.0] * wfm.N_INT
    good = wfm.simulate(expected, [wfm.agents_required(30, 300.0) + 2] * wfm.N_INT, 300.0, 120, days=3)
    bad = wfm.simulate(expected, [5] * wfm.N_INT, 300.0, 120, days=3)
    assert good["sl_mean"] > 0.8 > bad["sl_mean"]


# ----------------------------------------------------------------------------------------------------------- VoC
@pytest.fixture(scope="module")
def voc_data():
    anchor = synth.anchor_midnight(time.time())
    recs = synth.generate_history(anchor)
    from concierge.core.ai.embedding import hashed_embedding

    vecs = np.array([hashed_embedding(r["summary"], 256) for r in recs], dtype=float)
    return recs, vecs, anchor


def test_synthetic_history_has_the_agreed_shape(voc_data):
    recs, _, _ = voc_data
    assert len(recs) >= 1500
    assert {r["market"] for r in recs} == {"UK", "DE", "FR", "ES", "IT", "NL", "PL", "PT"}, "eight markets"
    assert min(r["ts"] for r in recs) <= max(r["ts"] for r in recs) - 85 * 86400, "90 days of history"
    assert all({"qa_overall", "qa_dims", "sentiment_start", "sentiment_end", "topic", "disposition", "summary"} <= set(r) for r in recs)
    assert {r["channel"] for r in recs} >= {"voice", "chat"} or len({r["channel"] for r in recs}) >= 2


def test_voc_finds_the_planted_carrier_spike_and_no_alert_without_it(voc_data):
    recs, vecs, anchor = voc_data
    res = voc.build_voc(recs, vecs, as_of_ts=anchor)
    assert res["clusters"] and res["alerts"], "the injected damaged-on-delivery spike must be detected"
    top = res["alerts"][0]
    assert "NordFreight" in json.dumps(top) and top["severity"] in ("critical", "high")
    assert res["purity"] >= 0.8, "clusters recover the planted drivers"
    control = synth.generate_history(anchor, spike=False)
    cvecs = np.array([hashed_embedding_for(r) for r in control], dtype=float)
    assert not voc.build_voc(control, cvecs, as_of_ts=anchor)["alerts"], "no spike -> no alert (false-positive control)"


def hashed_embedding_for(r):
    from concierge.core.ai.embedding import hashed_embedding

    return hashed_embedding(r["summary"], 256)


def test_kmeans_and_purity_primitives():
    rng = np.random.default_rng(0)
    axes = np.eye(4)[:3]
    pts = np.vstack([axes[i] + rng.normal(0, 0.05, size=(30, 4)) for i in range(3)])
    labels, _, inertia = voc.kmeans(voc._normalise(pts), 3)
    truth = ["a"] * 30 + ["b"] * 30 + ["c"] * 30
    assert voc.purity(labels, truth) > 0.95 and inertia >= 0
    assert voc.purity([0, 0, 1, 1], ["x", "y", "x", "y"]) == 0.5


# ------------------------------------------------------------------------------------------- CX metrics & reconcile
def test_cx_metrics_reconcile_across_every_cut(voc_data):
    recs, _, _ = voc_data
    rs = [r for r in recs]
    overall = mx.kpis(rs)
    by_queue = mx.rollup(rs, lambda r: r.get("queue") or mx.queue_for_intent(r.get("intent")))
    by_hour = mx.rollup(rs, lambda r: time.gmtime(r["ts"]).tm_hour)
    by_day = mx.rollup(rs, lambda r: time.strftime("%Y-%m-%d", time.gmtime(r["ts"])))
    checks = mx.reconcile(rs, overall, by_queue, by_hour, by_day)
    assert checks and all(c["ok"] for c in checks), [c for c in checks if not c["ok"]]
    assert overall["contacts"] == len(rs) and 0 < overall["containment_pct"] < 100
    ai = mx.ai_vs_human(rs)
    assert ai["ai"]["cost_per_contact_usd"] < ai["human"]["cost_per_contact_usd"] / 10 and ai["cost_per_resolved_ratio"] > 10


# ------------------------------------------------------------------------------------------------------------- ROI
def test_roi_calculator_reproduces_the_business_case_outputs_within_half_a_percent():
    a = roi_model.load_assumptions(BC / "assumptions.json")
    out = json.loads((BC / "outputs.json").read_text())
    for scenario in ("conservative", "base", "upside"):
        got, ref = roi_model.compute(a, scenario), out["scenarios"][scenario]
        assert got["roi"]["npv"] == pytest.approx(ref["roi"]["npv"], rel=0.005)
        assert got["roi"]["roi_pct"] == pytest.approx(ref["roi"]["roi_pct"], rel=0.005)
        assert got["roi"]["payback_months"] == pytest.approx(ref["roi"]["payback_months"], rel=0.005)
        assert got["acr"]["run_rate_year3"] == pytest.approx(ref["acr"]["run_rate_year3"], rel=0.005)
    base = roi_model.compute(a, "base")
    assert {"scenario", "currency", "horizon_years", "inputs", "benefits", "costs", "roi", "acr", "sensitivity"} <= set(base)
    assert {"by_year", "by_family", "run_rate_year3", "tiers", "pull_through_ratio"} <= set(base["acr"])
    more_seats = roi_model.compute(a, "base", {"agents": 3000})
    assert more_seats["acr"]["run_rate_year3"] > base["acr"]["run_rate_year3"], "overrides recompute the model"
    with pytest.raises(KeyError):
        roi_model.compute(a, "base", {"not_an_assumption": 1})


def test_vendored_business_case_is_identical_to_the_docs_source():
    src = BC.parents[5] / "business-case" if len(BC.parents) > 5 else None
    if not src or not (src / "model.py").exists():
        pytest.skip("business-case/ is not part of this checkout (e.g. inside the container image)")
    for name in ("model.py", "assumptions.json", "outputs.json"):
        assert hashlib.sha256((BC / name).read_bytes()).hexdigest() == hashlib.sha256((src / name).read_bytes()).hexdigest(), f"{name} drifted from business-case/"


def test_conversation_fixture_helpers_do_not_leak():
    assert Conversation(id="x").messages == []
