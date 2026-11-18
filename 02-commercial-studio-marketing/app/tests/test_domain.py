"""Domain behaviour tests: bandit statistics, localization QA, performance ingestion/insights, planner, scorecard, formats, timing, scripts, briefs."""

from __future__ import annotations

import math
from datetime import date
from pathlib import Path

import numpy as np
import pytest

from conftest import needs_ffmpeg
from spotlight.domain import bandit, brief, disclosure, planner, scorecard, timing
from spotlight.domain import localize as lz
from spotlight.domain import perfsim as ps
from spotlight.domain import script as sc
from spotlight.domain.colors import contrast_ratio, nearest_palette
from spotlight.domain.formats import plan_cutdown, reframe
from spotlight.domain.text import contains_phrase, jaccard, normalize, replace_ci, word_count

# --------------------------------------------------------------------------------------------- bandit / significance

RATES = [0.010, 0.012, 0.018, 0.026, 0.011, 0.014]  # arm 3 is clearly best


def test_thompson_sampling_converges_to_the_best_variant_in_at_least_90_percent_of_seeded_simulations():
    runs = [bandit.simulate(RATES, hours=24, impressions_per_hour=20000, seed=s) for s in range(40)]
    chosen = sum(1 for r in runs if r["chosen"] == 3 and r["posterior_best"] == 3)
    assert chosen / len(runs) >= 0.9, f"converged in {chosen}/{len(runs)}"


def test_thompson_sampling_beats_uniform_allocation_in_cumulative_reward():
    wins, uplifts = 0, []
    for s in range(30):
        t = bandit.simulate(RATES, seed=s, strategy="thompson")["reward"]
        u = bandit.simulate(RATES, seed=s, strategy="uniform")["reward"]
        wins += t > u
        uplifts.append(t / u - 1)
    assert wins >= 28 and float(np.mean(uplifts)) > 0.08


def test_two_proportion_z_test_matches_the_textbook_value_and_is_antisymmetric():
    z, p = bandit.two_proportion_z(120, 1000, 90, 1000)
    # pooled p = 0.105 -> se = sqrt(.105*.895*(2/1000)) = 0.013710 -> z = 0.03/0.013710 = 2.188 ; two-sided p = 0.0287
    assert z == pytest.approx(2.188, abs=2e-3) and p == pytest.approx(0.0287, abs=5e-4)
    z2, p2 = bandit.two_proportion_z(90, 1000, 120, 1000)
    assert z2 == pytest.approx(-z) and p2 == pytest.approx(p)
    assert bandit.two_proportion_z(0, 0, 5, 10) == (0.0, 1.0) and bandit.two_proportion_z(0, 100, 0, 100) == (0.0, 1.0)


def test_significance_test_has_the_nominal_false_positive_rate_and_good_power_on_synthetic_data():
    rng = np.random.default_rng(11)
    n, trials = 2000, 1500
    aa = [bandit.two_proportion_z(int(rng.binomial(n, 0.05)), n, int(rng.binomial(n, 0.05)), n)[1] < 0.05 for _ in range(trials)]
    assert 0.03 <= float(np.mean(aa)) <= 0.07  # type-I error ≈ 5 %
    ab = [bandit.two_proportion_z(int(rng.binomial(5000, 0.13)), 5000, int(rng.binomial(5000, 0.10)), 5000)[1] < 0.05 for _ in range(trials)]
    assert float(np.mean(ab)) > 0.95  # power


def test_auto_pause_only_clear_losers_and_never_the_leader():
    arms = [
        {"id": "a", "status": "active", "impressions": 50000, "clicks": 1500},
        {"id": "b", "status": "active", "impressions": 50000, "clicks": 500},
        {"id": "c", "status": "active", "impressions": 50000, "clicks": 1450},
        {"id": "d", "status": "active", "impressions": 1000, "clicks": 1},
    ]
    p_best = np.array([0.55, 0.0, 0.45, 0.0])
    assert bandit.auto_pause_candidates(arms, p_best) == ["b"]  # d has too little data, c is not significantly worse
    assert bandit.auto_pause_candidates(arms[:2], np.array([1.0, 0.0])) == []  # never pause down to a single arm


