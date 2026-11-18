"""Agents (PdM, quality, planner, materials, energy, safety, process) and governance APIs (policy, inbox, ledger, RBAC)."""

from __future__ import annotations

import pytest

from conftest import step

ENG = {"X-Demo-Role": "engineer"}
OPERATOR = {"X-Demo-Role": "operator"}
AUDITOR = {"X-Demo-Role": "auditor"}
ADMIN = {"X-Demo-Role": "admin"}


# ----------------------------------------------------------------------------- maintenance
def test_pdm_health_signatures_series_and_work_orders(client):
    step(client, 30)
    h = client.get("/api/maintenance/health").json()
    assert len(h["assets"]) >= 10 and all("status" in a for a in h["assets"])
    assert any(a["ready"] for a in h["assets"]) and h["spares"] and h["windows"]
    sig = client.get("/api/maintenance/signatures").json()
    assert {s["name"] for s in sig} >= {"bearing_wear", "thermal_drift"}
    ser = client.get("/api/maintenance/series?asset=CNC-04&metric=vibration_rms&n=60").json()
    assert len(ser["values"]) == 60
    assert client.get("/api/maintenance/series?asset=NOPE").status_code == 404
    wo = client.post(
        "/api/maintenance/work-orders", json={"asset": "CNC-03", "start_in_min": 120, "reason": "api test"}
    )
    assert wo.status_code == 200, wo.text
    assert any(w["asset"] == "CNC-03" for w in client.get("/api/maintenance/work-orders").json())
    assert client.post("/api/maintenance/work-orders", json={"asset": "CNC-03", "start_in_min": -5}).status_code == 422
    assert client.post("/api/maintenance/work-orders", headers=OPERATOR, json={"asset": "CNC-03"}).status_code == 403


def test_bearing_fault_raises_an_alert_through_the_api(client):
    client.post("/api/sim/faults", json={"kind": "bearing_wear", "asset": "CNC-01", "params": {"ttf_h": 8}})
    for _ in range(14):
        step(client, 15)
        row = next(a for a in client.get("/api/maintenance/health").json()["assets"] if a["asset"] == "CNC-01")
        if row["alert"]:
            break
    assert row["alert"] and row["signature"]["name"] == "bearing_wear"
    for _ in range(6):
        step(client, 10)
        row = next(a for a in client.get("/api/maintenance/health").json()["assets"] if a["asset"] == "CNC-01")
        if row["rul_min"] is not None or not row["alert"]:
            break
    assert (
        row["rul_min"] is not None or not row["alert"]
    )  # an RUL estimate, or the planned repair already cleared the alert


# ----------------------------------------------------------------------------- quality + vision
def test_spc_summary_and_chart(client):
    s = client.get("/api/quality/summary").json()
    assert s["assets"] and {"asset", "cpk", "status"} <= set(s["assets"][0])
    chart = client.get("/api/quality/spc/CNC-04").json()
    assert chart["available"] and chart["limits"]["ucl"] > chart["limits"]["lcl"]
    assert client.get("/api/quality/spc/NOPE").status_code == 404


def test_quality_drift_is_detected_and_compensated(client):
    client.post(
        "/api/sim/faults",
        json={"kind": "quality_drift", "asset": "CNC-02", "params": {"magnitude_sigma": 3.5, "duration_h": 4}},
    )
    for _ in range(10):
        step(client, 15)
    q = client.get("/api/quality/summary").json()
    assert any(i["asset"] == "CNC-02" for i in q["interventions"])


def test_vision_batch_queue_review_and_stats(client):
    r = client.post("/api/quality/vision/batch", json={"n": 6, "seed": 3}).json()
    assert len(r["results"]) == 6 and r["stats"]["inspected"] >= 6
    first = r["results"][0]
    img = client.get(f"/api/quality/vision/image/{first['id']}")
    assert img.status_code == 200 and img.headers["content-type"] == "image/png" and img.content[:4] == b"\x89PNG"
    assert client.get("/api/quality/vision/image/IMG-nope").status_code == 404
    assert client.get("/api/quality/vision/queue").json()["stats"]["inspected"] >= 6
    assert client.get("/api/quality/vision/stats").json()["agreement"] is not None
    assert client.post("/api/quality/vision/batch", json={"n": 99}).status_code == 422
    queue = client.get("/api/quality/vision/queue").json()["items"]
    if queue:
        rv = client.post(f"/api/quality/vision/review/{queue[0]['id']}", json={"label": "ok"})
        assert rv.status_code == 200
    assert client.post("/api/quality/vision/review/IMG-nope", json={"label": "ok"}).status_code == 404


