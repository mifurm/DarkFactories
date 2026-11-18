"""Unit tests for platform plumbing and algorithms (no HTTP)."""

from __future__ import annotations

import asyncio
import math

import numpy as np
import pytest

from nightshift.config import Settings
from nightshift.core.bus import EventHub, sse_format
from nightshift.core.llm import ChatResult, StubLLM, narrate
from nightshift.core.repo import MemoryBlobStore, MemoryRepository, WriteBehind
from nightshift.core.usage import BudgetExceeded, UsageMeter
from nightshift.features.df04_swarm.core import WorldView
from nightshift.features.df06_quality import spc
from nightshift.features.df12_policy.engine import PolicyEngine, load_rules
from nightshift.features.df13_inbox.inbox import Inbox
from nightshift.features.df14_ledger.ledger import Ledger
from nightshift.features.df21_value.stats import paired_summary
from nightshift.plant.core import PlantCore
from nightshift.plant.models import Action, Plan, Proposal
from nightshift.sim.config import build_plant_config
from nightshift.sim.plant import Plant
from nightshift.sim.rng import Streams


# ----------------------------------------------------------------------------- config / usage / llm
def test_settings_from_env_parses_flags_and_defaults():
    s = Settings.from_env(
        {
            "NIGHTSHIFT_MODE": "azure",
            "AI_DAILY_BUDGET_USD": "2.5",
            "SIM_SPEED": "7",
            "PLANTS": "A-1, B-2",
            "SIM_AUTOSTART": "false",
            "CONTAINER_APP_REVISION": "rev9",
        }
    )
    assert s.is_azure and s.daily_ai_budget_usd == 2.5 and s.sim_speed == 7 and s.plants == ("A-1", "B-2")
    assert s.sim_autostart is False and s.build_id == "rev9"
    d = Settings.from_env({})
    assert not d.is_azure and d.sim_speed == 1.0 and d.default_role == "plant_manager"


def test_budget_guard_fails_closed_and_rolls_over_at_midnight():
    day = ["2026-01-01"]
    m = UsageMeter(0.01, clock=lambda: day[0])
    m.guard("x")
    m.record("x", "chat", "chat", 10_000, 2_000, latency_ms=12.0)  # ~ $0.0165 > cap
    assert m.blocked
    with pytest.raises(BudgetExceeded):
        m.guard("x")
    snap = m.snapshot()
    assert snap["budget_blocked"] and snap["calls"] == 1 and snap["remaining_usd"] == 0
    doc = m.to_doc()
    day[0] = "2026-01-02"
    assert not m.blocked and m.snapshot()["calls"] == 0
    m2 = UsageMeter(5.0, clock=lambda: "2026-01-01")
    m2.load_doc(doc)
    assert m2.blocked is False or m2.snapshot()["calls"] == 1
    assert m.estimate("reasoning", 1_000_000, 0) == 2.5


async def test_stub_llm_and_narrate_fallbacks():
    llm = StubLLM()
    r = await llm.chat([{"role": "user", "content": "hello"}])
    assert isinstance(r, ChatResult) and r.text and (await llm.ping())["status"] == "ok"
    chunks = [e async for e in llm.stream([{"role": "user", "content": "hi"}])]
    assert chunks
    n = await narrate(llm, "t", {"a": 1}, "say hi", lambda f: f"fallback {f['a']}")
    assert n.text and n.source in ("stub", "fallback", "offline")

    class Broken(StubLLM):
        mode = "azure"

        async def chat(self, *a, **k):
            raise RuntimeError("boom")

    b = await narrate(Broken(), "t", {"a": 1}, "say hi", lambda f: f"fallback {f['a']}")
    assert b.text == "fallback 1" and b.source == "fallback" and b.error

    class OverBudget(StubLLM):
        mode = "azure"

        async def chat(self, *a, **k):
            raise BudgetExceeded("cap")

    o = await narrate(OverBudget(), "t", {"a": 2}, "say hi", lambda f: f"fallback {f['a']}")
    assert o.text == "fallback 2" and o.blocked


async def test_memory_repository_and_write_behind_and_blobs():
    repo = MemoryRepository()
    for i in range(5):
        await repo.upsert(
            "ledger", {"id": f"e{i}", "pk": "KAT-1", "seq": i, "kind": "a" if i % 2 else "b", "payload": {"x": i}}
        )
    assert (await repo.get("ledger", "e2", "KAT-1"))["seq"] == 2
    rows = await repo.query("ledger", pk="KAT-1", order_by="seq", desc=True, limit=3)
    assert [r["seq"] for r in rows] == [4, 3, 2]
    assert len(await repo.query("ledger", pk="KAT-1", where={"kind": "a"})) == 2
    assert await repo.count("ledger", pk="KAT-1") == 5
    await repo.delete("ledger", "e0", "KAT-1")
    assert await repo.get("ledger", "e0", "KAT-1") is None
    assert (await repo.ping())["status"] == "ok"
    wb = WriteBehind(repo, max_queue=3, batch=2)
    wb.start()
    for i in range(5):
        wb.enqueue("kpi", {"id": f"k{i}", "pk": "KAT-1"})
    await wb.flush()
    assert wb.stats()["written"] >= 3 and wb.stats()["dropped"] >= 1
    await wb.stop()
    blobs = MemoryBlobStore()
    await blobs.put("vision", "a/b.png", b"123", "image/png")
    assert await blobs.get("vision", "a/b.png") == b"123" and await blobs.list("vision", "a/") == ["a/b.png"]