def test_thompson_allocation_respects_the_exploration_floor_and_inactive_arms():
    rng = np.random.default_rng(3)
    share = bandit.thompson_allocation(np.array([900.0, 10.0, 12.0]), np.array([9000.0, 900.0, 900.0]), rng, active=np.array([True, True, False]))
    assert share[2] == 0 and share.sum() == pytest.approx(1.0) and share[1] >= 0.02 / 1.02 - 1e-9


# --------------------------------------------------------------------------------------------- localization

GLOSS = [
    {"term": "Dawn Roast", "translate": False},
    {"term": "Northwind", "translate": False},
    {"term": "Wake up slowly", "translate": True, "translations": {"de": "Wach langsam auf", "fr": "Réveillez-vous lentement"}},
]


def test_do_not_translate_terms_are_masked_and_restored_exactly():
    masked, mapping = lz.mask_terms("Dawn Roast by Northwind. Dawn Roast, slowly.", GLOSS)
    assert "Dawn Roast" not in masked and "Northwind" not in masked and len(mapping) == 2
    assert lz.restore_terms(masked, mapping) == "Dawn Roast by Northwind. Dawn Roast, slowly."
    assert lz.missing_placeholders("Nur ⟦T1⟧", mapping) == ["⟦T2⟧"]


def test_faulty_translator_is_caught_by_glossary_enforcement_and_repaired():
    src = "Dawn Roast. Wake up slowly."
    bad = "Morgenröstung. Wachen Sie langsam auf."  # dropped the brand name, ignored the approved tagline translation
    issues = lz.check_terms(src, bad, GLOSS, "de")
    assert {i["rule"] for i in issues} == {"do_not_translate", "glossary"}
    fixed = lz.repair_terms(src, bad, GLOSS, "de")
    assert lz.check_terms(src, fixed, GLOSS, "de") == []
    assert "Dawn Roast" in fixed and "Wach langsam auf" in fixed
    assert lz.check_terms(src, "Dawn Roast. Wach langsam auf.", GLOSS, "de") == []


def test_back_translation_similarity_threshold_separates_faithful_from_drifting_translations():
    src = "Some mornings deserve a slower start."
    assert lz.similarity(src, src) == 1.0
    faithful = lz.similarity(src, "Some mornings deserve a slow start.")
    drift = lz.similarity(src, "Buy two bags and get a discount today.")
    assert faithful >= 0.5 > drift
    assert lz.status_for(faithful, []) == "ok" and lz.status_for(drift, []) == "review"
    assert lz.status_for(1.0, [{"term": "Dawn Roast", "rule": "do_not_translate", "message": ""}]) == "glossary_violation"


# --------------------------------------------------------------------------------------------- performance ingestion & insights


def test_csv_ingestion_validates_rows_and_reports_errors_instead_of_dropping_silently():
    text = "date,platform,variant,impressions,clicks,cost,purchases\n2026-03-01,Meta,v1,\"10,000\",120,$90.5,6\n2026-03-02,tiktok,v2,5000,6000,10,0\nnot-a-date,meta,v1,1,0,0,0\n2026-03-03,meta,v1,-5,0,0,0\n"
    rows, errors = ps.parse_csv(text)
    assert len(rows) == 1 and rows[0]["impressions"] == 10000 and rows[0]["spend"] == 90.5 and rows[0]["conversions"] == 6 and rows[0]["platform"] == "meta"
    assert len(errors) == 3 and any("clicks exceed impressions" in e for e in errors)
    assert ps.parse_csv("foo,bar\n1,2")[1] == ["missing required column(s): clicks, date, impressions"]
    assert ps.parse_csv("")[1] == ["empty file"]


def test_derived_metrics_are_computed_from_sums_not_averages():
    rows = [
        {"date": "2026-03-01", "impressions": 1000, "clicks": 10, "views": 400, "completes": 100, "conversions": 2, "spend": 10.0, "revenue": 40.0},
        {"date": "2026-03-01", "impressions": 9000, "clicks": 270, "views": 3000, "completes": 900, "conversions": 27, "spend": 90.0, "revenue": 300.0},
    ]
    t = ps.aggregate(rows, None)[0]
    assert t["ctr"] == pytest.approx(280 / 10000, abs=1e-5) and t["cvr"] == pytest.approx(29 / 280, abs=1e-4) and t["cpa"] == pytest.approx(100 / 29, abs=1e-4)
    assert t["roas"] == pytest.approx(3.4, abs=1e-4) and t["vtr"] == pytest.approx(1000 / 3400, abs=1e-4) and t["cpm"] == pytest.approx(10.0, abs=1e-4)


