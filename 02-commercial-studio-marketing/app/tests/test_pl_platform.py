"""Polish platform texts that are rendered at read time: job titles/messages/errors, audit one-liners, approval stages, webhook cards, team notes, campaign-pack README.

Everything stored stays language-neutral (codes + params, hash-chained audit entries untouched); the viewer's language decides what is shown."""

from __future__ import annotations

import io
import time
import zipfile

import pytest
from fastapi.testclient import TestClient

from spotlight.app_factory import create_app
from spotlight.config import Settings
from spotlight.core.notify import format_payload, summary_for, title_for
from spotlight.i18n import use_locale
from spotlight.seed.data import DAWN_ROAST_BRIEF_PL

PL = {"X-Studio-Role": "creative", "X-Studio-User": "tester", "X-UI-Lang": "pl"}
EN = {"X-Studio-Role": "creative", "X-Studio-User": "tester", "X-UI-Lang": "en"}
ADMIN_PL = {"X-Studio-Role": "admin", "X-Studio-User": "tester", "X-UI-Lang": "pl"}
ADMIN_EN = {"X-Studio-Role": "admin", "X-Studio-User": "tester", "X-UI-Lang": "en"}
BM_PL = {"X-Studio-Role": "brand_manager", "X-Studio-User": "tester", "X-UI-Lang": "pl"}


@pytest.fixture(scope="module")
def ctx():
    app = create_app(Settings(spotlight_mode="offline", rate_limit_enabled=False, seed_on_start=True))
    with TestClient(app) as c:
        cid = c.post("/api/campaigns", json={"name": "Dawn Roast — platforma PL", "channels": ["youtube"]}, headers=PL).json()["id"]
        c.put(f"/api/campaigns/{cid}/brief", json={"raw_text": DAWN_ROAST_BRIEF_PL}, headers=PL)
        c.post(f"/api/campaigns/{cid}/brief/analyze", headers=PL)
        c.post(f"/api/campaigns/{cid}/brief/answers", json={"answers": {"key_message": "Wolniejszy początek dnia, zrobiony dobrze.", "cta": "Znajdź Dawn Roast na northwind.example/dawn", "duration_targets": [6, 15]}}, headers=PL)
        assert c.post(f"/api/campaigns/{cid}/brief/finalize", headers=PL).status_code == 200
        yield c, cid


def _wait_for(c: TestClient, job_id: str, timeout: float = 60.0) -> dict:
    end = time.time() + timeout
    while time.time() < end:
        j = c.get(f"/api/jobs/{job_id}", headers=EN).json()
        if j["status"] in {"succeeded", "failed", "cancelled"}:
            return j
        time.sleep(0.2)
    raise AssertionError("job did not finish")


# ------------------------------------------------------------------------------------------------ jobs


def test_job_title_and_message_follow_the_viewer_while_status_and_ids_do_not(ctx):
    c, cid = ctx
    job = c.post(f"/api/campaigns/{cid}/strategy/generate", json={}, headers=PL).json()
    assert job["title"] == "Strateg: spostrzeżenia i kierunki" and job["status"] in {"queued", "running", "succeeded"}
    done = _wait_for(c, job["id"])
    assert done["status"] == "succeeded"
    pl = c.get(f"/api/jobs/{job['id']}", headers=PL).json()
    assert pl["message"] == "Gotowe" and pl["title"] == "Strateg: spostrzeżenia i kierunki"
    assert done["message"] == "Done" and done["title"] == "Strategy agent: insights & territories"
    assert pl["status"] == done["status"] and pl["id"] == done["id"] and pl["kind"] == "strategy.generate"
    assert pl["title_key"] == "job.title.strategy" and pl["message_key"] == "job.state.done"
    listing = c.get("/api/jobs", params={"campaign_id": cid}, headers=PL).json()
    assert listing and all(j["title"] != j["kind"] for j in listing)
    recent = c.get(f"/api/campaigns/{cid}", headers=PL).json()["recent_jobs"]
    assert any(j["title"] == "Strateg: spostrzeżenia i kierunki" for j in recent)


