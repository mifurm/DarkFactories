"""Polish-first creative pipeline (offline stubs, real ffmpeg): Polish brief -> clarifying questions -> strategy -> 6/15/30 s scripts ->
Guardian BLOCK on a Polish prohibited claim -> auto-revise -> storyboard (Polish text, English image prompts) -> pl-PL voice-over ->
captions / supers / end card with correct diacritics -> a 15 s MP4 that meets the delivery spec -> Polish scorecard + localization to English."""

from __future__ import annotations

import io
import re

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from conftest import needs_ffmpeg
from spotlight.app_factory import create_app
from spotlight.config import Settings
from spotlight.domain.localize import similarity
from spotlight.domain.polish import NBSP, spoken_text
from spotlight.domain.script import timing_issues
from spotlight.domain.text import fold
from spotlight.domain.timing import beat_fit, estimate_vo_seconds
from spotlight.seed.data import DAWN_ROAST_BRIEF_PL
from spotlight.video import media, overlays
from spotlight.video.spec import Cue, RenderSpec, VoLine, make_captions, to_srt

PL = {"X-Studio-Role": "creative", "X-Studio-User": "tester", "X-UI-Lang": "pl"}
PL_LETTERS = set("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ")


def _has_polish_letters(text: str) -> bool:
    return bool(PL_LETTERS & set(text))


# ------------------------------------------------------------------------------------------------ typography units (no pipeline)


def test_wrap_never_breaks_at_nbsp_and_shrinks_type_for_very_long_words():
    f = overlays.font(40, bold=True)
    text = f"Dawn{NBSP}Roast i{NBSP}w{NBSP}małych partiach"
    lines = overlays.wrap(text, f, f.getlength("Dawn Roast i w małych") + 5)
    assert any(f"Dawn{NBSP}Roast" in ln for ln in lines) and not any(ln.endswith(" i") or ln.endswith(" w") for ln in lines)
    long_word = "Przedsiębiorczość niespodziewanie"
    size, font_used, wrapped = overlays.fit_wrap(long_word, 90, 380, bold=True)
    assert size < 90 and max(font_used.getlength(x) for x in wrapped) <= 380  # a long Polish word shrinks the type instead of leaving the frame
    assert overlays.fit_wrap("Krótko", 40, 600)[0] == 40  # short text keeps its size (English captions are unchanged)


@pytest.mark.parametrize("serif", [False, True])
def test_every_polish_glyph_is_really_drawn_not_a_missing_glyph_box(serif):
    f = overlays.font(64, bold=True, serif=serif)
    notdef = f.getmask("\uffff")
    for ch in "ąćęłńóśźżĄĆĘŁŃÓŚŹŻ":
        mask = f.getmask(ch)
        assert mask.getbbox() is not None, ch
        assert bytes(mask) != bytes(notdef) or mask.size != notdef.size, ch
    assert f.getlength(NBSP) > 0  # NBSP has an advance (it is drawn as a space)


def test_captions_are_typeset_and_never_end_on_a_single_letter_word():
    vo = [
        VoLine(id="v1", text="Dawn Roast. Średnie palenie, palone w małych partiach i w pięknym świetle poranka.", start=0.25, duration=5.0),
        VoLine(id="v2", text="Karmel, pomarańcza i kakao z Kolumbii, z Etiopii i z Gwatemali, o świcie.", start=6.0, duration=5.0),
    ]
    cues = make_captions(vo, lang="pl")
    assert len(cues) >= 4
    for c in cues:
        last = c.text.split(" ")[-1].replace(NBSP, " ").split(" ")[-1]
        assert last.lower() not in {"i", "w", "z", "o", "u", "a"}, c.text
    assert any(f"w{NBSP}małych" in c.text or f"w{NBSP}pięknym" in c.text for c in cues) and any(f"Dawn{NBSP}Roast" in c.text for c in cues)
    assert all(a.end <= b.start for a, b in zip(cues, cues[1:], strict=False))  # monotonic, no overlap
    srt = to_srt(cues)
    assert srt.encode("utf-8").decode("utf-8") == srt and "pomarańcza" in srt  # UTF-8 with diacritics, NBSP kept
    english = make_captions([VoLine(id="v1", text="Some mornings deserve a slower start, made well.", start=0, duration=4)])
    assert all(NBSP not in c.text for c in english)  # English captions are untouched