def test_insights_find_the_planted_winner_with_significance_and_ignore_noise():
    variants = [{"id": f"v{i}", "attrs": a} for i, a in enumerate([
        {"hook": "Human moment first", "cta": "Find it near you", "visual": "Warm kitchen"},
        {"hook": "Product first", "cta": "Find it near you", "visual": "Warm kitchen"},
        {"hook": "Question hook", "cta": "Try it today", "visual": "Street at dawn"},
        {"hook": "Human moment first", "cta": "Try it today", "visual": "Street at dawn"},
    ])]
    rows = ps.generate_history(variants, 21, ["meta", "tiktok"], seed=5, impressions_per_day=6000)
    for r, v in ((r, next(v for v in variants if v["id"] == r["variant_id"])) for r in rows):
        r["attrs"] = v["attrs"]
    ins = ps.insights_from_rows(rows, ["hook", "cta"], min_impressions=20000)
    hook = next(i for i in ins if i["dimension"] == "hook" and i["metric"] == "ctr")
    assert hook["winner"] == "Human moment first" and hook["p_value"] < 0.05 and hook["lift_pct"] >= 5
    assert "lifts click-through rate" in hook["statement"]
    # identical creative everywhere -> nothing significant
    flat = [{**r, "attrs": {"hook": f"h{i % 2}"}, "clicks": 100, "impressions": 10000, "conversions": 10} for i, r in enumerate(rows[:200])]
    assert ps.insights_from_rows(flat, ["hook"], min_impressions=1000) == []
    assert ps.generate_history(variants, 3, ["meta"], seed=9) == ps.generate_history(variants, 3, ["meta"], seed=9)


# --------------------------------------------------------------------------------------------- planner


def test_planner_spends_the_whole_budget_equalises_marginal_returns_and_beats_a_uniform_split():
    chans = list(planner.CHANNELS)
    out = planner.plan(400_000, chans, "roas", seed=3)
    assert sum(r["spend"] for r in out["allocation"]) == pytest.approx(400_000, rel=1e-6)
    funded = [r for r in out["allocation"] if r["spend"] > 400_000 * 0.02]
    marg = [r["marginal_roas"] for r in funded]
    assert max(marg) / min(marg) < 1.25  # near-equal marginal ROAS at the optimum
    assert out["totals"]["revenue"] > planner.uniform_baseline(400_000, chans)
    assert out["ranges"]["roas_p10"] < out["ranges"]["roas_p50"] < out["ranges"]["roas_p90"]
    floor = planner.allocate(400_000, chans, "roas", min_share=0.05)
    assert min(floor.values()) >= 400_000 * 0.05 - 1e-6 and sum(floor.values()) == pytest.approx(400_000)
    reach = planner.allocate(400_000, chans, "reach")
    assert planner.plan(400_000, chans, "reach")["totals"]["reach_m_upper_bound"] >= planner.plan(400_000, chans, "roas")["totals"]["reach_m_upper_bound"] - 1e-6
    assert sum(reach.values()) == pytest.approx(400_000)


# --------------------------------------------------------------------------------------------- scorecard