def test_job_progress_stream_is_delivered_in_the_viewers_language(ctx):
    c, cid = ctx
    job = c.post(f"/api/campaigns/{cid}/script/generate", json={"durations": [6, 15]}, headers=PL).json()
    assert job["title"] == "Agent scenariusza: 6/15 s"
    _wait_for(c, job["id"])
    body_pl = c.get(f"/api/stream/jobs/{job['id']}", headers=PL).text
    body_en = c.get(f"/api/stream/jobs/{job['id']}", headers=EN).text
    assert "event: done" in body_pl and "Gotowe" in body_pl and "Agent scenariusza: 6/15 s" in body_pl
    assert "Done" in body_en and "Script agent: 6/15 s" in body_en and "Gotowe" not in body_en


def test_progress_messages_with_params_are_rendered_per_viewer(ctx):
    c, cid = ctx
    from spotlight.core.jobs import _set_message, render_job

    doc: dict = {"title": "x", "status": "running"}
    _set_message(doc, "job.msg.spot.composite", {"dur": 14.9, "aspect": "16:9"})
    assert render_job(doc, "en")["message"] == "Compositing 14.9s spot (16:9)"  # the exact English the job always showed
    assert render_job(doc, "pl")["message"] == "Składanie spotu 14,9 s (16:9)"  # decimal comma
    _set_message(doc, "job.msg.loc.transcreate", {"language": "de"})
    assert render_job(doc, "en")["message"] == "Transcreating to German" and render_job(doc, "pl")["message"] == "Transkreacja na język: niemiecki"
    _set_message(doc, "job.msg.frames.start", {"total": 6, "model": "gpt-image-2", "quality": "low"})
    assert render_job(doc, "en")["message"] == "Generating 6 keyframes (gpt-image-2, low)" and render_job(doc, "pl")["message"] == "Generowanie klatek kluczowych: 6 (gpt-image-2, jakość: niska)"
    plain = {"title": "x", "status": "running", "message": "Custom text"}
    assert render_job(plain, "pl")["message"] == "Custom text"  # records without keys (older jobs) keep their text


def test_failed_job_error_is_localized_at_read_time_and_on_wait(ctx):
    c, _ = ctx
    cid2 = c.post("/api/campaigns", json={"name": "Bez briefu", "channels": ["meta"]}, headers=PL).json()["id"]
    r_pl = c.post(f"/api/campaigns/{cid2}/strategy/generate?wait=true", json={}, headers=PL)
    r_en = c.post(f"/api/campaigns/{cid2}/strategy/generate?wait=true", json={}, headers=EN)
    assert r_pl.status_code == r_en.status_code and r_pl.json()["error"]["code"] == r_en.json()["error"]["code"] == "brief_missing"
    assert r_en.json()["error"]["message"] == "Finalize the brief first (CS-04)."
    assert r_pl.json()["error"]["message"] != r_en.json()["error"]["message"] and "brief" in r_pl.json()["error"]["message"].lower() and "{" not in r_pl.json()["error"]["message"]
    job = c.post(f"/api/campaigns/{cid2}/strategy/generate", json={}, headers=PL).json()
    done = _wait_for(c, job["id"])
    assert done["status"] == "failed" and done["error"] == "Finalize the brief first (CS-04)." and done["error_code"] == "brief_missing"
    pl = c.get(f"/api/jobs/{job['id']}", headers=PL).json()
    assert pl["error"] == r_pl.json()["error"]["message"] and pl["message"] == pl["error"] and pl["error_code"] == "brief_missing"


# ------------------------------------------------------------------------------------------------ audit, approvals, notifications