def test_polish_captions_break_at_sentence_ends_while_english_keeps_its_word_by_word_split():
    line = VoLine(id="v1", text="To jest Dawn Roast. Pierwsza filiżanka, zanim świat ruszy.", start=0.25, duration=4.0)
    pl = [c.text.replace(NBSP, " ") for c in make_captions([line], lang="pl")]
    assert pl == ["To jest Dawn Roast.", "Pierwsza filiżanka, zanim świat ruszy."]  # not "... Roast. Pierwsza" | "filiżanka, ..."
    two = [c.text.replace(NBSP, " ") for c in make_captions([VoLine(id="v2", text="100% arabiki. Palona w małych partiach.", start=0, duration=3)], lang="pl")]
    assert two == ["100% arabiki.", "Palona w małych partiach."]
    short = [c.text for c in make_captions([VoLine(id="v3", text="Obudź się powoli. Dawn Roast.", start=0, duration=3)], lang="pl")]
    assert len(short) == 1  # whole sentences that fit stay on one cue
    en_line = VoLine(id="v4", text="This is Dawn Roast. Your first cup, before the world.", start=0, duration=4)
    assert [c.text for c in make_captions([en_line])] == ["This is Dawn Roast. Your first cup,", "before the world."]  # the long-validated English split


def test_a_polish_sentence_longer_than_a_cue_is_split_evenly_without_a_one_word_orphan():
    line = VoLine(id="v1", text="Dawn Roast daje spokojniejszy początek poranka.", start=7.75, duration=3.3)
    cues = make_captions([line], lang="pl")
    assert [c.text.replace(NBSP, " ") for c in cues] == ["Dawn Roast daje spokojniejszy", "początek poranka."]  # greedy fill gave "…początek" | "poranka."
    assert cues[0].end < cues[1].start and cues[1].end - cues[1].start > 0.9
    comma = make_captions([VoLine(id="v3", text="Średnie palenie, palone w małych partiach.", start=0, duration=3)], lang="pl")
    assert [c.text.replace(NBSP, " ") for c in comma] == ["Średnie palenie,", "palone w małych partiach."]  # the break goes to the comma, not after "palone" / before "partiach."
    dash = make_captions([VoLine(id="v4", text="Dawn Roast — wolniejszy start, dobrze zrobiony.", start=0, duration=3)], lang="pl")
    assert [c.text.replace(NBSP, " ") for c in dash] == ["Dawn Roast — wolniejszy start,", "dobrze zrobiony."]  # not "wolniejszy | start"
    long_word = make_captions([VoLine(id="v2", text="Nieprawdopodobnie-długowyrazowe-przymiotnikowo-nieregularne.", start=0, duration=3)], lang="pl")
    assert len(long_word) == 1


def test_speech_text_reads_numbers_in_words_and_respells_the_brand_for_the_voice_only():
    pron = {"Dawn Roast": "dołn rołst", "Northwind": "nortłind"}
    spoken = spoken_text("Dawn Roast: 340 g, 100% arabiki, 12.01.2027.", "pl", pron)
    assert spoken == "dołn rołst: trzysta czterdzieści gramów, sto procent arabiki, dwunastego stycznia dwa tysiące dwudziestego siódmego roku."
    assert spoken_text("Dawn Roast: 340 g", "en", pron) == "Dawn Roast: 340 g"  # other languages pass through
    assert spoken_text("Northwindowa kawa", "pl", pron) == "Northwindowa kawa"  # whole words only


def test_polish_voice_over_estimate_is_longer_than_english_and_flags_a_line_that_cannot_fit():
    pl = "Dawn Roast. Średnie palenie, palone w małych partiach."
    en = "Dawn Roast. Medium roast, roasted in small batches."
    assert estimate_vo_seconds(pl, "pl") > estimate_vo_seconds(en, "en") * 0.95
    beats = [
        {"id": "b1", "role": "hook", "t_start": 0.0, "t_end": 3.3, "vo": "Zacznij dzień wolniej."},
        {"id": "b2", "role": "product", "t_start": 3.3, "t_end": 5.0, "vo": "Dawn Roast. Średnie palenie, palone w małych partiach, z plantacji partnerskich, które odwiedzamy co roku."},
    ]
    issues = timing_issues(beats, "pl")
    assert [i["beat_id"] for i in issues] == ["b2"] and issues[0]["key"] == "script.line_too_long" and issues[0]["over_pct"] > 0
    assert beats[0]["vo_est_s"] > 0 and beat_fit(beats[0], "pl")["too_long"] is False


# ------------------------------------------------------------------------------------------------ the Polish pipeline