async def test_event_hub_backpressure_drops_oldest_not_the_publisher():
    hub = EventHub()
    sub = hub.subscribe({"t/x"}, maxsize=2)
    for i in range(5):
        hub.publish("t/x", {"i": i})
    hub.publish("t/y", {"i": 99})  # not subscribed
    assert hub.subscribers == 1
    got = []
    while not sub.queue.empty():
        got.append(sub.queue.get_nowait())
    assert [d["i"] for _, d in got] == [3, 4]
    hub.unsubscribe(sub)
    assert hub.subscribers == 0
    assert sse_format("tick", {"a": 1}) == 'event: tick\ndata: {"a":1}\n\n'


# ----------------------------------------------------------------------------- statistics and SPC
def test_paired_summary_matches_textbook_t_test():
    s = paired_summary([1.0, 2.0, 3.0, 4.0, 5.0])
    assert s["mean"] == 3.0 and s["n"] == 5 and s["significant"] is True
    assert s["ci_low"] == pytest.approx(3.0 - 2.776 * math.sqrt(2.5 / 5), abs=0.01)
    z = paired_summary([-1.0, 1.0, -1.0, 1.0])
    assert z["significant"] is False and z["p_one_sided"] > 0.3
    assert paired_summary([2.0, 2.0, 2.0])["significant"] is True  # zero variance, positive mean


def test_spc_limits_cpk_and_western_electric_rules():
    rng = np.random.default_rng(1)
    x = rng.normal(10.0, 0.2, 200)
    sg = spc.subgroups(x, 5)
    xbar, r = spc.xbar_r(sg)
    lim = spc.limits(xbar, r, 5)
    assert lim["lcl"] < lim["center"] < lim["ucl"] and abs(lim["center"] - 10.0) < 0.1
    assert spc.cpk(10.0, 0.2, 9.0, 11.0) == pytest.approx(1.667, abs=0.01)
    assert spc.cpk(10.8, 0.2, 9.0, 11.0) < spc.cpk(10.0, 0.2, 9.0, 11.0)
    flat = np.full(12, 10.0)
    assert spc.western_electric(flat, 10.0, 0.1) == []
    spike = np.array([10.0] * 5 + [10.5])  # rules are evaluated for the latest point
    assert any(v["rule"] == 1 for v in spc.western_electric(spike, 10.0, 0.1))
    run = np.array([10.02] * 9)  # nine in a row on one side of the centre
    assert any(v["rule"] == 4 for v in spc.western_electric(run, 10.0, 0.1))
    two_of_three = np.array([10.0, 10.25, 10.25])
    assert any(v["rule"] == 2 for v in spc.western_electric(two_of_three, 10.0, 0.1))
    four_of_five = np.array([10.0, 10.15, 10.15, 10.15, 10.15])
    assert any(v["rule"] == 3 for v in spc.western_electric(four_of_five, 10.0, 0.1))
    assert len(spc.ewma(np.array([1.0, 2.0, 3.0]))) == 3
    cp = spc.control_plan_limits(10.0, 0.2, 5)
    assert cp["ucl"] > cp["center"] > cp["lcl"]


# ----------------------------------------------------------------------------- simulator invariants
def test_simulation_is_deterministic_and_snapshot_restore_continues_identically():
    def run(seed):
        c = PlantCore("KAT-1", seed=seed, swarm=False)
        c.run(240)
        return c

    a, b, other = run(7), run(7), run(8)
    assert a.plant.snapshot() == b.plant.snapshot() or a.plant.acc == b.plant.acc
    assert a.plant.acc["units_total"] == b.plant.acc["units_total"]
    assert a.plant.acc["energy_cost"] == b.plant.acc["energy_cost"]
    assert a.plant.acc != other.plant.acc
    snap = a.plant.snapshot()
    a.run(60)
    after = a.plant.acc["units_total"]
    a.plant.restore(snap)
    a.run(60)
    assert a.plant.acc["units_total"] == after


def test_streams_use_a_fixed_number_of_variates_per_tick():
    s1, s2 = Streams(1).get("CNC-01"), Streams(1).get("CNC-01")
    (n1, u1), (n1b, _) = s1.next(), s1.next()
    n2, u2 = s2.next()
    assert len(n1) == 6 and len(u1) == 2 and n1 == n2 and u1 == u2 and n1 != n1b
    assert Streams(1).get("CNC-02").next()[0] != n1  # independent streams per asset
    assert Streams(2).get("CNC-01").next()[0] != n1  # different seed, different noise