# ----------------------------------------------------------------------------- planner, materials, energy, safety, process
def test_planner_schedule_compare_explain_replan(client):
    s = client.get("/api/planner/schedule").json()
    assert s["slots"] and s["violations"] == [] and s["makespan_min"] > 0
    assert client.get("/api/planner/schedule?rule=bogus").status_code == 422
    c = client.get("/api/planner/compare").json()
    assert {"planner", "fifo", "improvement"} <= set(c)
    e = client.get("/api/planner/explain").json()
    assert e["summary"] and e["orders"]
    assert "plans" in client.post("/api/planner/replan").json()


def test_materials_summary_and_amr(client):
    m = client.get("/api/materials/summary").json()
    assert {i["material"] for i in m["inventory"]} >= {"BAR-AL", "RESIN-PA"} and m["amr"]
    assert all({"cover_min", "at_risk"} <= set(i["risk"]) for i in m["inventory"])
    assert "priority" in client.get("/api/materials/requests").json()


def test_supplier_delay_scenario_reaches_the_materials_agent(client):
    client.post("/api/sim/faults", json={"kind": "supplier_delay", "material": "RESIN-PA", "params": {"delay_h": 12}})
    for _ in range(8):
        step(client, 30)
    inv = {i["material"]: i for i in client.get("/api/materials/summary").json()["inventory"]}
    assert inv["RESIN-PA"]["on_order"] or inv["RESIN-PA"]["risk"]["at_risk"] or inv["RESIN-PA"]["on_hand"] > 0


def test_energy_summary_and_trend(client):
    e = client.get("/api/energy/summary").json()
    assert len(e["forecast"]) == 48 and e["plan"]["hi"] >= e["plan"]["lo"] and e["shifts"]
    assert len(client.get("/api/energy/trend").json()) > 10


def test_safety_summary_cyber_and_rule_checker(client):
    s = client.get("/api/safety/summary").json()
    assert len(s["zones"]) == 6 and s["rules"]["forbidden"]["speed_pct"]
    assert 0 <= client.get("/api/safety/cyber").json()["score"] <= 100
    deny = client.post(
        "/api/safety/check", json={"kind": "set_speed", "asset": "CNC-01", "params": {"pct": 240}}
    ).json()
    assert deny["allowed"] is False and deny["violations"][0]["rule"] == "forbidden_setpoint"
    ok = client.post("/api/safety/check", json={"kind": "set_speed", "asset": "CNC-01", "params": {"pct": 90}}).json()
    assert ok["allowed"] is True


def test_human_intrusion_triggers_protective_stop_and_restart(client):
    client.post("/api/sim/faults", json={"kind": "human_intrusion", "zone": "Z-MOLD", "params": {"duration_min": 10}})
    step(client, 3)
    z = next(z for z in client.get("/api/safety/summary").json()["zones"] if z["zone"] == "Z-MOLD")
    assert z["occupied"] or z["locked_out"]
    for _ in range(6):
        step(client, 10)
    z = next(z for z in client.get("/api/safety/summary").json()["zones"] if z["zone"] == "Z-MOLD")
    assert not z["occupied"]


def test_process_agent_is_disabled_by_default_and_can_be_enabled(client):
    s = client.get("/api/process/summary").json()
    assert s["enabled"] is False and s["bounds"]["melt_temp_c"]
    assert client.post("/api/process/enable", json={"enabled": True}).json()["enabled"] is True
    opt = client.post("/api/process/optimize").json()
    assert "history" in opt
    client.post("/api/process/enable", json={"enabled": False})