def test_audit_entries_carry_a_localized_one_liner_and_the_hash_chain_is_untouched(ctx):
    c, cid = ctx
    pl = c.get(f"/api/campaigns/{cid}/audit", headers=PL).json()
    en = c.get(f"/api/campaigns/{cid}/audit", headers=EN).json()
    assert pl["verification"]["ok"] and en["verification"]["ok"] and pl["verification"]["head_hash"] == en["verification"]["head_hash"]
    by_action_pl = {e["action"]: e["message"] for e in pl["entries"]}
    by_action_en = {e["action"]: e["message"] for e in en["entries"]}
    assert by_action_pl["campaign.created"] == "Utworzono kampanię" and by_action_en["campaign.created"] == "Campaign created"
    assert by_action_pl["brief.finalized"] == "Sfinalizowano brief" and by_action_en["brief.finalized"] == "Brief finalised"
    assert [e["hash"] for e in pl["entries"]] == [e["hash"] for e in en["entries"]] and [e["action"] for e in pl["entries"]] == [e["action"] for e in en["entries"]]
    activity = c.get("/api/studio/activity", params={"limit": 100}, headers=PL).json()["activity"]
    assert any(a["action"] == "campaign.created" and a["message"] == "Utworzono kampanię" for a in activity)


def test_every_audit_action_the_backend_writes_has_a_catalog_label():
    import pathlib
    import re

    from spotlight.i18n import CATALOGS

    src = pathlib.Path(__file__).resolve().parents[1] / "src" / "spotlight"
    actions: set[str] = set()
    for p in src.rglob("*.py"):
        for m in re.finditer(r'\.audit\(\s*[^,]+,\s*[^,]+,\s*"([a-z_]+\.[a-z_]+)"', p.read_text(encoding="utf-8")):
            actions.add(m.group(1))
    actions |= {"approval.approve", "approval.reject", "approval.request_changes", "budget.premium_approved", "budget.premium_revoked"}  # written with a computed suffix
    actions -= {"approval.decision", "budget.premium_"}
    missing = sorted(a for a in actions if f"audit.{a}" not in CATALOGS["en"] or f"audit.{a}" not in CATALOGS["pl"])
    assert len(actions) >= 45 and not missing, missing


def test_approval_stage_and_state_names_are_rendered_per_viewer_and_the_audit_line_names_the_stage(ctx):
    c, cid = ctx
    apr = c.post(f"/api/campaigns/{cid}/approvals", json={"stage": "concept"}, headers=PL)
    if apr.status_code != 200:  # the concept gate needs a strategy: the earlier test generated one
        raise AssertionError(apr.text)
    apr = apr.json()
    assert apr["stage_label"] == "Koncepcja (strategia)" and apr["state_label"] == "oczekująca" and apr["stage"] == "concept" and apr["state"] == "pending"
    en = c.get(f"/api/campaigns/{cid}/approvals", headers=EN).json()
    pl = c.get(f"/api/campaigns/{cid}/approvals", headers=PL).json()
    assert [g["id"] for g in pl["gates"]] == [g["id"] for g in en["gates"]] and {g["label"] for g in pl["gates"]} != {g["label"] for g in en["gates"]}
    assert next(g for g in en["gates"] if g["id"] == "final")["label"] == "Final spot" and next(g for g in pl["gates"] if g["id"] == "final")["label"] == "Spot finalny"
    assert [p["label"] for p in pl["pipeline"]][:3] == ["Brief", "Koncepcja (strategia)", "Scenariusz"]
    audit = {e["action"]: e["message"] for e in c.get(f"/api/campaigns/{cid}/audit", headers=PL).json()["entries"]}
    assert audit["approval.requested"] == "Poproszono o zatwierdzenie — Koncepcja (strategia)"
    en_audit = {e["action"]: e["message"] for e in c.get(f"/api/campaigns/{cid}/audit", headers=EN).json()["entries"]}
    assert en_audit["approval.requested"] == "Approval requested — Concept (strategy)"


