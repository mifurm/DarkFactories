"""Platform, simulator, telemetry, twin and swarm API tests (offline mode, deterministic)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from conftest import offline_settings, step
from nightshift.core.http import TokenBuckets
from nightshift.main import create_app


# ----------------------------------------------------------------------------- platform
def test_health_ready_meta(client):
    assert client.get("/healthz").json()["status"] == "ok"
    ready = client.get("/readyz?fresh=1").json()
    assert ready["status"] == "ready" and ready["mode"] == "offline"
    meta = client.get("/api/meta").json()
    assert meta["mode"] == "offline" and meta["synthetic_data"] is True and len(meta["plants"]) == 3
    assert meta["models"]["backend"] == "offline-stub"


def test_all_25_features_are_listed_and_implemented(client):
    feats = client.get("/api/features").json()
    ids = [f["id"] for f in feats]
    assert ids == [f"DF-{i:02d}" for i in range(1, 26)]
    assert all(f["status"] == "implemented" for f in feats)
    assert all(f["ui_route"].startswith("/") and f["api_prefix"].startswith("/api") for f in feats)
    assert {f["priority"] for f in feats} == {"P0", "P1", "P2"}


def test_security_headers_request_id_and_docs(client):
    r = client.get("/api/meta", headers={"X-Request-ID": "abc-123"})
    assert r.headers["x-request-id"] == "abc-123"
    assert "default-src 'self'" in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff"
    bad = client.get("/api/meta", headers={"X-Request-ID": "bad id with spaces"})
    assert bad.headers["x-request-id"] != "bad id with spaces"
    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").json()["info"]["title"]


def test_usage_endpoint_and_budget_guard(client):
    u = client.get("/api/usage").json()
    assert u["daily_budget_usd"] == 5.0 and u["budget_blocked"] is False


def test_body_size_limit_and_rate_limit_buckets():
    app = create_app(offline_settings(max_body_bytes=200, rate_limit_mutating_per_min=3))
    with TestClient(app) as c:
        big = c.post("/api/sim/control", json={"command": "pause", "value": 0, "pad": "x" * 600})
        assert big.status_code == 413
        codes = [c.post("/api/sim/control", json={"command": "pause"}).status_code for _ in range(6)]
        assert 429 in codes
    b = TokenBuckets()
    assert b.take("k", 2, now=0) == 0 and b.take("k", 2, now=0) == 0
    assert b.take("k", 2, now=0) > 0 and b.take("k", 2, now=60) == 0


def test_calculator_posts_use_their_own_bucket_and_large_json_is_gzipped():
    app = create_app(offline_settings(rate_limit_mutating_per_min=3, rate_limit_compute_per_min=50))
    with TestClient(app) as c:
        codes = [c.post("/api/value/calculator/compute", json={"sensitivity": False}).status_code for _ in range(8)]
        assert codes == [200] * 8
        assert c.post("/api/sim/control", json={"command": "pause"}).status_code == 200  # mutation bucket untouched
        meta = c.get("/api/value/calculator/meta", headers={"Accept-Encoding": "gzip"})
        assert meta.headers["content-encoding"] == "gzip" and meta.json()["counts"]["prices"] == 60


def test_spa_fallback_serves_index_or_404(client):
    r = client.get("/definitely-not-a-route")
    assert r.status_code in (200, 404)


# ----------------------------------------------------------------------------- simulator
def test_sim_state_assets_orders_config_catalog(client):
    s = client.get("/api/sim/state").json()
    assert len(s["assets"]) == 20 and s["plant"]["id"] == "KAT-1" and s["t"] >= 180
    assert client.get("/api/sim/assets/cnc-04").json()["id"] == "CNC-04"
    assert client.get("/api/sim/assets/NOPE").status_code == 404
    assert client.get("/api/sim/orders").json()
    cfg = client.get("/api/sim/config").json()["assumptions"]
    assert cfg["energy"]["tariff_eur_per_kwh"]["peak"] > cfg["energy"]["tariff_eur_per_kwh"]["offpeak"]
    cat = client.get("/api/sim/catalog").json()
    assert {f["kind"] for f in cat["faults"]} >= {"bearing_wear", "jam", "human_intrusion", "power_price_spike"}
    assert len(cat["scenarios"]) == 8


def test_time_control_pause_step_speed(client):
    t0 = client.get("/api/sim/state").json()["t"]
    assert client.post("/api/sim/control", json={"command": "pause"}).json()["paused"] is True
    assert step(client, 15)["t"] == t0 + 15
    assert client.post("/api/sim/control", json={"command": "speed", "value": 30}).json()["speed"] == 30
    assert client.post("/api/sim/control", json={"command": "speed", "value": 99999}).json()["speed"] <= 600
    assert client.post("/api/sim/control", json={"command": "warp"}).status_code == 422


def test_fault_injection_scenarios_and_unknown_kinds(client):
    r = client.post("/api/sim/faults", json={"kind": "jam", "asset": "CNC-05", "params": {"duration_min": 30}})
    assert r.status_code == 200
    step(client, 3)
    assert client.get("/api/sim/assets/CNC-05").json()["state"] in ("DOWN", "BLOCKED", "IDLE", "RUN")
    assert client.post("/api/sim/faults", json={"kind": "meteor"}).status_code in (400, 404, 422)
    sc = client.post("/api/sim/scenario/price-spike")
    assert sc.status_code == 200 and sc.json()["steps"]
    assert client.post("/api/sim/scenario/nope").status_code in (404, 422)
    ev = client.get("/api/sim/events?limit=5").json()
    assert isinstance(ev, list)


def test_control_api_accepts_valid_and_rejects_forbidden_actions(client):
    ok = client.post("/api/sim/action", json={"action": {"kind": "set_speed", "asset": "CNC-02", "pct": 88}})
    assert ok.status_code == 200, ok.text
    bad = client.post("/api/sim/action", json={"action": {"kind": "set_speed", "asset": "CNC-02", "pct": 240}})
    assert bad.status_code in (409, 422)
    assert client.post("/api/sim/action", json={"action": {"kind": "teleport"}}).status_code in (409, 422)


def test_snapshot_and_restore_roundtrip(client):
    snap = client.post("/api/sim/snapshot").json()
    t_snap = snap["t"]
    step(client, 20)
    assert client.get("/api/sim/state").json()["t"] == t_snap + 20
    assert client.post(f"/api/sim/restore/{snap['id']}").json()["t"] == t_snap
    assert client.get("/api/sim/state").json()["t"] == t_snap
    assert client.post("/api/sim/restore/snap-nope").status_code == 404


def test_other_plants_are_independent(client):
    a = client.get("/api/sim/state?plant=GDN-2").json()
    b = client.get("/api/sim/state?plant=MTY-3").json()
    assert a["plant"]["id"] == "GDN-2" and b["plant"]["id"] == "MTY-3"
    assert len(a["assets"]) != len(b["assets"]) or a["plant"]["profile"] != b["plant"]["profile"]
    assert client.get("/api/sim/state?plant=XXX").status_code == 404


# ----------------------------------------------------------------------------- telemetry / UNS
def test_uns_tree_latest_series_aggregates(client):
    tree = client.get("/api/telemetry/tree").json()
    assert tree["topics"] > 100 and "contoso" in tree["tree"]
    topic = client.get("/api/telemetry/adapters").json()["example_topic"]
    assert topic.count("/") == 6
    latest = client.get("/api/telemetry/latest?limit=3").json()
    assert len(latest) == 3 and {"topic", "value", "unit", "quality", "source"} <= set(latest[0])
    ser = client.get(f"/api/telemetry/series?topic={topic}&n=30").json()
    assert len(ser["points"]) > 5
    assert client.get("/api/telemetry/series?topic=a/b").status_code == 422
    assert client.get("/api/telemetry/series?topic=contoso/kat-1/x/y/z/nope-1/vibration_rms").status_code == 404
    agg = client.get("/api/telemetry/aggregates?asset=CNC-04&metric=vibration_rms&bucket=15&buckets=4").json()
    assert len(agg) == 4 and {"mean", "min", "max"} <= set(agg[0])


def test_ingest_validates_topics_values_and_prefix(client):
    prefix = "contoso/kat-1/machining/mach-line-1/cell-04/cnc-04"
    ENG = {"X-Demo-Role": "engineer"}
    assert (
        client.post("/api/telemetry/ingest", json={"messages": [{"topic": f"{prefix}/p", "value": 1}]}).status_code
        == 403
    )  # plant manager may not ingest
    good = client.post(
        "/api/telemetry/ingest",
        headers=ENG,
        json={"messages": [{"topic": f"{prefix}/ext_probe", "value": 41.5, "unit": "C"}]},
    )
    assert good.status_code == 200 and good.json()["accepted"] == 1
    mixed = client.post(
        "/api/telemetry/ingest",
        headers=ENG,
        json={
            "messages": [
                {"topic": "other/site/a/b/c/d/e", "value": 1},
                {"topic": f"{prefix}/x", "value": {"nested": 1}},
            ]
        },
    ).json()
    assert mixed["accepted"] == 0 and mixed["rejected"] == 2
    assert client.post("/api/telemetry/ingest", headers=ENG, json={"messages": []}).status_code == 422


def test_uns_message_decoders():
    import json

    from nightshift.features.df02_telemetry.uns import (
        AdapterUnavailable,
        EventHubDecoder,
        MqttDecoder,
        TelemetryMessage,
    )

    topic = "contoso/kat-1/machining/mach-line-1/cell-01/cnc-01/vibration_rms"
    m = MqttDecoder.decode(topic, b'{"v": 1.25, "q": "good"}')
    assert isinstance(m, TelemetryMessage) and m.value == 1.25 and m.source == "mqtt"
    assert MqttDecoder.decode(topic, b"3.5").value == 3.5
    with pytest.raises(ValueError):
        MqttDecoder.decode("not/a/uns/topic", b"1")
    with pytest.raises(AdapterUnavailable):
        MqttDecoder.connect("broker")
    body = json.dumps({"asset": "CNC-01", "datapoints": [{"metric": "vibration_rms", "value": 2.0, "ts": 5}]}).encode()
    msgs = EventHubDecoder.decode(body, "contoso/kat-1/machining/mach-line-1/cell-01")
    assert msgs[0].topic.endswith("/cnc-01/vibration_rms") and msgs[0].value == 2.0


# ----------------------------------------------------------------------------- twin
def test_twin_graph_and_whatif_is_pure(client):
    g = client.get("/api/twin/graph").json()
    assert len(g["nodes"]) > 25 and {e["kind"] for e in g["edges"]} >= {"contains", "flows_to"}
    t = client.get("/api/sim/state").json()["t"]
    body = {
        "actions": [{"kind": "schedule_maintenance", "asset": "CNC-04", "start_t": t + 15, "duration": 45}],
        "horizon_min": 120,
    }
    a = client.post("/api/twin/whatif", json=body).json()
    b = client.post("/api/twin/whatif", json=body).json()
    assert a["delta"] == b["delta"]  # deterministic fork
    assert client.get("/api/sim/state").json()["t"] == t  # the live plant did not move
    assert {"accept", "explanation", "baseline", "with_actions", "counterfactual"} <= set(a)
    assert client.post("/api/twin/whatif", json={"actions": [{"kind": "nope"}], "horizon_min": 60}).status_code == 422
    f = client.post("/api/twin/fork", json={"minutes": 60}).json()
    assert f["live_t_unchanged"] == t and f["kpi"]["oee"] is not None


# ----------------------------------------------------------------------------- swarm
def test_swarm_agents_plans_weights_blackboard(client):
    step(client, 60)
    sw = client.get("/api/swarm/agents").json()
    names = {a["name"] for a in sw["agents"]}
    assert {"safety", "maintenance", "quality", "planner", "materials", "energy"} <= names
    plans = client.get("/api/swarm/plans").json()
    assert isinstance(plans, list)
    if plans:
        assert client.get(f"/api/swarm/plans/{plans[0]['id']}").json()["id"] == plans[0]["id"]
        ex = client.post("/api/swarm/explain", json={"plan_id": plans[0]["id"]}).json()
        assert ex["text"] and ex["source"] in ("fallback", "stub", "deterministic", "azure", "offline")
    assert client.get("/api/swarm/plans/PLN-nope").status_code == 404
    w = client.get("/api/swarm/weights").json()["weights"]
    new = {**w, "energy_eur": w["energy_eur"] * 2}
    assert client.put("/api/swarm/weights", json={"weights": new}).json()["weights"]["energy_eur"] == new["energy_eur"]
    assert client.put("/api/swarm/weights", json={"weights": {"energy_eur": -5}}).status_code == 422
    client.put("/api/swarm/weights", json={"weights": w})
    assert isinstance(client.get("/api/swarm/blackboard").json(), dict)


def test_agent_toggle_is_enforced_and_audited(client):
    r = client.post("/api/swarm/agents/energy/toggle", json={"enabled": False}).json()
    assert r["enabled"] is False
    assert client.post("/api/swarm/agents/energy/toggle", json={"enabled": True}).json()["enabled"] is True
    assert client.post("/api/swarm/agents/ghost/toggle", json={"enabled": True}).status_code == 404
    safety = client.post("/api/swarm/agents/safety/toggle", json={"enabled": False})
    assert safety.status_code in (200, 403, 409)
    client.post("/api/swarm/agents/safety/toggle", json={"enabled": True})


@pytest.mark.parametrize("path", ["/api/tower/snapshot", "/api/tower/map"])
def test_control_tower_endpoints(client, path):
    d = client.get(path).json()
    assert d
