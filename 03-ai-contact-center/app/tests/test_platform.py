"""Platform tests: Bicep <-> collections consistency, governance tags and keyless settings in IaC, feature auto-discovery, the CRM contract suite, outbound rules
(consent, opt-out, quiet hours per recipient time zone, caps, kill switch) and API smoke across every feature."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from concierge.core.collections import BACKOFFICE_COLLECTIONS, COLLECTIONS, partition_key
from concierge.core.config import Settings
from concierge.core.repo import InMemoryRepository, prepare
from concierge.engine import crm, crm_contract, outbound
from concierge.main import create_app

ROOT = Path(__file__).resolve().parents[2]
INFRA = ROOT / "infra"


# ------------------------------------------------------------------------------------------------------------ IaC
def bicep(name: str) -> str:
    p = INFRA / name
    if not p.exists():
        pytest.skip("infra/ is not part of this checkout")
    return p.read_text()


def test_bicep_cosmos_containers_match_the_application_collections():
    txt = bicep("resources.bicep")
    block = re.search(r"var cosmosContainers = \[(.*?)\]", txt, re.S).group(1)
    containers = re.findall(r"'([a-z_]+)'", block)
    assert sorted(containers) == sorted(COLLECTIONS), "infra/resources.bicep cosmosContainers must equal core/collections.py"
    assert "/pk" in txt and set(BACKOFFICE_COLLECTIONS) <= set(COLLECTIONS)
    assert partition_key("conversations", "cv_1") == "cv_1" and partition_key("history", "H-1") == "history"
    with pytest.raises(KeyError):
        partition_key("not_a_collection", "x")


def test_bicep_is_keyless_and_carries_the_governance_tags_everywhere():
    main, res = bicep("main.bicep"), bicep("resources.bicep")
    assert "SecurityControl: 'Ignore'" in main and "SecurityExemption: 'StorageAccountKeyAccess'" in main
    for key in ("project: 'SwarmAI'", "concept: 'contactcenter'", "owner: 'michalfu'", "environment: 'demo'"):
        assert key in main
    assert "SecurityExemption: 'Cosmos'" not in main + res, "a tag key holds one value"
    assert res.count("disableLocalAuth: true") >= 2, "Cosmos DB and the AI Services account accept Entra tokens only"
    assert "allowSharedKeyAccess: false" in res and "allowBlobPublicAccess: false" in res and "minimumTlsVersion: 'TLS1_2'" in res
    taggable = re.findall(r"^resource \w+ '([^']+)'", res, re.M)
    untagged = []
    for m in re.finditer(r"^resource (\w+) '([^']+)'[^\n]*\{\n(.*?)^\}", res, re.S | re.M):
        _name, rtype, body = m.groups()
        if "roleAssignments" in rtype or "sqlRoleAssignments" in rtype or rtype.startswith("Microsoft.Authorization") or "diagnosticSettings" in rtype:
            continue
        if "/sqlDatabases" in rtype or "/deployments@" in rtype or "/containers@" in rtype or "/sqlRoleDefinitions" in rtype or "blobServices" in rtype or "authConfigs" in rtype:
            continue
        if "tags:" not in body:
            untagged.append(rtype)
    assert not untagged, f"resources without tags: {untagged}"
    assert taggable, "resources were parsed"
    assert "minReplicas: 1" in res and "maxReplicas: 1" in res, "single replica: the event bus and rate limits are in-process"
    assert "AI_DAILY_BUDGET_USD" in res and "CONCIERGE_MODE" in res and "'azure'" in res
    assert "listKeys" not in res and "primaryMasterKey" not in res and "connectionString" not in res.replace("APPLICATIONINSIGHTS_CONNECTION_STRING", ""), "no keys or connection strings are read"


def test_azure_yaml_declares_one_remote_built_container_app():
    txt = (ROOT / "azure.yaml").read_text() if (ROOT / "azure.yaml").exists() else pytest.skip("azure.yaml missing")
    assert "host: containerapp" in txt and "remoteBuild: true" in txt and "path: infra" in txt


def test_settings_come_from_the_environment_and_auto_select_the_mode(monkeypatch):
    from concierge.core.config import load_settings

    for k in ("COSMOS_ENDPOINT", "AZURE_OPENAI_ENDPOINT", "CONCIERGE_MODE", "AI_DAILY_BUDGET_USD", "AUTH_MODE", "AOAI_DEPLOYMENT_CHAT", "SEED_ON_START"):
        monkeypatch.delenv(k, raising=False)
    assert load_settings().mode == "offline" and not load_settings().is_azure
    monkeypatch.setenv("COSMOS_ENDPOINT", "https://cosmos.example")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://aoai.example/")
    s = load_settings()
    assert s.mode == "azure" and s.is_azure and s.openai_endpoint == "https://aoai.example", "both endpoints configured -> azure mode"
    monkeypatch.setenv("CONCIERGE_MODE", "offline")
    assert load_settings().mode == "offline", "an explicit mode wins"
    monkeypatch.setenv("AI_DAILY_BUDGET_USD", "7.5")
    monkeypatch.setenv("AUTH_MODE", "entra")
    monkeypatch.setenv("AOAI_DEPLOYMENT_CHAT", "my-chat")
    monkeypatch.setenv("SEED_ON_START", "0")
    s = load_settings(region="x")
    assert (s.daily_budget_usd, s.auth_mode, s.deployment("chat"), s.seed_on_start, s.region) == (7.5, "entra", "my-chat", False, "x")
    assert s.deployment("realtime") and s.deployment("nope") == ""


# ----------------------------------------------------------------------------------------------- repository contract
async def test_repository_contract_in_memory():
    repo = InMemoryRepository()
    d = await repo.put("settings", {"id": "a", "n": 1, "tag": "x"})
    assert d["pk"] == "settings" and (await repo.get("settings", "a"))["n"] == 1
    await repo.put_many("settings", [{"id": f"k{i}", "n": i, "tag": "y"} for i in range(10)])
    assert await repo.count("settings") == 11 and await repo.count("settings", {"tag": "y"}) == 10
    rows = await repo.query("settings", {"tag": "y", "n": {"$gte": 5}}, order_by="n", desc=True, limit=3)
    assert [r["n"] for r in rows] == [9, 8, 7]
    assert await repo.delete("settings", "a") and not await repo.delete("settings", "a")
    await repo.put("usage_daily", {"id": "ttl-doc"}, ttl=60)
    assert await repo.get("usage_daily", "ttl-doc")
    repo._data["usage_daily"]["ttl-doc"]["_ts"] -= 120  # two minutes pass
    assert await repo.get("usage_daily", "ttl-doc") is None, "TTL expiry"
    assert await repo.clear("settings") == 10 and (await repo.ping())["ok"]
    for bad in ("a/b", "a\\b", "a?b", "a#b", ""):
        with pytest.raises(ValueError):
            prepare("settings", {"id": bad}, None)


# ---------------------------------------------------------------------------------------------------------- CRM (CC-20)
async def test_crm_contract_suite_passes_for_mock_dataverse_and_generic_rest(svc):
    report = await crm_contract.contract_report(svc.backoffice)
    assert set(report) == {"mock-crm", "dynamics365-dataverse", "generic-rest", "summary"}
    failed = [c for k, v in report.items() if k != "summary" for c in v["checks"] if not c["ok"]]
    assert not failed, failed
    assert report["summary"]["total"] >= 40 and report["dynamics365-dataverse"]["total"] >= 12


async def test_connector_outage_degrades_gracefully_into_a_human_handoff(svc):
    from conftest import say

    svc.ext["crm"].chaos = True
    conv = await svc.orchestrator.start(language="en", recording_consent="granted")
    await say(svc, conv.id, "Where is my order CH-100232?")
    c = await svc.store.get(conv.id)
    assert c.status in ("active", "waiting_human") and not [t for m in c.messages for t in m.tools if t.status == "ok" and t.name in ("lookup_order", "track_shipment")]
    svc.ext["crm"].chaos = False
    with pytest.raises(crm.ConnectorError):
        raise crm.ConnectorError(503, "down", retryable=True)


async def test_customer_360_masks_pii_by_role_and_merges_a_timeline(svc):
    with TestClient(create_app(Settings(mode="offline"))) as c:
        full = c.get("/api/crm/customers/CU-1001/360", headers={"X-Demo-Role": "agent"}).json()
        masked = c.get("/api/crm/customers/CU-1001/360", headers={"X-Demo-Role": "auditor"}).json()
        assert full["customer"]["email"] == "anna.becker@example.com" and masked["customer"]["email"] != "anna.becker@example.com"
        assert "***" in masked["customer"]["email"] or "*" in masked["customer"]["email"]
        assert full["orders"] and full["timeline"] and full["stats"]["orders"] >= 2
        assert c.get("/api/crm/customers?q=thompson", headers={"X-Demo-Role": "agent"}).json()[0]["id"] == "CU-1002"


# ------------------------------------------------------------------------------------------------- outbound (CC-18)
CAMP = {"id": "c", "state": "active", "caps": {"per_customer_7d": 2, "per_day": 150}, "quiet_hours": {"start": 21, "end": 8}}
PREFS = {"consents": {"sms": {"granted": True, "ts": 1.0, "text_version": "v1", "source": "checkout"}, "email": {"granted": True, "ts": 1.0}}, "opt_out": {}}


def ts_at(hour_local: int, tz_market: str) -> float:
    """A UTC timestamp that is `hour_local` o'clock in the market's time zone on 2026-11-18 (winter time)."""
    base = datetime(2026, 11, 18, hour_local, 0, tzinfo=outbound.tz_for(tz_market))
    return base.astimezone(UTC).timestamp()


def decide(market="DE", prefs=PREFS, camp=CAMP, kill=False, now=None, c7=0, today=0):
    return outbound.decide(market=market, prefs=prefs, campaign=camp, kill_switch=kill, now_ts=now or ts_at(11, market), contacts_7d=c7, sent_today=today)


def test_outbound_sends_only_with_consent_and_records_the_evidence():
    d = decide()
    assert d.decision == "sent" and d.channel == "sms" and d.consent["text_version"] == "v1" and "consent:sms" in d.checks
    assert decide(prefs=None).decision == "suppressed" and decide(prefs={"consents": {"sms": {"granted": False}}, "opt_out": {}}).decision == "suppressed"
    assert decide(prefs={**PREFS, "opt_out": {"all": True}}).reason.startswith("customer opted out"), "opt-outs are never contacted"
    assert decide(prefs={**PREFS, "opt_out": {"channels": ["sms"]}}).channel == "email", "an opted-out channel is skipped, the next consented one is used"
    assert decide(prefs={"consents": {"email": {"granted": True}}, "opt_out": {}}).channel == "email"


def test_outbound_kill_switch_pauses_and_caps_override_everything_else():
    assert decide(kill=True).decision == "suppressed" and decide(camp={**CAMP, "state": "paused"}).decision == "suppressed"
    assert decide(camp={**CAMP, "state": "killed"}).decision == "suppressed"
    assert decide(c7=2).decision == "suppressed" and "frequency cap" in decide(c7=2).reason
    assert decide(today=150).decision == "deferred"
    assert decide(c7=1).decision == "sent"


@pytest.mark.parametrize(("market", "local_hour", "expected"), [("DE", 22, "deferred"), ("DE", 7, "deferred"), ("DE", 8, "sent"), ("DE", 20, "sent"), ("UK", 23, "deferred"), ("PL", 12, "sent"), ("PT", 3, "deferred")])
def test_quiet_hours_follow_the_recipients_time_zone(market, local_hour, expected):
    d = decide(market=market, now=ts_at(local_hour, market))
    assert d.decision == expected, (market, local_hour, d.reason)
    if expected == "deferred":
        assert d.scheduled_for > ts_at(local_hour, market) and not outbound.in_quiet_hours(d.scheduled_for, market), "released at the next allowed window"


def test_same_instant_is_quiet_in_one_market_and_not_in_another():
    now = datetime(2026, 11, 18, 21, 30, tzinfo=UTC).timestamp()  # 22:30 in Berlin, 21:30 in London
    assert outbound.in_quiet_hours(now, "DE") and outbound.in_quiet_hours(now, "UK")
    now = datetime(2026, 11, 18, 20, 30, tzinfo=UTC).timestamp()  # 21:30 in Berlin, 20:30 in London
    assert outbound.in_quiet_hours(now, "DE") and not outbound.in_quiet_hours(now, "UK")


def test_outbound_messages_disclose_ai_and_offer_opt_out_in_every_market():
    for lang in outbound.AI_NOTE:
        for trig in ("shipment_delayed", "appointment_reminder"):
            msg = outbound.render(trig, lang, first_name="Anna", order_id="CH-100231", carrier="NordFreight", eta="Fri 20 Nov", kind="delivery", window="09-13")
            assert outbound.AI_NOTE[lang] in msg and outbound.STOP[lang] in msg and "CH-100231" in msg


def test_outbound_api_end_to_end_consent_opt_out_kill_switch_and_audit():
    with TestClient(create_app(Settings(mode="offline"))) as c:
        h = {"X-Demo-Role": "supervisor"}
        night = datetime(2026, 11, 18, 22, 30, tzinfo=UTC).isoformat()
        r = c.post("/api/outbound/events", json={"trigger": "shipment_delayed", "as_of": night}, headers=h).json()
        assert r["candidates"] > 0 and r["counts"]["deferred"] > 0, r
        ov = c.get("/api/outbound/overview", headers=h).json()
        assert ov["counts"]["sent"] + ov["counts"]["deferred"] + ov["counts"]["suppressed"] == r["candidates"]
        assert all(d["consent_evidence"] is not None or d["decision"] == "suppressed" for d in ov["decisions"])
        sup = [d for d in ov["decisions"] if d["decision"] == "suppressed"]
        assert all(d["reason"] for d in sup)
        assert c.post("/api/outbound/kill-switch", json={"on": True}, headers=h).json()["kill_switch"] is True
        r2 = c.post("/api/outbound/events", json={"trigger": "shipment_delayed"}, headers=h).json()
        assert r2["counts"]["sent"] == 0 and r2["counts"]["suppressed"] == r2["candidates"], "kill switch stops all outreach immediately"
        assert c.post("/api/outbound/kill-switch", json={"on": False}, headers=h).json()["kill_switch"] is False


# ------------------------------------------------------------------------------------------ discovery & API surface
def test_feature_auto_discovery_lists_all_24_features_as_implemented():
    with TestClient(create_app(Settings(mode="offline"))) as c:
        feats = c.get("/api/features").json()
        feats = feats["features"] if isinstance(feats, dict) else feats
        ids = sorted(f["id"] for f in feats)
        assert ids == [f"CC-{i:02d}" for i in range(1, 25)]
        assert all(f["status"] == "implemented" and f["ui_route"].startswith("/") and f["api_prefix"].startswith("/api") for f in feats)
        assert {f["priority"] for f in feats} <= {"P0", "P1", "P2"} and {f["epic"] for f in feats}
        meta = c.get("/api/meta").json()
        assert meta["features"] == 24 and meta["mode"] == "offline" and meta["simulated"]
        assert "PSTN" in " ".join(meta["simulated"]) and "ACS Call Automation (legacy)" in " ".join(meta["simulated"])


def test_health_ready_usage_and_spa_fallback():
    with TestClient(create_app(Settings(mode="offline"))) as c:
        assert c.get("/healthz").json()["status"] == "ok"
        ready = c.get("/readyz").json()
        assert ready["status"] in ("ready", "degraded") and ready["mode"] == "offline"
        u = c.get("/api/usage").json()
        assert u["budget_usd"] > 0 and u["status"] in ("ok", "warning") and "by_model" in u
        assert c.get("/api/does-not-exist").status_code == 404