def test_webhook_cards_are_rendered_in_the_language_of_the_user_who_triggered_them(ctx):
    c, _ = ctx
    hook = c.post("/api/team/webhooks", json={"name": "Sink PL", "url": "internal://sink", "format": "generic"}, headers=ADMIN_PL).json()
    d_pl = c.post(f"/api/team/webhooks/{hook['id']}/test", headers=ADMIN_PL).json()
    d_en = c.post(f"/api/team/webhooks/{hook['id']}/test", headers=ADMIN_EN).json()
    assert d_pl["ok"] and d_pl["payload"]["title"] == "Spotlight · Prośba o zatwierdzenie"
    assert d_pl["payload"]["text"] == "kampania: Dawn Roast — premiera · etap: Scenariusz · przez: test webhooka"
    assert d_en["payload"]["title"] == "Spotlight · Approval requested" and d_en["payload"]["text"] == "campaign: Dawn Roast — Launch · stage: Script · by: webhook test"
    assert d_pl["payload"]["event"] == d_en["payload"]["event"] == "approval.requested"  # machine fields are language-neutral


def test_notification_text_helpers_render_every_event_and_field_in_both_languages():
    events = ["approval.requested", "approval.approved", "approval.rejected", "approval.changes_requested", "job.failed", "job.succeeded", "budget.alert", "rights.expiring", "rights.revoked"]
    payload = {"campaign": "K", "stage": "Final spot", "stage_id": "final", "decision": "request_changes", "by": "Ala", "title": "T", "scope": "global", "spent_usd": 1.5, "cap_usd": 8, "days_left": 3, "kind": "spot.render"}
    with use_locale("pl"):
        pl_titles = [title_for(e) for e in events]
        assert all(t and t != e for t, e in zip(pl_titles, events, strict=True)) and len(set(pl_titles)) == len(events)
        assert summary_for("approval.approved", payload) == "kampania: K · etap: Spot finalny · decyzja: zażądano zmian · przez: Ala · tytuł: T · zakres: global · wydano (USD): 1.5 · limit (USD): 8 · dni do końca: 3 · rodzaj: spot.render"
        assert format_payload("slack", "job.failed", {"title": "x"})["text"] == "*Spotlight · Zadanie nie powiodło się* — tytuł: x"
    with use_locale("en"):
        assert title_for("budget.alert") == "Budget alert" and title_for("custom.event") == "custom.event"
        assert summary_for("approval.approved", payload).startswith("campaign: K · stage: Final spot · decision: request_changes · by: Ala")


# ------------------------------------------------------------------------------------------------ team, export


def test_team_roster_roles_and_api_notes_follow_the_viewer(ctx):
    c, _ = ctx
    pl = c.get("/api/team/members", headers=PL).json()
    en = c.get("/api/team/members", headers=EN).json()
    assert [m["name"] for m in pl["members"]] == [m["name"] for m in en["members"]] and [m["role"] for m in pl["members"]] == [m["role"] for m in en["members"]]
    assert en["members"][0]["title"] == "Studio administrator" and pl["members"][0]["title"] == "Administrator studia" and pl["note"].startswith("Fikcyjny skład zespołu")
    roles = {r["id"]: r["label"] for r in c.get("/api/team/roles", headers=PL).json()["roles"]}
    assert roles["creative_director"] == "Dyrektor kreatywny" and roles["agency_guest"] == "Agencja (gość)"
    assert {r["id"]: r["label"] for r in c.get("/api/team/roles", headers=EN).json()["roles"]}["creative_director"] == "Creative Director"
    assert c.get("/api/team/api", headers=PL).json()["auth"].startswith("Demo: nagłówki X-Studio-Role")


def test_campaign_pack_readme_and_manifest_note_follow_the_campaign_language(ctx):
    c, cid = ctx
    r = c.post(f"/api/campaigns/{cid}/export?wait=true", headers={**PL, "X-Studio-Role": "creative_director"})
    assert r.status_code == 200, r.text
    asset_id = r.json()["result"]["asset_id"]
    blob = c.get(f"/api/library/assets/{asset_id}/content", headers=EN).content  # fetched with an English UI: the pack is a deliverable in the campaign language
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        readme = z.read("README.txt").decode("utf-8")
        note = z.read("manifest.json").decode("utf-8")
    assert readme.startswith("Pakiet kampanii wygenerowany przez SwarmAI Spotlight") and "SHA-256 każdego pliku" in readme
    assert "Spoty mają wtopione napisy" in note and "\\u" not in note  # readable UTF-8, not escaped