# ----------------------------------------------------------------------------- policy
def test_policy_read_matrix_evaluate(client):
    p = client.get("/api/policy").json()
    assert p["global_cap"] == 5 and len(p["classes"]) == 16 and p["protected_assets"]
    m = client.get("/api/policy/matrix?decision_class=maintenance.schedule&risk=0.2").json()
    assert m["outcome_by_level"]["L0"] == "observe" and m["outcome_by_level"]["L4"] == "auto_approve"
    assert client.get("/api/policy/matrix?decision_class=nope").status_code == 404
    ev = client.post(
        "/api/policy/evaluate",
        json={"decision_class": "maintenance.schedule", "risk": 0.9, "assets": 2, "cost_eur": 100},
    ).json()
    assert ev["outcome"] == "require_approval" and ev["reasons"]
    assert client.post("/api/policy/evaluate", json={"decision_class": "nope"}).status_code == 404


def test_policy_dial_rbac_and_ledger_audit(client):
    assert client.put("/api/policy/dial", headers=OPERATOR, json={"global_cap": 1}).status_code == 403
    assert client.put("/api/policy/dial", json={"levels": {"nope": 3}}).status_code in (404, 422)
    assert client.put("/api/policy/dial", json={"levels": {"energy.standby": 3}}).status_code == 200
    assert client.get("/api/policy").json()["levels"]["energy.standby"] == 3
    assert client.put("/api/policy/dial", json={"levels": {"energy.standby": 4}}).status_code == 200
    changes = client.get("/api/policy").json()["changes"]
    assert changes


def test_kill_switch_via_api_blocks_then_releases(client):
    assert client.post("/api/policy/kill", json={"on": True, "reason": "api test"}).status_code == 200
    p = client.get("/api/policy").json()
    assert p["kill_switch"] is True
    assert client.get("/api/tower/snapshot").json()["kill_switch"] is True
    assert (
        client.post("/api/policy/kill", headers=OPERATOR, json={"on": False}).status_code == 403
    )  # operators can pull it, not reset it
    assert client.post("/api/policy/kill", json={"on": False, "reason": "done"}).status_code == 200
    assert client.get("/api/policy").json()["kill_switch"] is False
    assert (
        client.post("/api/policy/kill", headers=OPERATOR, json={"on": True, "reason": "operator e-stop"}).status_code
        == 200
    )
    client.post("/api/policy/kill", json={"on": False})


def test_break_glass_and_timebox_require_reasons_and_expire(client):
    assert (
        client.post(
            "/api/policy/break-glass", json={"decision_class": "*", "level": 5, "minutes": 5, "reason": ""}
        ).status_code
        == 422
    )
    ok = client.post(
        "/api/policy/break-glass",
        json={
            "decision_class": "process.recipe",
            "level": 5,
            "minutes": 5,
            "reason": "plant trial approved by ops director",
        },
    )
    assert ok.status_code == 200
    assert client.get("/api/policy").json()["grants"]["break_glass"]
    tb = client.post(
        "/api/policy/timebox",
        json={"decision_class": "schedule.replan", "minutes": 30, "max_cost_eur": 500, "max_risk": 0.3},
    )
    assert tb.status_code == 200
    step(client, 360)  # grants expire with simulated time
    g = client.get("/api/policy").json()["grants"]
    assert not g["break_glass"] and not g["timeboxes"]


def test_policy_rules_roundtrip_and_validation(client):
    y = client.get("/api/policy/rules").json()["yaml"]
    assert "levels:" in y
    assert client.put("/api/policy/rules", json={"yaml_text": y}).status_code == 200
    assert client.put("/api/policy/rules", json={"yaml_text": "levels: [unclosed"}).status_code == 422
    assert (
        client.put("/api/policy/rules", json={"yaml_text": "version: 9\nclasses: {nope: {level: 9}}"}).status_code
        == 422
    )