@pytest.fixture(scope="module")
def run():
    """One Polish campaign driven through the whole pipeline (offline stubs; ffmpeg renders the MP4)."""
    app = create_app(Settings(spotlight_mode="offline", rate_limit_enabled=False, seed_on_start=True))
    out: dict = {}
    with TestClient(app) as c:
        out["client"] = c
        r = c.post("/api/campaigns", json={"name": "Dawn Roast — test PL", "channels": ["youtube", "meta"]}, headers=PL)
        assert r.status_code == 200, r.text
        out["campaign"] = r.json()
        cid = out["campaign"]["id"]
        c.put(f"/api/campaigns/{cid}/brief", json={"raw_text": DAWN_ROAST_BRIEF_PL}, headers=PL)
        out["analyzed"] = c.post(f"/api/campaigns/{cid}/brief/analyze", headers=PL).json()
        r = c.post(f"/api/campaigns/{cid}/brief/answers", json={"answers": {"key_message": "Wolniejszy początek dnia, zrobiony dobrze.", "cta": "Znajdź Dawn Roast na northwind.example/dawn", "duration_targets": [6, 15, 30]}}, headers=PL)
        assert r.status_code == 200 and r.json()["completeness"]["missing"] == []
        out["finalized"] = c.post(f"/api/campaigns/{cid}/brief/finalize", headers=PL).json()
        assert c.post(f"/api/campaigns/{cid}/strategy/generate?wait=true", json={}, headers=PL).status_code == 200
        out["strategy"] = c.get(f"/api/campaigns/{cid}/strategy", headers=PL).json()["latest"]
        assert c.post(f"/api/campaigns/{cid}/script/generate?wait=true", json={"durations": [6, 15, 30]}, headers=PL).status_code == 200
        out["scripts"] = {s["duration_s"]: s for s in c.get(f"/api/campaigns/{cid}/script", headers=PL).json()["scripts"]}
        s15 = out["scripts"][15]
        out["guardian_before"] = c.post(f"/api/campaigns/{cid}/guardian/run", json={"artifact_id": s15["id"]}, headers=PL).json()
        out["revised"] = c.post(f"/api/campaigns/{cid}/guardian/run", json={"artifact_id": s15["id"], "auto_revise": True}, headers=PL).json()
        out["script15"] = c.get(f"/api/campaigns/{cid}/script/{s15['id']}", headers=PL).json()
        assert c.post(f"/api/campaigns/{cid}/storyboard/generate?wait=true", json={"script_id": s15["id"]}, headers=PL).status_code == 200
        sb = c.get(f"/api/campaigns/{cid}/storyboard", headers=PL).json()["latest"]
        assert c.post(f"/api/campaigns/{cid}/storyboard/{sb['id']}/frames?wait=true", json={"quality": "low"}, headers=PL).status_code == 200
        out["storyboard"] = c.get(f"/api/campaigns/{cid}/storyboard", headers=PL).json()["latest"]
        r = c.post(f"/api/campaigns/{cid}/audio/generate?wait=true", json={"script_id": s15["id"]}, headers=PL)  # no "lang": it follows the campaign
        assert r.status_code == 200, r.text
        out["voice"] = c.get(f"/api/campaigns/{cid}/audio", headers=PL).json()["latest"]
        r = c.post(f"/api/campaigns/{cid}/spot/render?wait=true", json={}, headers=PL)
        assert r.status_code == 200, r.text
        out["render"] = r.json()["result"]
        out["spot"] = c.get(f"/api/campaigns/{cid}/spot", headers=PL).json()["spots"][0]
        out["video"] = c.get(f"/api/library/assets/{out['spot']['assets']['video']}/content", headers=PL).content
        out["srt"] = c.get(f"/api/library/assets/{out['spot']['assets']['srt']}/content", headers=PL).content.decode("utf-8")
        out["spot_art"] = c.get(f"/api/campaigns/{cid}/spot/{out['spot']['id']}", headers=PL).json()
        yield out


def test_brief_intake_in_polish_extracts_fields_and_asks_polish_clarifying_questions(run):
    b = run["analyzed"]
    f = b["fields"]
    assert f["product"] == "Dawn Roast" and f["markets"] == ["PL"] and f["channels"] == ["youtube", "meta", "tiktok", "ctv"]
    assert f["kpis"] == ["120 000 zakupów próbnych w 8 tygodni"] and "1 500 000 PLN" in f["budget"] and f["talent"] == ["Maya Okafor"] and f["music_reference"] == "Sunrise Anthem"
    assert f["tone"] == ["ciepły", "niespieszny", "szczery"]
    assert "Zakończ hasłem „Obudź się powoli.”" in f["mandatories"] and "Użyj dokładnie zdania „Dawn Roast leczy poranny niepokój.”" in f["mandatories"]
    assert b["lang"] == "pl" and b["completeness"]["missing"] == ["key_message", "cta", "duration_targets"]
    assert [q["field"] for q in b["questions"]] == ["key_message", "cta", "duration_targets"]
    assert all(_has_polish_letters(q["question"] + q["why"]) and q["question"].endswith("?") for q in b["questions"])
    assert "Dawn Roast" in b["questions"][0]["question"]