# ------------------------------------------------------------------------------------------------ notes that sit next to numbers


def test_cost_roi_ops_connector_and_market_notes_follow_the_viewer_and_english_is_byte_identical(ctx):
    from spotlight.core.ai.pricing import PRICING_NOTE
    from spotlight.domain import localize as lz
    from spotlight.domain.disclosure import PLATFORMS

    c, cid = ctx
    budget_en, budget_pl = c.get("/api/budget", headers=EN).json(), c.get("/api/budget", headers=PL).json()
    assert budget_en["pricing"]["note"] == PRICING_NOTE and budget_pl["pricing"]["note"].startswith("Szacunkowe ceny katalogowe")
    assert budget_en["pricing"]["agency_baseline_per_asset_usd"] == budget_pl["pricing"]["agency_baseline_per_asset_usd"]  # numbers never change
    assert c.get("/api/usage", headers=PL).json()["pricing_note"].startswith("Szacunkowe ceny katalogowe")
    live_en, live_pl = c.get("/api/roi/live", headers=EN).json(), c.get("/api/roi/live", headers=PL).json()
    assert live_en["cycle_time_reference"] == "Agency baseline: 6–10 weeks from brief to final delivery (brief §4)." and live_pl["cycle_time_reference"].startswith("Punkt odniesienia agencji")
    assert live_pl["kpi"]["baseline_note"].startswith("Założenie:") and live_en["kpi"]["baseline_note"].startswith("Assumption:")
    assert c.get("/api/ops/status", headers=PL).json()["security"]["auth"].startswith("wyłącznie tożsamość zarządzana")
    assert c.get("/api/ops/status", headers=EN).json()["security"]["auth"] == "managed identity / Entra ID only (keyless); no account keys or connection secrets"
    assert c.get("/api/performance/connectors", headers=PL).json()["connectors"][0]["production"].startswith("Azure Functions + API raportowe")
    langs_pl = c.get(f"/api/campaigns/{cid}/localization/languages", headers=PL).json()
    langs_en = c.get(f"/api/campaigns/{cid}/localization/languages", headers=EN).json()
    assert {x["code"]: x["notes"] for x in langs_en["languages"]} == lz.MARKET_NOTES  # the English text the editors always saw
    assert next(x for x in langs_pl["languages"] if x["code"] == "de")["notes"].startswith("Rzeczowo") and langs_pl["directions"].startswith("dowolny język źródłowy")
    labels_pl = c.get("/api/provenance/labels", params={"markets": "PL", "channels": "tiktok"}, headers=PL).json()
    labels_en = c.get("/api/provenance/labels", params={"markets": "PL", "channels": "tiktok"}, headers=EN).json()
    assert labels_en["platform_catalog"]["tiktok"]["mechanism"] == PLATFORMS["tiktok"]["mechanism"] and labels_pl["platform_catalog"]["tiktok"]["mechanism"].startswith("Włącz przełącznik")
    assert labels_pl["platform_catalog"]["tiktok"]["required"] is True  # machine flags are untouched


def test_brand_kit_logo_note_is_translated_but_the_wordmark_and_numbers_are_not(ctx):
    c, _ = ctx
    pl = c.get("/api/brand", headers=PL).json()["kit"]
    en = c.get("/api/brand", headers=EN).json()["kit"]
    assert pl["logo"]["notes"].startswith("Bursztynowy znak słońca") and en["logo"]["notes"].startswith("Amber sun mark")
    assert pl["logo"]["wordmark"] == en["logo"]["wordmark"] == "NORTHWIND" and pl["logo"]["min_width_pct"] == en["logo"]["min_width_pct"]