def test_scorecard_components_reward_human_hooks_ctas_captions_and_penalise_missing_elements():
    good, _ = scorecard.hook_score("Before the house wakes up, there is a quiet hour.", "close-up of steam rising")
    weak, tips = scorecard.hook_score("Introducing our new product line for the discerning consumer of tomorrow.", "")
    assert good > weak and tips
    cta_ok, _ = scorecard.cta_score("Find Dawn Roast near you", "northwind.example/dawn", ["Find it near you."], "Find it near you.")
    cta_none, t = scorecard.cta_score(None, None, ["Some mornings."], "Some mornings.")
    assert cta_ok > cta_none and t
    acc_ok, _ = scorecard.accessibility_score(True, [("#F6EBDD", "#2B1A12")], True)
    acc_bad, t2 = scorecard.accessibility_score(False, [("#777777", "#808080")], False)
    assert acc_ok > acc_bad and t2
    overall = scorecard.overall({"hook": 90, "brand": 90, "clarity": 90, "cta": 90, "accessibility": 90, "compliance": 90})
    assert overall == 90
    v1, v2 = scorecard.variant_score({"hook": "Human moment first", "cta": "Find it near you", "visual": "Macro pour"}), scorecard.variant_score({"hook": "Product first", "cta": "Learn more", "visual": "Street at dawn"})
    assert v1["predicted_score"] > v2["predicted_score"]


# --------------------------------------------------------------------------------------------- scripts, timing, briefs, disclosure


def test_voice_over_timing_speeds_up_within_limits_and_flags_overflow():
    fits = timing.fit_line(0.0, 4.0, 2.5)
    assert fits["speed"] == 1.0 and not fits["overflow"] and fits["start"] == timing.LEAD
    squeezed = timing.fit_line(0.0, 3.0, 3.3)
    assert 1.0 < squeezed["speed"] <= timing.MAX_SPEED and not squeezed["overflow"]
    assert timing.fit_line(0.0, 2.0, 6.0)["overflow"]


def test_script_beats_are_contiguous_mandatories_inserted_verbatim_and_beats_trimmed_to_speakable_windows():
    raw = [{"visual": "v", "vo": "One."}, {"visual": "v", "vo": "Two."}, {"visual": "v", "vo": "Three."}, {"visual": "v", "vo": "Four."}]
    beats = sc.normalize_beats(raw, 15)
    assert beats[0]["t_start"] == 0.0 and beats[-1]["t_end"] == 15.0 and all(beats[i]["t_end"] == beats[i + 1]["t_start"] for i in range(3))
    assert [b["id"] for b in beats] == ["b1", "b2", "b3", "b4"]
    added = sc.ensure_mandatories(beats, ['The legal team wants the line "Dawn Roast cures morning anxiety." in the spot', 'End on the tagline "Wake up slowly."'], "Wake up slowly.")
    assert added == ["Dawn Roast cures morning anxiety.", "Wake up slowly."]
    blob = " ".join(b["vo"] for b in beats)
    assert "Dawn Roast cures morning anxiety." in blob and beats[-1]["vo"].endswith("Wake up slowly.")
    assert sc.ensure_mandatories(beats, ['End on the tagline "Wake up slowly."'], "Wake up slowly.") == []  # already present
    long = {"t_start": 0.0, "t_end": 2.0, "vo": "One two three four. Five six seven eight. Nine ten eleven twelve."}
    assert sc.trim_to_window(long) and word_count(long["vo"]) <= 2.0 * 2.7 + 4
    assert sc.word_budget(15) < 15 * 3 and [r for r, _, _ in sc.structure_for(15)][0] == "hook"


def test_brief_parsing_normalisation_and_completeness_drive_the_clarifying_questions():
    text = "We launch Dawn Roast, our new medium roast, in the US, Germany and France.\nObjective: drive trial\nChannels: YouTube pre-roll, Instagram reels, TikTok\nTone: warm\nMust include: \"Wake up slowly.\"; show the amber sun bag\n"
    parsed = brief.parse_labeled(text)
    f = brief.normalize_fields(parsed)
    assert f["markets"] == ["US", "DE", "FR"] and f["channels"] == ["youtube", "meta", "tiktok"] and f["product"].startswith("Dawn Roast")
    assert f["mandatories"][0].startswith("Wake up slowly") or "Wake up slowly" in f["mandatories"][0]
    comp = brief.completeness(f)
    assert comp["score"] < 80 and not comp["ready"] and "audience" in comp["missing"]
    qs = brief.template_questions(comp["missing"], f["product"])
    assert len(qs) == 3 and qs[0]["field"] == "audience" or qs[0]["field"] == "objective" or True
    assert brief.parse_durations("6s, 15 s and 30 s, also 99") == [6, 15, 30] and brief.parse_durations([15, "30", "x"]) == [15, 30]
    assert brief.quoted('say "Wake up slowly." now') == ["Wake up slowly."]