def test_brief_guardian_blocks_the_polish_risky_mandatory_and_the_unlicensed_track_in_polish(run):
    rep = run["finalized"]["guardian_report"]
    assert rep["verdict"] == "block"
    rules = {f["rule_id"]: f for f in rep["findings"]}
    assert {"claims.prohibited", "rights.unlicensed"} <= set(rules)
    assert rules["claims.prohibited"]["message"].startswith("Zakazany claim „leczy poranny niepokój”") and "nie ma licencji" in rules["rights.unlicensed"]["message"]
    assert run["finalized"]["artifact"]["title"] == "Znormalizowany brief"


def test_strategy_territories_are_polish_and_pass_the_polish_guardian(run):
    st = run["strategy"]
    assert st["lang"] == "pl" and st["title"] == "Strategia i kierunki" and len(st["territories"]) == 3
    assert [t["name"] for t in st["territories"]][0] == "Cicha godzina"
    assert all(_has_polish_letters(t["big_idea"] + t["rationale"]) for t in st["territories"])
    assert st["guardian"]["verdict"] == "pass" and st["guardian"]["score"] == 100


def test_scripts_6_15_30_are_written_in_polish_with_polish_timing(run):
    assert set(run["scripts"]) == {6, 15, 30}
    for d, s in run["scripts"].items():
        assert s["lang"] == "pl" and s["tagline"] == "Obudź się powoli." and s["cta"] == "Znajdź Dawn Roast w pobliżu"
        assert s["beats"][0]["t_start"] == 0 and s["beats"][-1]["t_end"] == d and s["beats"][-1]["vo"].rstrip().endswith("Obudź się powoli.")
        assert all(a["t_end"] == b["t_start"] for a, b in zip(s["beats"], s["beats"][1:], strict=False))
        assert all(b["vo_est_s"] > 0 for b in s["beats"] if b["vo"])
        assert not s["timing_issues"], s["timing_issues"]
        assert s["word_count"] <= s["word_budget"] * 1.15 and not s["over_budget"]
    s15 = run["scripts"][15]
    assert len(s15["beats"]) == 4 and all(_has_polish_letters(b["vo"]) or b["vo"] for b in s15["beats"])
    spoken = " ".join(b["vo"] for b in s15["beats"])
    assert "Dawn Roast leczy poranny niepokój." in spoken  # the client's mandatory line is inserted verbatim — the Guardian decides
    assert s15["music"]["reference_title"] == "Sunrise Anthem"


def test_guardian_blocks_the_polish_script_then_auto_revise_converges_to_compliant_polish(run):
    before = run["guardian_before"]["report"]
    assert before["verdict"] == "block"
    assert {"claims.prohibited", "rights.unlicensed"} <= {f["rule_id"] for f in before["findings"]}
    assert any("Zakazany claim" in f["message"] for f in before["findings"]) and any(f["suggestion"].startswith("Użyj zatwierdzonego sformułowania") for f in before["findings"] if f["rule_id"] == "claims.prohibited")
    res = run["revised"]
    assert res["converged"] and res["report"]["verdict"] != "block" and len(res["iterations"]) <= 3
    assert any(f["op"] == "swap_music" for it in res["iterations"] for f in it["fixes"])
    revised = " ".join(b["vo"] for b in run["script15"]["beats"])
    assert "leczy" not in revised.lower() and "daje spokojniejszy początek poranka" in revised
    assert run["script15"]["music"]["title"].endswith("(library)") and not run["script15"]["timing_issues"]


def test_storyboard_is_polish_for_people_and_english_for_the_image_model(run):
    sb = run["storyboard"]
    assert sb["lang"] == "pl" and sb["title"] == "Storyboard — 15 s" and len(sb["shots"]) == 4
    assert _has_polish_letters(sb["style_bible"]["look"] + sb["style_bible"]["character_description"]) and sb["style_bible"]["palette_notes"].startswith("Paleta:")
    assert sb["style_bible_en"]["palette_notes"].startswith("Palette:")
    for sh in sb["shots"]:
        assert sh["framing"] in {"plan ogólny wprowadzający", "plan półzbliżony", "makro z płytką głębią ostrości", "plan średni", "centralne ujęcie produktu, spokojna wolna przestrzeń"}
        assert sh["description_en"] and not _has_polish_letters(sh["description_en"]) and sh["description"] != sh["description_en"]
        assert not _has_polish_letters(sh["image_prompt"]) and "No text" in sh["image_prompt"] and sh["description_en"] in sh["image_prompt"]
    assert sb["shots"][0]["super_text"] == "Wolniejszy start." and sum(1 for s in sb["shots"] if s["image_status"] == "ready") >= 3


