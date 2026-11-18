"""Polish experiments / insights / planner: texts follow the campaign (stored) or the viewer (read time); ids and numbers never change."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from spotlight.app_factory import create_app
from spotlight.config import Settings
from spotlight.domain import perfsim as ps

PL = {"X-Studio-Role": "creative", "X-Studio-User": "tester", "X-UI-Lang": "pl"}
EN = {"X-Studio-Role": "creative", "X-Studio-User": "tester", "X-UI-Lang": "en"}
PL_LETTERS = set("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ")


@pytest.fixture(scope="module")
def client():
    with TestClient(create_app(Settings(spotlight_mode="offline", rate_limit_enabled=False, seed_on_start=True))) as c:
        yield c


def _campaign(client, lang: str) -> str:
    h = PL if lang == "pl" else EN
    return client.post("/api/campaigns", json={"name": f"Insights {lang}", "markets": ["PL" if lang == "pl" else "US"], "channels": ["meta"], "language": lang}, headers=h).json()["id"]


# ------------------------------------------------------------------------------------------------ CS-17 variants


def test_polish_experiment_has_polish_copy_labels_rationale_and_name_while_ids_stay_english(client):
    exp = client.post("/api/experiments", json={"campaign_id": _campaign(client, "pl")}, headers=PL).json()
    assert exp["name"] == "Test wariantów Dawn Roast" and exp["lang"] == "pl"
    v1 = exp["variants"][0]
    assert v1["attrs"] == {"hook": "Human moment first", "cta": "Find it near you", "visual": "Warm kitchen"}  # machine ids are language-neutral
    assert v1["label"] == "Najpierw ludzka chwila · Znajdź w pobliżu · Kuchnia w ciepłym świetle"
    assert v1["copy"]["hook_line"] == "Zanim dom się obudzi, jest cicha godzina." and v1["copy"]["cta"] == "Znajdź w pobliżu"
    ranking = client.post(f"/api/experiments/{exp['id']}/preflight", headers=PL).json()
    assert ranking["label"] == "Predykcja / symulacja" and len(ranking["ranking"]) == 12
    assert all(r["rationale"].startswith("symulowany panel: hook=") for r in ranking["ranking"])
    sim = client.post(f"/api/experiments/{exp['id']}/simulate", json={"hours": 24}, headers=PL).json()
    assert any(c in sim["leader"]["label"] for c in "ąćęłńóśźż") or " · " in sim["leader"]["label"]
    assert "Najpierw" in sim["leader"]["label"] or "Otwarcie" in sim["leader"]["label"] or "Znajdź" in sim["leader"]["label"] or "Spróbuj" in sim["leader"]["label"]
    assert all(set(p["label"]) & PL_LETTERS for p in sim["last_run"]["paused"])
    sig = client.get(f"/api/experiments/{exp['id']}/significance", headers=PL).json()
    assert sig["control"] == "v01" and all(set(r["label"]) & PL_LETTERS for r in sig["results"])


def test_experiment_labels_are_rendered_for_the_viewer_not_frozen_at_creation(client):
    exp = client.post("/api/experiments", json={"campaign_id": _campaign(client, "pl")}, headers=PL).json()
    pl_view = client.get(f"/api/experiments/{exp['id']}", headers=PL).json()["variants"][1]
    en_view = client.get(f"/api/experiments/{exp['id']}", headers=EN).json()["variants"][1]
    assert pl_view["label"] != en_view["label"] and en_view["label"] == "Human moment first · Find it near you · Macro pour"
    assert pl_view["attrs"] == en_view["attrs"]


def test_english_experiment_is_unchanged(client):
    exp = client.post("/api/experiments", json={"campaign_id": _campaign(client, "en")}, headers=EN).json()
    assert exp["name"] == "Dawn Roast variant test" and exp["lang"] == "en"
    v1 = exp["variants"][0]
    assert v1["label"] == "Human moment first · Find it near you · Warm kitchen"
    assert v1["copy"] == {"hook_line": "Before the house wakes up, there is a quiet hour.", "cta": "Find it near you", "visual": "Warm kitchen"}
    ranking = client.post(f"/api/experiments/{exp['id']}/preflight", headers=EN).json()
    assert ranking["label"] == "Predictive / simulated" and ranking["ranking"][0]["rationale"].startswith("simulated panel: hook=")


def test_explicit_experiment_name_is_kept_as_typed(client):
    exp = client.post("/api/experiments", json={"campaign_id": _campaign(client, "pl"), "name": "Mój test"}, headers=PL).json()
    assert exp["name"] == "Mój test"


# ------------------------------------------------------------------------------------------------ CS-18 insights


def _rows_with_clear_winner() -> list[dict]:
    rows = []
    for hook, ctr in (("Human moment first", 0.02), ("Product first", 0.008), ("Question hook", 0.009)):
        for day in range(1, 6):
            rows.append({"hook": hook, "platform": "meta", "impressions": 60_000, "clicks": int(60_000 * ctr), "conversions": int(60_000 * ctr * 0.05), "spend": 300.0, "revenue": 200.0, "date": f"2026-03-0{day}"})
    return rows


def test_insight_statements_are_rendered_in_polish_from_structured_evidence():
    ins = ps.insights_from_rows(_rows_with_clear_winner(), dims=["hook"], min_impressions=1000)
    assert ins and ins[0]["winner"] == "Human moment first"
    pl_text = ps.render_statement(ins[0], "pl")
    assert pl_text and "Hook" in pl_text and "„Najpierw ludzka chwila”" in pl_text and "współczynnik" in pl_text
    assert ps.render_statement(ins[0], "en") == ins[0]["statement"]  # English stays exactly as generated
    assert ps.render_statement({"dimension": "hook"}, "pl") is None  # free-text learnings (no structured evidence) are never "translated"


def test_insights_endpoint_returns_polish_statements_for_a_polish_viewer(client):
    cid = _campaign(client, "pl")
    assert client.post("/api/performance/connectors/tiktok/sync", json={"campaign_id": cid, "days": 14}, headers=PL).status_code == 200
    gen = client.post("/api/performance/insights/generate", json={"campaign_id": cid, "min_impressions": 1000}, headers=PL).json()
    assert gen["insights"], "the simulated connector must produce at least one insight"
    first = gen["insights"][0]
    assert set(first["statement"]) & PL_LETTERS and first["statement_en"] != first["statement"]
    stored_pl = client.get("/api/performance/insights", params={"campaign_id": cid}, headers=PL).json()["insights"]
    stored_en = client.get("/api/performance/insights", params={"campaign_id": cid}, headers=EN).json()["insights"]
    assert stored_pl and stored_en and len(stored_pl) == len(stored_en)
    assert all(set(s["statement"]) & PL_LETTERS for s in stored_pl)  # rendered at read time from the evidence
    assert all(not (set(s["statement"]) & PL_LETTERS) for s in stored_en)  # the same rows read in English


# ------------------------------------------------------------------------------------------------ CS-19 planner


def test_planner_note_and_channel_names_follow_the_viewer_while_numbers_do_not(client):
    plan_pl = client.post("/api/planner/plan", json={"budget_usd": 400000, "objective": "roas"}, headers=PL).json()
    plan_en = client.post("/api/planner/plan", json={"budget_usd": 400000, "objective": "roas"}, headers=EN).json()
    assert plan_pl["note"].startswith("ILUSTRACYJNIE") and plan_en["note"].startswith("ILLUSTRATIVE")
    assert [a["spend"] for a in plan_pl["allocation"]] == [a["spend"] for a in plan_en["allocation"]] and [a["channel"] for a in plan_pl["allocation"]] == [a["channel"] for a in plan_en["allocation"]]
    assert all(a["label"] for a in plan_pl["allocation"]) and {a["label"] for a in plan_pl["allocation"]} != {a["label"] for a in plan_en["allocation"]}
    ch = client.get("/api/planner/channels", headers=PL).json()
    assert ch["channels"] == client.get("/api/planner/channels", headers=EN).json()["channels"] and ch["note"].startswith("Założenia ilustracyjne") and ch["labels"]["youtube"] == "YouTube"
