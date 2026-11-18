"""Behavioural tests from the brief: seeded scenarios, guardrails, A/B evidence, planner, energy, vision, ROI parity."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nightshift.features.df04_swarm.core import WorldView
from nightshift.features.df06_quality.vision import LABELS, classify_with_model, generate_part_image
from nightshift.features.df07_planner.scheduler import build_schedule, check_feasibility
from nightshift.features.df21_value.ab import ABConfig, run_ab, run_arm
from nightshift.plant.core import PlantCore
from nightshift.plant.models import Action, Proposal
from nightshift.sim.plant import ActionRejected

BC = Path(__file__).resolve().parents[1] / "src/nightshift/features/df21_value/business_case"


def proposal(core: PlantCore, cls: str, actions: list[Action], agent: str = "maintenance", **kw) -> Proposal:
    t = core.plant.t
    return Proposal(
        agent=agent,
        decision_class=cls,
        title=kw.pop("title", "test proposal"),
        actions=actions,
        rationale="test",
        created_t=t,
        expires_t=t + 120,
        assets=kw.pop("assets", [a.target for a in actions if a.target]),
        risk=kw.pop("risk", 0.1),
        **kw,
    )


# ----------------------------------------------------------------------------- bearing wear narrative
def _first_failure(core: PlantCore, asset: str) -> int | None:
    for ev in core.event_log:
        if ev["kind"] == "failure" and ev.get("asset") == asset:
            return ev["t"]
    return None


@pytest.fixture(scope="module")
def bearing_story():
    """Same seed, same injected bearing fault: baseline (run-to-failure) vs swarm, observed for the same span."""
    out = {}
    t_end = None
    for name, swarm in (("base", False), ("swarm", True)):
        c = PlantCore("KAT-1", seed=5, swarm=swarm, sim_first="surrogate", headless_latency=20)
        c.run(180)
        t_inject = c.plant.t
        c.plant.inject_fault("bearing_wear", asset="CNC-04", ttf_h=10)
        alert_t = None
        while True:
            c.run(5)
            if swarm and alert_t is None:
                v = c.pdm.models["CNC-04"].view
                if v.get("alert") and v.get("rul_min"):
                    alert_t = c.plant.t
            if swarm:
                if c.plant.t >= t_end:
                    break
            else:
                t_fail = _first_failure(c, "CNC-04")
                if (t_fail is not None and c.plant.t > t_fail + 240) or c.plant.t > t_inject + 3000:
                    t_end = c.plant.t
                    break
        out[name] = {"core": c, "t_inject": t_inject, "alert_t": alert_t}
    return out


def test_bearing_wear_baseline_breaks_down(bearing_story):
    base = bearing_story["base"]
    assert base["core"].plant.assets["CNC-04"].failures >= 1
    assert _first_failure(base["core"], "CNC-04") is not None


def test_pdm_alerts_well_before_the_failure(bearing_story):
    t_fail = _first_failure(bearing_story["base"]["core"], "CNC-04")
    alert_t = bearing_story["swarm"]["alert_t"]
    assert alert_t is not None, "PdM never raised an alert"
    lead = t_fail - alert_t
    assert lead >= 120, f"alert only {lead} sim-min before the failure"
    assert alert_t - bearing_story["swarm"]["t_inject"] <= 300


def test_planned_maintenance_avoids_the_breakdown(bearing_story):
    swarm = bearing_story["swarm"]["core"]
    a = swarm.plant.assets["CNC-04"]
    assert a.failures == 0
    wos = [w for w in swarm.plant.work_orders.values() if w.asset == "CNC-04"]
    assert wos and wos[0].status == "done"
    assert swarm.plant.acc["downtime_unplanned_min"] < bearing_story["base"]["core"].plant.acc["downtime_unplanned_min"]


def test_ledger_documents_the_story_with_a_valid_chain(bearing_story):
    led = bearing_story["swarm"]["core"].ledger
    v = led.verify()
    assert v["ok"] and v["length"] > 10
    kinds = {e["kind"] for e in led.query(limit=500)["items"]}
    assert {"proposal", "decision", "action"} <= kinds
    maint = [e for e in led.query(limit=500, asset="CNC-04")["items"] if "aintenance" in e["summary"]]
    assert maint, "no maintenance entry for CNC-04"


def test_ledger_tamper_is_detected(bearing_story):
    led = bearing_story["swarm"]["core"].ledger
    victim = led._entries[len(led._entries) // 2]
    original = victim["summary"]
    victim["summary"] = original + " (edited)"
    try:
        v = led.verify()
        assert not v["ok"] and v["broken_at"] == victim["seq"]
    finally:
        victim["summary"] = original
    assert led.verify()["ok"]


# ----------------------------------------------------------------------------- guardrails
def test_safety_veto_beats_the_planner(core):
    core.plant.inject_fault("human_intrusion", zone="Z-MACH-A", duration_min=30)
    core.run(2)
    assert WorldView(core.plant).zone_state("Z-MACH-A")[0] > 0
    asset = "CNC-01"
    plan = core.supervisor.submit(
        proposal(core, "schedule.replan", [Action("set_speed", {"asset": asset, "pct": 90}, asset)], agent="planner")
    )
    assert plan.status == "vetoed"
    assert core.plant.assets[asset].speed != 90
    veto = [e for e in core.ledger.query(limit=100, kind="veto")["items"] if asset in e["assets"]]
    assert veto and "zone_occupied" in veto[0]["rationale"]


def test_kill_switch_halts_every_autonomous_action(core):
    core.policy.set_kill_switch(True, "unit test", "tester", core.plant.t)
    plan = core.supervisor.submit(
        proposal(
            core,
            "maintenance.schedule",
            [
                Action(
                    "schedule_maintenance", {"asset": "CNC-01", "start_t": core.plant.t + 60, "duration": 45}, "CNC-01"
                )
            ],
        )
    )
    assert plan.status == "denied"
    assert plan.decision["policy"]["reasons"][0].startswith("kill switch")
    assert not core.plant.work_orders
    executed_before = core.supervisor.stats["executed"]
    core.run(120)  # the swarm keeps proposing but nothing executes
    assert core.supervisor.stats["executed"] == executed_before
    stop = core.supervisor.submit(
        proposal(
            core,
            "safety.protective_stop",
            [Action("safe_stop", {"asset": "CNC-02"}, "CNC-02")],
            agent="safety",
            risk=0.0,
        )
    )
    assert stop.status == "executed" and core.plant.assets["CNC-02"].safe_stop
    core.policy.set_kill_switch(False, "", "tester", core.plant.t)
    assert not core.policy.kill_switch


@pytest.mark.parametrize(
    ("cls", "risk", "assets", "cost", "expected"),
    [
        (
            "maintenance.schedule",
            0.2,
            1,
            300,
            ["observe", "recommend", "require_approval", "auto_approve", "auto_approve", "auto_approve"],
        ),
        (
            "maintenance.schedule",
            0.5,
            3,
            2000,
            ["observe", "recommend", "require_approval", "require_approval", "auto_approve", "auto_approve"],
        ),
        (
            "maintenance.schedule",
            0.9,
            12,
            90000,
            ["observe", "recommend", "require_approval", "require_approval", "require_approval", "require_approval"],
        ),
    ],
)
def test_autonomy_level_matrix(core, cls, risk, assets, cost, expected):
    m = core.policy.matrix(cls, risk, assets, cost, core.plant.t)
    assert [m[f"L{i}"] for i in range(6)] == expected


def test_lowering_the_dial_changes_what_executes(core):
    core.policy.set_level("maintenance.schedule", 2, "tester", core.plant.t)  # approve-all
    plan = core.supervisor.submit(
        proposal(
            core,
            "maintenance.schedule",
            [
                Action(
                    "schedule_maintenance", {"asset": "CNC-03", "start_t": core.plant.t + 90, "duration": 45}, "CNC-03"
                )
            ],
        )
    )
    assert plan.status in ("pending_approval", "awaiting_approval") or core.inbox.pending()
    assert not core.plant.work_orders  # nothing ran without a human
    item = core.inbox.pending()[0]
    res = core.supervisor.resolve(item.id, "approve", "tester:plant_manager")
    assert res["item"]["status"] == "approved" and res["executed"] is not None
    assert core.plant.work_orders


def test_forbidden_setpoints_are_rejected_everywhere(core):
    with pytest.raises(ActionRejected):
        core.plant.apply({"kind": "set_speed", "asset": "CNC-01", "pct": 240})
    with pytest.raises(ActionRejected):
        core.plant.apply({"kind": "set_setpoint", "asset": "CNC-01", "name": "offset_comp", "value": 9.0})
    plan = core.supervisor.submit(
        proposal(
            core, "setpoint.adjust", [Action("set_speed", {"asset": "CNC-01", "pct": 240}, "CNC-01")], agent="quality"
        )
    )
    assert plan.status == "vetoed"
    assert core.plant.assets["CNC-01"].speed != 240


# ----------------------------------------------------------------------------- A/B evidence
@pytest.fixture(scope="module")
def ab():
    return run_ab(ABConfig())


def test_ab_runs_fast_and_uses_at_least_ten_seeds(ab):
    assert len(ab["seeds"]) >= 10
    assert ab["elapsed_s"] < 30


@pytest.mark.parametrize("metric", ["downtime_h", "late_orders", "oee"])
def test_ab_primary_metrics_are_significantly_better(ab, metric):
    m = ab["metrics"][metric]
    assert m["improvement"] > 0
    assert m["ci_low"] > 0, f"{metric}: 95 % CI includes 0"
    assert m["p_one_sided"] < 0.05


def test_ab_tardiness_and_total_loss_improve(ab):
    assert ab["metrics"]["tardiness_h"]["improvement"] > 0 and ab["metrics"]["tardiness_h"]["p_one_sided"] < 0.05
    assert ab["metrics"]["loss_eur"]["improvement"] > 0 and ab["metrics"]["loss_eur"]["p_one_sided"] < 0.05


def test_ab_energy_effective_price_is_lower_and_absolute_cost_is_reported_honestly(ab):
    price = ab["metrics"]["energy_price_eur_kwh"]
    assert price["improvement"] > 0 and price["ci_low"] > 0
    cost = ab["metrics"]["energy_cost_eur"]
    assert cost["off_mean"] > 0 and "improvement" in cost  # reported whether or not it is positive


def test_ab_is_deterministic():
    cfg = ABConfig(seeds=[101, 102], horizon_h=4)
    a, b = run_ab(cfg), run_ab(cfg)
    assert [r["on"]["loss_eur"] for r in a["rows"]] == [r["on"]["loss_eur"] for r in b["rows"]]


# ----------------------------------------------------------------------------- planner and energy
def test_planner_replan_meets_more_due_dates_than_fifo_after_a_breakdown():
    cfg = ABConfig(window="late")
    faults = [
        (30, "jam", {"asset": "CNC-02", "duration_min": 240}),
        (60, "rush_order", {"sku": "SHF-200", "qty": 80, "due_in_h": 9.0}),
    ]
    seeds = range(101, 109)
    fifo = [run_arm(cfg, s, False, faults=faults) for s in seeds]
    plan = [run_arm(cfg, s, True, agents={"planner", "safety"}, faults=faults) for s in seeds]
    late_fifo = sum(r["late_orders"] for r in fifo)
    late_plan = sum(r["late_orders"] for r in plan)
    assert late_plan < late_fifo
    assert sum(r["tardiness_h"] for r in plan) < sum(r["tardiness_h"] for r in fifo)


def test_planner_schedule_is_feasible_without_capacity_overlaps(core):
    core.plant.inject_fault("jam", asset="CNC-02", duration_min=120)
    core.run(10)
    sched = build_schedule(WorldView(core.plant), "cr")
    assert sched.slots and not check_feasibility(sched, WorldView(core.plant))
    by_machine: dict[str, list] = {}
    for s in sched.slots:
        by_machine.setdefault(s.asset, []).append(s)
    for slots in by_machine.values():
        slots.sort(key=lambda s: s.start)
        for a, b in zip(slots, slots[1:], strict=False):
            assert a.end <= b.start + 1e-6, f"{a.order}/{b.order} overlap on {a.asset}"
    for s in sched.slots:  # routing precedence: an op never starts before its predecessor ended
        prev = [x for x in sched.slots if x.order == s.order and x.idx == s.idx - 1]
        assert all(p.end <= s.end + 1e-6 for p in prev)


def test_energy_agent_shifts_load_without_hurting_due_dates():
    cfg = ABConfig(window="late")
    spike = [(10, "power_price_spike", {"multiplier": 2.8, "duration_h": 3.0})]
    seeds = range(101, 109)
    base = [run_arm(cfg, s, False, faults=spike) for s in seeds]
    eco = [run_arm(cfg, s, True, agents={"energy", "safety"}, faults=spike) for s in seeds]
    assert sum(1 for b, e in zip(base, eco, strict=True) if e["energy_price_eur_kwh"] < b["energy_price_eur_kwh"]) >= 7
    assert sum(r["energy_cost_eur"] for r in eco) <= sum(r["energy_cost_eur"] for r in base)
    assert sum(r["late_orders"] for r in eco) <= sum(r["late_orders"] for r in base)


# ----------------------------------------------------------------------------- vision (stub in unit tests)
async def test_vision_stub_agrees_with_the_known_defect_above_threshold():
    from nightshift.core.llm import StubLLM

    llm = StubLLM()
    labels = [lab for lab in LABELS for _ in range(5)]
    hits = 0
    for i, truth in enumerate(labels):
        png = generate_part_image(1000 + i, None if truth == "ok" else truth)
        res = await classify_with_model(llm, png)
        hits += res["label"] == truth
    assert hits / len(labels) >= 0.8


# ----------------------------------------------------------------------------- ROI calculator parity
def _assert_same(ours, theirs, path="$", rel=0.005):
    """Whole-document comparison: same keys / lengths / strings, numbers within `rel` (0.5 %)."""
    if isinstance(theirs, dict):
        assert isinstance(ours, dict) and ours.keys() == theirs.keys(), f"{path}: keys differ"
        for k, v in theirs.items():
            _assert_same(ours[k], v, f"{path}.{k}", rel)
    elif isinstance(theirs, list):
        assert isinstance(ours, list) and len(ours) == len(theirs), f"{path}: length differs"
        for i, (a, b) in enumerate(zip(ours, theirs, strict=True)):
            _assert_same(a, b, f"{path}[{i}]", rel)
    elif isinstance(theirs, bool) or theirs is None or isinstance(theirs, str):
        assert ours == theirs, f"{path}: {ours!r} != {theirs!r}"
    else:
        assert ours == pytest.approx(theirs, rel=rel, abs=1e-6), f"{path}: {ours} != {theirs}"


def test_roi_calculator_reproduces_outputs_json_whole_document_within_half_a_percent():
    from nightshift.features.df21_value.business_case import model

    ref = json.loads((BC / "outputs.json").read_text())
    ours = model.compute_all(model.load_assumptions())
    assert set(ref["scenarios"]) == {"conservative", "base", "upside"}
    _assert_same(json.loads(json.dumps(ours)), ref)


def test_vendored_business_case_files_are_one_consistent_version():
    from nightshift.features.df21_value.business_case import model

    ref = json.loads((BC / "outputs.json").read_text())
    assumptions = json.loads((BC / "assumptions.json").read_text())
    assert model.MODEL_VERSION == ref["model_version"] == "1.1.0"
    assert assumptions["meta"]["assumptions_version"] == ref["assumptions_version"]
    source = Path(__file__).resolve().parents[2] / "business-case"
    if source.exists():  # in the repository checkout the vendored trio must be byte-identical to the docs agent's files
        for name in ("model.py", "assumptions.json", "outputs.json"):
            assert (source / name).read_bytes() == (BC / name).read_bytes(), f"{name} drifted from business-case/"