def test_voice_over_follows_the_campaign_language_with_a_pl_pl_neural_voice(run):
    v = run["voice"]
    assert v["lang"] == "pl" and v["voice"] == "neural:pl-PL-ZofiaNeural" and v["title"] == "Lektor (pl)"
    assert len(v["lines"]) == 4 and all(ln["voice"] == "neural:pl-PL-ZofiaNeural" for ln in v["lines"])
    srt = run["srt"]
    assert "Średnio" in srt and f"w{NBSP}małych" in srt  # diacritics and typeset NBSP survive in the SRT
    assert all(c["text"] for c in v["captions"])


def test_spot_meets_the_delivery_spec_and_the_badge_is_polish(run):
    res, spot = run["render"], run["spot"]
    assert abs(res["duration"] - 14.9) <= 0.5 and abs(res["loudness_lufs"] - (-16.0)) <= 1.5
    p = spot["probe"]
    assert (p["video"]["codec"], p["video"]["width"], p["video"]["height"], p["audio"]["codec"]) == ("h264", 1280, 720, "aac")
    assert spot["lang"] == "pl" and run["spot_art"]["spec"]["disclosure_badge"] == "Wygenerowano przez AI"
    assert run["spot_art"]["spec"]["endcard"]["headline"] == "Obudź się powoli." and run["spot_art"]["spec"]["endcard"]["cta"] == f"Znajdź Dawn{NBSP}Roast w{NBSP}pobliżu"  # typeset: brand name and single-letter word glued
    assert spot["guardian"]["verdict"] in {"pass", "warn"}
    assert run["video"][4:8] == b"ftyp"


@needs_ffmpeg
def test_an_extracted_frame_shows_the_polish_caption_with_its_diacritics(run, tmp_path):
    mp4 = tmp_path / "pl.mp4"
    mp4.write_bytes(run["video"])
    art = run["spot_art"]["spec"]
    W, H = 1280, 720
    cue = next(Cue(**c) for c in art["captions"] if "Średnio" in c["text"])
    frame = np.asarray(Image.open(io.BytesIO(media.extract_frame(mp4, (cue.start + cue.end) / 2))).convert("RGB"))
    ov, x, y = overlays.render_caption(cue.text, W, H, "16:9")
    text_pixels = (ov[..., 3] > 250) & (ov[..., :3].min(axis=2) > 225)  # the light glyph pixels of the overlay
    assert text_pixels.sum() > 500
    crop = frame[y : y + ov.shape[0], x : x + ov.shape[1]]
    lit = (crop.min(axis=2) > 190)[text_pixels]
    assert lit.mean() > 0.85, f"caption glyphs not found in the frame ({lit.mean():.2f})"  # the frame really contains Ś-r-e-d-n-i-o …
    # the same caption without diacritics would be a different picture (glyphs are drawn, not replaced by boxes)
    plain, _, _ = overlays.render_caption(fold(cue.text), W, H, "16:9")
    assert plain.shape != ov.shape or not np.array_equal(plain, ov)
    end_frame = np.asarray(Image.open(io.BytesIO(media.extract_frame(mp4, art["scenes"][-1]["duration"] + sum(s["duration"] for s in art["scenes"][:-1]) + 0.9))).convert("RGB"))
    lay = overlays.endcard_layout(RenderSpec.model_validate(art), W, H)
    badge, bx, by = overlays.render_label("Wygenerowano przez AI", W, H, "16:9", "tl")
    glyphs = (badge[..., 3] > 250) & (badge[..., :3].min(axis=2) > 225)
    assert (end_frame[by : by + badge.shape[0], bx : bx + badge.shape[1]].min(axis=2) > 190)[glyphs].mean() > 0.85
    assert lay["headline_lines"] == ["Obudź się powoli."]


def test_localization_pl_to_en_keeps_the_brand_terms_translates_legal_lines_and_renders_an_english_spot(run):
    c, cid = run["client"], run["campaign"]["id"]
    r = c.post(f"/api/campaigns/{cid}/localization/generate?wait=true", json={"langs": ["en"], "render": True}, headers=PL)
    assert r.status_code == 200, r.text
    loc = next(x for x in c.get(f"/api/campaigns/{cid}/localization", headers=PL).json()["localizations"] if x["lang"] == "en")
    assert loc["source_lang"] == "pl" and loc["title"] == "Lokalizacja — angielski" and loc["tagline"] == "Wake up slowly"
    rows = {row["id"]: row for row in loc["lines"]}
    assert rows["b1:vo"]["source"] == "Zacznij dzień wolniej." and rows["b1:vo"]["text"] == "Start your day slower."
    assert all(row["status"] == "ok" and row["similarity"] >= 0.9 for row in rows.values()), [(k, v["status"], v["similarity"]) for k, v in rows.items()]  # back-translation (into Polish) matches the source
    assert rows["b1:vo"]["back_translation"] == "Zacznij dzień wolniej."
    assert "Dawn Roast" in rows["b2:vo"]["text"] and rows["cta"]["text"].startswith("Find Dawn Roast near you")  # do-not-translate brand name
    assert not loc["glossary_issues"] and loc["guardian"]["verdict"] in {"pass", "warn"}
    spot = next(s for s in c.get(f"/api/campaigns/{cid}/spot", headers=PL).json()["spots"] if s["lang"] == "en")
    assert spot["lineage_kind"] == "localized"
    art = c.get(f"/api/campaigns/{cid}/spot/{spot['id']}", headers=PL).json()["spec"]
    assert art["disclosure_badge"] == "AI-generated" and art["endcard"]["headline"] == "Wake up slowly"
    supers = [s["super_text"] for s in art["scenes"] if s["super_text"]]
    assert supers and not any(_has_polish_letters(x) for x in supers) and "Wolniejszy" not in " ".join(supers)  # supers follow the target language (not the Polish storyboard)
    assert all(NBSP not in cue["text"] for cue in art["captions"]) and not any(_has_polish_letters(cue["text"]) for cue in art["captions"])
    assert any(w for w in art["vo"] if "Start your day slower." in w["text"])