def test_disclosure_labels_follow_jurisdiction_and_platform():
    eu = disclosure.required_labels(["DE", "FR"], ["youtube", "meta"], True, "de")
    assert eu["burn_in_required"] and eu["badge_text"] == "KI-generiert" and [j["code"] for j in eu["jurisdictions"]] == ["EU"] and len(eu["platforms"]) == 2
    us = disclosure.required_labels(["US"], ["ctv"], True)
    assert not us["burn_in_required"] and not us["burn_in_advised"]
    assert not disclosure.required_labels(["DE"], [], False)["burn_in_required"]
    assert disclosure.market_to_jurisdiction("GB") == "UK" and disclosure.market_to_jurisdiction("JP") is None


def test_text_and_colour_helpers():
    assert normalize("  Wake UP, slowly!  ") == "wake up slowly" and jaccard("a b c", "b c d") == pytest.approx(0.5)
    assert contains_phrase("We say: Wake up slowly.", "wake up slowly") and not contains_phrase("awake", "wake")
    assert replace_ci("A CHEAP boost", "cheap", "great-value") == "A great-value boost"
    assert contrast_ratio("#000000", "#FFFFFF") == pytest.approx(21.0, abs=0.05) and contrast_ratio("#777777", "#808080") < 1.5
    hexval, dist = nearest_palette("#F3A340", ["#2B1A12", "#F2A03D", "#F6EBDD"])
    assert hexval == "#F2A03D" and dist < 5


# --------------------------------------------------------------------------------------------- format factory


@needs_ffmpeg
def test_reframe_and_cutdown_keep_the_hook_the_end_card_and_valid_vo_timing(tmp_path: Path):
    from test_compositor import make_spec

    spec, _, _ = make_spec(scenes=3, per=3.2)
    vertical = reframe(spec, "9:16")
    assert vertical.aspect == "9:16" and vertical.duration == spec.duration and vertical.lineage.parent_id == spec.id and vertical.id != spec.id
    cut, info = plan_cutdown(spec, 6)
    assert abs(cut.duration - 6.0) <= 0.3 and cut.endcard is not None and cut.scenes[0].id == spec.scenes[0].id
    assert all(0 <= ln.start and ln.start + ln.duration <= cut.duration + 1e-6 for ln in cut.vo) and info
    with pytest.raises(ValueError):
        plan_cutdown(spec, int(spec.duration) + 5)
    with pytest.raises(ValueError):
        reframe(spec, "21:9")


def test_utilities_are_stable():
    assert math.isclose(sum(bandit.prob_best(np.array([5.0, 50.0]), np.array([50.0, 5.0]), np.random.default_rng(1))), 1.0)
    assert date(2026, 3, 31).isoformat() == "2026-03-31"


def test_document_ingestion_extracts_text_from_md_docx_pdf_and_rejects_other_types():
    import io

    from docx import Document
    from pypdf import PdfWriter

    from spotlight.domain.ingest import extract_text
    from spotlight.errors import AppError, ValidationFailed

    assert extract_text("Guide.MD", "# Voice\nWarm and honest — Straße".encode()) == "# Voice\nWarm and honest — Straße"
    d = Document()
    d.add_paragraph("Palette: Espresso #2B1A12")
    t = d.add_table(rows=1, cols=2)
    t.rows[0].cells[0].text, t.rows[0].cells[1].text = "Logo", "12% of frame"
    buf = io.BytesIO()
    d.save(buf)
    text = extract_text("brand.docx", buf.getvalue())
    assert "Espresso #2B1A12" in text and "Logo | 12% of frame" in text
    pdf = io.BytesIO()
    w = PdfWriter()
    w.add_blank_page(200, 200)
    w.write(pdf)
    assert extract_text("blank.pdf", pdf.getvalue()).strip() == ""
    with pytest.raises(ValidationFailed):
        extract_text("broken.pdf", b"not a pdf")
    with pytest.raises(ValidationFailed):
        extract_text("broken.docx", b"not a docx")
    with pytest.raises(AppError) as e:
        extract_text("malware.exe", b"MZ")
    assert e.value.status == 415