# ----------------------------------------------------------------------------- inbox + ledger
def _propose_maintenance(client, asset: str):
    from nightshift.plant.models import Action, Proposal

    pr = client.app.state.rt.fleet.get("KAT-1")
    t = pr.plant.t
    prop = Proposal(
        agent="maintenance",
        decision_class="maintenance.schedule",
        title=f"test maintenance on {asset}",
        actions=[Action("schedule_maintenance", {"asset": asset, "start_t": t + 240, "duration": 45}, asset)],
        rationale="test",
        created_t=t,
        expires_t=t + 600,
        assets=[asset],
        risk=0.1,
    )
    return pr.supervisor.submit(prop)


@pytest.fixture()
def pending_item(client):
    client.put("/api/policy/dial", json={"levels": {"maintenance.schedule": 2}})
    _propose_maintenance(client, "CNC-05")
    items = [i for i in client.get("/api/inbox?status=pending").json()["items"] if i["status"] == "pending"]
    assert items, "approval did not land in the inbox"
    yield items[-1]
    client.put("/api/policy/dial", json={"levels": {"maintenance.schedule": 4}})


def test_inbox_item_lifecycle_approve(client, pending_item):
    assert pending_item["advisory"] is False and pending_item["assigned_role"] and pending_item["sla_min"] > 0
    card = client.get(f"/api/inbox/{pending_item['id']}/teams-card").json()
    assert card["type"] == "AdaptiveCard" and card["version"] == "1.4"
    assert (
        client.post(
            f"/api/inbox/{pending_item['id']}/resolve", headers=OPERATOR, json={"option": "approve"}
        ).status_code
        == 403
    )
    r = client.post(f"/api/inbox/{pending_item['id']}/resolve", json={"option": "approve", "comment": "ok to go"})
    assert r.status_code == 200 and r.json()["item"]["status"] == "approved"
    assert client.post(f"/api/inbox/{pending_item['id']}/resolve", json={"option": "approve"}).status_code in (404, 409)
    n = client.post(f"/api/inbox/{pending_item['id']}/notify")
    assert n.status_code in (200, 409)


def test_inbox_reject_and_expiry_fail_safe(client, pending_item):
    r = client.post(f"/api/inbox/{pending_item['id']}/resolve", json={"option": "reject", "comment": "not now"})
    assert r.json()["item"]["status"] == "rejected"
    assert client.get("/api/inbox/NOPE").status_code == 404
    client.put("/api/policy/dial", json={"levels": {"maintenance.schedule": 2}})
    plan = _propose_maintenance(client, "CNC-03")
    assert plan.status != "executed"
    before = {
        w["id"]
        for w in client.get("/api/maintenance/work-orders").json()
        if w["asset"] == "CNC-03" and "test maintenance" in w["reason"]
    }
    step(client, 400)  # nobody answers: SLA breach, escalation, then expiry with NOTHING executed
    st = client.get("/api/inbox").json()["stats"]
    assert st["expired"] >= 1 and st["escalations"] >= 1
    after = {
        w["id"]
        for w in client.get("/api/maintenance/work-orders").json()
        if w["asset"] == "CNC-03" and "test maintenance" in w["reason"]
    }
    assert after == before


def test_ledger_query_verify_export_stats_and_rbac(client):
    led = client.get("/api/ledger?limit=5").json()
    assert led["total"] > 10 and len(led["items"]) == 5
    seq = led["items"][0]["seq"]
    assert client.get(f"/api/ledger/{seq}").json()["entry"]["seq"] == seq
    assert client.get("/api/ledger/99999999").status_code == 404
    assert client.get("/api/ledger?kind=decision&limit=3").json()["items"][0]["kind"] == "decision"
    assert client.get("/api/ledger?q=maintenance&limit=3").json()["total"] >= 1
    assert client.get("/api/ledger/verify").json()["ok"] is True
    assert client.get("/api/ledger/stats").json()["entries"] > 10
    assert client.get("/api/ledger/export", headers=OPERATOR).status_code == 403
    exp = client.get("/api/ledger/export", headers=AUDITOR)
    assert exp.status_code == 200 and exp.text.splitlines()[0].startswith("{")
    ex = client.post("/api/ledger/explain", json={"seq": seq}).json()
    assert ex["text"]