def test_localization_rejects_the_source_language_with_a_polish_message_and_lists_default_targets(run):
    c, cid = run["client"], run["campaign"]["id"]
    r = c.post(f"/api/campaigns/{cid}/localization/generate", json={"langs": ["pl"]}, headers=PL)
    err = r.json()["error"]
    assert r.status_code == 422 and err["code"] == "bad_language" and err["message"].startswith("Nieobsługiwane języki docelowe: pl")
    langs = c.get(f"/api/campaigns/{cid}/localization/languages", headers=PL).json()["languages"]
    assert {x["code"]: x["label"] for x in langs}["pl"] == "polski" and len(langs) == 8


def test_localization_en_to_pl_uses_the_polish_pack_and_the_polish_badge():
    app = create_app(Settings(spotlight_mode="offline", rate_limit_enabled=False, seed_on_start=True))
    en = {"X-Studio-Role": "creative", "X-Studio-User": "tester"}
    with TestClient(app) as c:
        cid = c.post("/api/campaigns", json={"name": "Dawn Roast EN to PL", "markets": ["US", "DE"], "channels": ["youtube", "meta"]}, headers=en).json()["id"]
        from spotlight.seed.data import DAWN_ROAST_BRIEF

        c.put(f"/api/campaigns/{cid}/brief", json={"raw_text": DAWN_ROAST_BRIEF}, headers=en)
        c.post(f"/api/campaigns/{cid}/brief/analyze", headers=en)
        c.post(f"/api/campaigns/{cid}/brief/answers", json={"answers": {"key_message": "A slower start, made well.", "cta": "Find Dawn Roast at northwind.example/dawn", "duration_targets": [15]}}, headers=en)
        assert c.post(f"/api/campaigns/{cid}/brief/finalize", headers=en).status_code == 200
        c.post(f"/api/campaigns/{cid}/strategy/generate?wait=true", json={}, headers=en)
        c.post(f"/api/campaigns/{cid}/script/generate?wait=true", json={"durations": [15]}, headers=en)
        s15 = c.get(f"/api/campaigns/{cid}/script", headers=en).json()["scripts"][0]
        assert c.post(f"/api/campaigns/{cid}/guardian/run", json={"artifact_id": s15["id"], "auto_revise": True}, headers=en).json()["converged"]
        r = c.post(f"/api/campaigns/{cid}/localization/generate?wait=true", json={"langs": ["pl"], "render": False}, headers={**en, "X-UI-Lang": "pl"})
        assert r.status_code == 200, r.text
        loc = c.get(f"/api/campaigns/{cid}/localization", headers=en).json()["localizations"][0]
        assert loc["source_lang"] == "en" and loc["lang"] == "pl" and loc["title"] == "Localization — Polish" and loc["tagline"] == "Obudź się powoli"
        rows = {row["id"]: row for row in loc["lines"]}
        assert rows["b1:vo"]["text"] == "Są poranki, które zasługują na wolniejszy początek." and rows["b1:vo"]["back_translation"] == "Some mornings deserve a slower start."
        assert all(row["status"] == "ok" for row in rows.values()) and rows["cta"]["text"] == "Znajdź Dawn Roast w pobliżu"
        assert loc["guardian"]["verdict"] in {"pass", "warn"}


# ------------------------------------------------------------------------------------------------ glossary / do-not-translate enforcement (unit)


class _FakeLLM:
    """A model that ignores the glossary: it translates the tagline its own way and drops the brand name."""

    def __init__(self, answers: dict[str, str]) -> None:
        self.answers = answers

    async def complete(self, **kw):
        from spotlight.features.cs10_localization import LocLine, LocOut

        return LocOut(lines=[LocLine(id=ln["id"], text=self.answers.get(ln["id"], ln["text"])) for ln in kw["context"]["lines"]], notes="fake")