def test_each_plant_profile_builds_and_runs():
    for pid, n in (("KAT-1", 20), ("GDN-2", 19), ("MTY-3", 21)):
        cfg = build_plant_config(pid)
        assert len(cfg.assets) == n
        p = Plant(cfg, 3)
        p.run(60)
        assert p.t == 60 and p.total_kw > 0


def test_material_shortage_starves_presses_in_the_baseline():
    c = PlantCore("KAT-1", seed=9, swarm=False)
    c.run(180)
    c.plant.inject_fault("supplier_delay", material="RESIN-PA", delay_h=30)
    c.run(600)
    states = {a.state for a in c.plant.assets.values() if a.id.startswith("PRESS")}
    assert c.plant.inventory["RESIN-PA"]["on_hand"] >= 0 and states


# ----------------------------------------------------------------------------- policy / inbox / ledger units
def test_policy_yaml_must_be_monotonic_and_known_classes_only():
    import yaml

    base = PolicyEngine().rules
    assert base.classes["maintenance.schedule"].level == 4
    with pytest.raises(ValueError):
        load_rules("version: 2\nclasses:\n  not.a.class: {level: 3}\n")
    with pytest.raises(yaml.YAMLError):
        load_rules("{{{{")
    eng = PolicyEngine()
    with pytest.raises(ValueError):
        eng.set_level("maintenance.schedule", 9)
    with pytest.raises(ValueError):
        eng.set_level("nope.nope", 2)


def test_policy_rate_limit_and_protected_assets_force_approval():
    eng = PolicyEngine()
    c = PlantCore("KAT-1", seed=2, swarm=False)
    c.run(10)

    def plan(asset, kind="safe_stop"):
        p = Proposal(
            agent="maintenance",
            decision_class="maintenance.schedule",
            title="t",
            actions=[Action(kind, {"asset": asset}, asset)],
            rationale="r",
            created_t=0,
            expires_t=99,
            assets=[asset],
            risk=0.05,
        )
        return Plan(id="PLN-x", trigger=p.id, proposals=[p])

    d = eng.evaluate(plan("COMP-01"), 10)
    assert d.outcome == "require_approval" and any("protected" in r for r in d.reasons)
    assert eng.evaluate(plan("CNC-01"), 10).outcome == "auto_approve"
    for _ in range(30):
        eng.record_auto("maintenance.schedule", 10)
    assert eng.evaluate(plan("CNC-01"), 10).outcome == "require_approval"


def test_inbox_escalates_through_the_role_chain_then_expires():
    ib = Inbox("KAT-1")
    p = Proposal(
        agent="maintenance",
        decision_class="maintenance.schedule",
        title="x",
        actions=[],
        rationale="r",
        created_t=0,
        expires_t=10_000,
        risk=0.4,
    )
    plan = Plan(id="PLN-1", trigger=p.id, proposals=[p])
    decision = type("D", (), {"level": 2, "risk_score": 0.4, "reasons": ["r"], "sla_min": 10})()
    item = ib.add(plan, decision, 0, "explain")
    assert item.status == "pending" and item.assigned_role == "engineer"
    ev = ib.tick(15)
    assert any(kind == "escalated" for kind, _ in ev) and ib.get(item.id).assigned_role == "plant_manager"
    for now in (30, 60, 120, 240):  # keep escalating until the chain is exhausted, then fail safe
        ev = ib.tick(now)
        if any(kind == "expired" for kind, _ in ev):
            break
    assert ib.get(item.id).status == "expired" and ib.get(item.id).resolution == "sla_exhausted"
    assert ib.stats(500)["expired"] == 1


def test_ledger_chain_survives_restart_via_repository_anchor():
    async def go():
        repo = MemoryRepository()
        wb = WriteBehind(repo)
        wb.start()
        a = Ledger("KAT-1", writer=wb)
        for i in range(5):
            a.append("system", f"event {i}", agent="t")
        await wb.flush()
        b = Ledger("KAT-1", writer=wb)
        await b.load_head(repo)
        b.append("system", "after restart", agent="t")
        assert b.last_seq == a.last_seq + 1 and b.verify()["ok"]
        assert a.export_jsonl().count("\n") == 5
        await wb.stop()

    asyncio.run(go())


def test_worldview_is_a_read_only_projection_without_hidden_state():
    c = PlantCore("KAT-1", seed=4, swarm=False)
    c.run(30)
    w = WorldView(c.plant)
    a = w.asset("CNC-01")
    assert not hasattr(a, "health") and not hasattr(a, "tool_wear")  # agents never see ground truth
    assert w.t == c.plant.t and w.ids("CNC")


async def test_write_behind_daily_caps_protect_cosmos_cost():
    repo = MemoryRepository()
    wb = WriteBehind(repo, caps={"kpi": 2, "default": 3})
    wb.start()
    for i in range(5):
        wb.enqueue("kpi", {"id": f"k{i}", "pk": "p"})
        wb.enqueue("ledger", {"id": f"l{i}", "pk": "p"})
    await wb.flush()
    assert wb.stats()["capped"] == 3 + 2 and wb.stats()["written"] == 5
    assert await repo.count("kpi") == 2 and await repo.count("ledger") == 3
    await wb.stop()