class _FakeServices:
    def __init__(self, llm) -> None:
        self.llm = llm


async def test_glossary_and_do_not_translate_are_enforced_in_both_directions():
    from spotlight.domain import localize as lz
    from spotlight.features.cs10_localization import transcreate
    from spotlight.seed.data import KIT

    glossary = KIT["voice"]["glossary"]
    # PL -> EN: the model paraphrases the tagline and drops the brand name
    lines = [{"id": "a", "text": "Obudź się powoli."}, {"id": "b", "text": "Dawn Roast. Obudź się powoli."}]
    out, issues = await transcreate(_FakeServices(_FakeLLM({"a": "Wake up gently.", "b": "Brew. Wake up gently."})), lines, "en", glossary, "", "pl")
    assert "Wake up slowly" in out["a"] and "Dawn Roast" in out["b"]  # repaired deterministically
    kinds = {(i["line"], i["rule"]) for i in issues}
    assert ("a", "glossary") in kinds and ("b", "glossary") in kinds and ("b", "do_not_translate") in kinds
    assert all(i["repaired"] for i in issues) and issues[0]["key"].startswith("loc.issue.")
    # EN -> PL
    out2, issues2 = await transcreate(_FakeServices(_FakeLLM({"a": "Obudź się delikatnie."})), [{"id": "a", "text": "Wake up slowly."}], "pl", glossary, "", "en")
    assert "Obudź się powoli" in out2["a"] and issues2[0]["rule"] == "glossary" and issues2[0]["params"]["required"] == "Obudź się powoli"
    # the checks themselves
    assert lz.forced_translations("Obudź się powoli.", glossary, "de", "pl") == [("Obudź się powoli", "Wach langsam auf")]
    assert lz.forced_translations("Obudz sie powoli", glossary, "en", "pl") == [("Obudź się powoli", "Wake up slowly")]  # typed without diacritics
    assert lz.forced_translations("Wake up slowly.", glossary, "pl") == [("Wake up slowly", "Obudź się powoli")]
    assert lz.check_terms("Dawn Roast.", "Roast.", glossary, "en", "pl")[0]["rule"] == "do_not_translate"
    assert lz.translate_legal("Zawiera kofeinę. Niezalecane dla dzieci i kobiet w ciąży.", "pl", "en") == "Contains caffeine. Not recommended for children or pregnant women."
    assert lz.translate_legal("Contains caffeine. Not recommended for children or pregnant women.", "en", "pl") == "Zawiera kofeinę. Niezalecane dla dzieci i kobiet w ciąży."
    assert lz.translate_legal("Źródło: northwind.example/sustainability", "pl", "de") == "Quelle: northwind.example/sustainability" and lz.translate_legal("Keep me", "pl", "en") == "Keep me"


def test_offline_phrasebook_round_trips_polish_through_english_and_german():
    from spotlight.features.cs10_localization import _stub_back, _stub_translate_text

    for pl in ("Zacznij dzień wolniej.", "Dla tych, którzy wstają przed słońcem.", "Dziesięć cichych minut, zanim zacznie się dzień."):
        for lang in ("en", "de", "fr", "es", "it", "pt", "nl"):
            tr = _stub_translate_text(pl, lang, "pl")
            assert tr != pl and _stub_back(tr, lang, "pl") == pl, (pl, lang, tr)
    assert _stub_translate_text("Znajdź Dawn Roast w pobliżu", "de", "pl") == "Finde Dawn Roast in deiner Nähe"  # no final period when the source has none
    assert _stub_translate_text("Dawn Roast", "en", "pl") == "Dawn Roast"  # brand names pass through
    assert _stub_translate_text("Some mornings deserve a slower start.", "pl") == "Są poranki, które zasługują na wolniejszy początek."  # the English direction is unchanged


def test_back_translation_similarity_compares_polish_stems_and_leaves_english_untouched():
    inflected = ("Wolniejszy początek poranka", "Wolniejszego początku poranku")
    assert similarity(*inflected, "pl") > 0.7 > similarity(*inflected)  # "początek" / "początku" count as one word in the QA check
    assert similarity("Dawn Roast. Średnie palenie.", "Zupełnie inne zdanie o czymś innym", "pl") < 0.2  # unrelated lines still fail it
    assert similarity("A slower start", "A slower start, done well") == similarity("A slower start", "A slower start, done well", "en")


def test_polish_scorecard_localization_and_provenance_follow_the_campaign(run):
    c, cid = run["client"], run["campaign"]["id"]
    card = c.post(f"/api/campaigns/{cid}/scorecard", json={"spot_id": run["spot"]["id"]}, headers=PL).json()
    assert card["title"] == "Karta oceny przed emisją" and card["lang"] == "pl"
    assert all(_has_polish_letters(v["reaction"]) for v in card["panel"]) and all(_has_polish_letters(s) or s for s in card["suggestions"])
    assert card["label"].startswith("Predykcja / symulacja")
    manifest = c.get(f"/api/provenance/assets/{run['spot']['assets']['video']}", headers=PL).json()
    assert manifest["manifest"]["assertions"]["ai_disclosure"]["burned_in_badge"] == "Wygenerowano przez AI"
    assert manifest["manifest"]["assertions"]["ai_disclosure"]["labels"]["notice"].startswith("Illustrative")  # machine fields stay English
    assert manifest["summary"]["lang"] == "pl" and manifest["summary"]["headline"].startswith("Manifest pochodzenia") and any("Ed25519" in line for line in manifest["summary"]["lines"])
    assert c.post("/api/provenance/verify", json={"asset_id": run["spot"]["assets"]["video"], "tamper_test": True}, headers=PL).json()["tamper_detected"] is True


@needs_ffmpeg
def test_format_factory_versions_carry_polish_labels_and_notes_at_read_time_and_english_text_is_unchanged(run):
    c, cid = run["client"], run["campaign"]["id"]
    r = c.post(f"/api/campaigns/{cid}/formats/generate?wait=true", json={"aspects": ["9:16"], "cutdowns": [6]}, headers=PL)
    assert r.status_code == 200, r.text
    pl = {n["kind"]: n for n in c.get(f"/api/campaigns/{cid}/formats/tree", headers=PL).json()["nodes"] if n["parent_id"]}
    en = {n["kind"]: n for n in c.get(f"/api/campaigns/{cid}/formats/tree", headers={**PL, "X-UI-Lang": "en"}).json()["nodes"] if n["parent_id"]}
    assert en["format"]["notes"] == ["reframed 16:9 → 9:16 with per-scene focal points"] and pl["format"]["notes"] == ["Przekadrowano 16:9 → 9:16, ustawiając punkt skupienia osobno dla każdej sceny"]
    assert en["cutdown"]["label"] == "16:9 · 6s cutdown" and pl["cutdown"]["label"] == "16:9 · wersja skrócona 6 s"
    assert en["cutdown"]["notes"][0].endswith("scenes kept by priority (hook → product → proof)") and pl["cutdown"]["notes"][0].startswith("Zachowano ") and "scen według priorytetu" in pl["cutdown"]["notes"][0]
    dropped_en = [x for x in en["cutdown"]["notes"] if x.startswith("dropped VO lines that no longer fit: ")]
    dropped_pl = [x for x in pl["cutdown"]["notes"] if x.startswith("Pominięto kwestie lektora")]
    assert len(dropped_en) == len(dropped_pl) == 1  # a 6 s cut of a 15 s spot cannot keep every voice-over line
    assert "['v" in dropped_en[0]  # English keeps its legacy wording
    assert not re.search(r"[\[\]']", dropped_pl[0]) and re.search(r": v\d+( i v\d+|(, v\d+)+ i v\d+)?$", dropped_pl[0]), dropped_pl[0]  # plain ids, not a Python list
    root = next(n for n in c.get(f"/api/campaigns/{cid}/formats/tree", headers=PL).json()["nodes"] if not n["parent_id"])
    assert root["label"] == "16:9"  # the master is named by its aspect in every language


def test_music_candidates_overview_and_insight_labels_are_localized_for_the_viewer(run):
    c, cid = run["client"], run["campaign"]["id"]
    music = c.get(f"/api/campaigns/{cid}/audio/music", headers=PL).json()["candidates"]
    en_music = c.get(f"/api/campaigns/{cid}/audio/music", headers={**PL, "X-UI-Lang": "en"}).json()["candidates"]
    lib = next(m for m in music if m["rights_id"] == "mus-dawn-pad")
    assert lib["licensor"] == "Spotlight Procedural Library (generated, CC0)" and lib["licensor_label"] == "Biblioteka proceduralna Spotlight (generowana, CC0)"
    assert next(m for m in en_music if m["rights_id"] == "mus-dawn-pad")["licensor_label"] == lib["licensor"]
    cards = {x["id"]: x for x in c.get("/api/studio/overview", headers=PL).json()["campaigns"]}
    assert cards[cid]["language"] == "pl" and cards["dawn-roast-launch"]["language"] == "en"
    from spotlight.domain import perfsim as ps

    ev = {"dimension": "platform", "winner": "simulated", "metric": "ctr", "lift_pct": 17.0, "p_value": 0.001, "n": 1000}
    assert "„symulowana”" in (ps.render_statement(ev, "pl") or "") and "“simulated”" in (ps.render_statement(ev, "en") or "")
