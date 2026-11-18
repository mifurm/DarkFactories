"""Brand Guardian behavioural tests: seeded violations are caught, compliant assets pass, auto-revise converges."""

from __future__ import annotations

import pytest

from spotlight.domain import colors as col
from spotlight.domain.claims import ClaimRule, find_hits, market_matches
from spotlight.domain.guardian import (
    BrandRules,
    Disclosure,
    GuardianContext,
    GuardianSubject,
    MusicUse,
    SafetyObs,
    StockUse,
    TalentUse,
    TextItem,
    VisualItem,
    apply_fix,
    build_report,
    revise_once,
    run_rules,
)
from spotlight.domain.rights import RightsEntry, check_use, expiring, find_entry
from spotlight.seed import data


@pytest.fixture
def ctx() -> GuardianContext:
    v = data.KIT["voice"]
    return GuardianContext(
        brand=BrandRules(palette=[p["hex"] for p in data.PALETTE], forbidden_words=v["forbidden_words"], replacements=v["replacements"], max_exclamations=1),
        claims=[ClaimRule(**{k: x for k, x in c.items() if k in ClaimRule.model_fields}) for c in data.claims()],
        rights=[RightsEntry(**{k: x for k, x in r.items() if k in RightsEntry.model_fields}) for r in data.rights()],
        today="2026-11-17",
    )


def subject(**kw) -> GuardianSubject:
    base = {"type": "script", "campaign_id": "c1", "markets": ["US"], "channels": ["youtube"], "category": "beverage", "air_start": "2026-12-01", "air_end": "2027-01-31"}
    base.update(kw)
    return GuardianSubject(**base)


def rules(findings):
    return {f.rule_id for f in findings if f.severity == "block"}


def test_prohibited_health_claim_is_blocked_with_a_compliant_fix(ctx):
    s = subject(texts=[TextItem(id="b1:vo", text="Dawn Roast cures morning anxiety.")])
    fs = run_rules(s, ctx)
    f = next(f for f in fs if f.rule_id == "claims.prohibited")
    assert f.severity == "block" and "cures morning anxiety" in f.evidence
    assert f.fix and f.fix["op"] == "replace_text" and f.fix["replace"] == "brings a calmer start to your morning"
    assert build_report(s, ctx, fs).verdict == "block"


def test_missing_caffeine_disclaimer_blocks_and_adding_it_clears(ctx):
    s = subject(texts=[TextItem(id="b1:vo", text="A little energy for the early shift.")])
    fs = run_rules(s, ctx)
    assert "claims.missing_disclaimer" in rules(fs)
    s.texts.append(TextItem(id="legal-0", kind="legal", text="Contains caffeine. Not recommended for children or pregnant women."))
    assert "claims.missing_disclaimer" not in rules(run_rules(s, ctx))


def test_forbidden_word_is_blocked_and_replaced_from_the_voice_profile(ctx):
    s = subject(texts=[TextItem(id="b1:vo", text="A cheap way to start the day.")])
    f = next(f for f in run_rules(s, ctx) if f.rule_id == "voice.forbidden_word")
    assert f.severity == "block" and f.fix["replace"] == "great value"


def test_off_palette_colour_is_blocked_and_snapped_to_the_brand_palette(ctx):
    s = subject(type="spot", has_video=True, visuals=[VisualItem(id="endcard", kind="endcard", colors=["#FF2BD6", "#F6EBDD"])])
    fs = run_rules(s, ctx)
    f = next(f for f in fs if f.rule_id == "visual.off_palette")
    assert f.severity == "block" and f.evidence == "#FF2BD6"
    assert apply_fix(s, f.fix, ctx)
    assert not [x for x in run_rules(s, ctx) if x.rule_id == "visual.off_palette"]


def test_brand_colours_and_neutrals_pass_the_palette_check(ctx):
    s = subject(type="spot", visuals=[VisualItem(id="endcard", colors=[p["hex"] for p in data.PALETTE] + ["#FFFFFF", "#000000"])])
    assert not [f for f in run_rules(s, ctx) if f.rule_id == "visual.off_palette"]


def test_unlicensed_music_cue_is_blocked_and_swapped_for_a_licensed_library_track(ctx):
    s = subject(music=[MusicUse(title="Sunrise Anthem", mood="warm")])
    f = next(f for f in run_rules(s, ctx) if f.rule_id == "rights.unlicensed")
    assert f.severity == "block" and f.fix["op"] == "swap_music" and f.fix["title"].endswith("(library)")
    assert apply_fix(s, f.fix, ctx)
    assert s.music[0].title == "Slow Ember (library)"  # mood-matched
    assert not [x for x in run_rules(s, ctx) if x.check == "rights" and x.severity == "block"]


def test_expired_talent_consent_is_blocked(ctx):
    s = subject(talent=[TalentUse(name="Jonas Weber")], markets=["DE"])
    fs = run_rules(s, ctx)
    f = next(f for f in fs if f.rule_id == "rights.expired")
    assert f.severity == "block" and "expired" in f.message


def test_talent_without_ai_consent_and_territory_and_channel_limits_are_enforced(ctx):
    maya = find_entry(ctx.rights, "talent", "Maya Okafor")
    assert maya is not None
    assert any(v.code == "rights.no_ai_consent" for v in check_use(maya, ["US"], ["youtube"], ai_synthesis=True, usage="likeness"))
    assert not any(v.severity == "block" for v in check_use(maya, ["US", "DE"], ["youtube"], "2026-12-01", "2027-06-01", ai_synthesis=True, usage="voice"))
    stock = find_entry(ctx.rights, "stock", "Stock photo: latte art hero")
    assert any(v.code == "rights.territory" for v in check_use(stock, ["DE"], []))
    golden = find_entry(ctx.rights, "music", "Golden Hour Pop (artist track)")
    codes = {v.code for v in check_use(golden, ["US"], ["youtube"], "2026-12-01", "2027-01-31")}
    assert {"rights.not_active", "rights.channel"} <= codes


def test_stock_territory_violation_is_found_through_the_guardian(ctx):
    s = subject(markets=["DE"], stock=[StockUse(title="Stock photo: latte art hero")])
    assert "rights.territory" in rules(run_rules(s, ctx))


def test_content_safety_hit_blocks_and_low_severity_warns(ctx):
    s = subject(texts=[TextItem(id="t1", text="I will stab you."), TextItem(id="t2", text="A fight for the last cup.")])
    ctx.safety = SafetyObs(text={"t1": {"max": 4, "categories": {"Violence": 4}}, "t2": {"max": 2, "categories": {"Violence": 2}}})
    fs = run_rules(s, ctx)
    assert any(f.rule_id == "safety.text" and f.severity == "block" and f.item_id == "t1" for f in fs)
    assert any(f.rule_id == "safety.text" and f.severity == "warn" and f.item_id == "t2" for f in fs)
    ctx.safety = SafetyObs(text={"t1": {"max": 0, "protected": True, "categories": {}}})
    assert "safety.protected_material" in rules(run_rules(s, ctx))
    ctx.safety = SafetyObs(text={"t1": {"max": 0, "attack": True, "categories": {}}})
    assert "safety.prompt_injection" in rules(run_rules(s, ctx))


def test_compliant_asset_passes(ctx):
    s = subject(
        type="spot", has_video=True, captions_present=True, markets=["US"], disclosure=Disclosure(ai_generated=True, label_present=True),
        texts=[TextItem(id="v1", kind="vo", text="Some mornings deserve a slower start."), TextItem(id="v2", kind="vo", text="Dawn Roast. Roasted in small batches."), TextItem(id="v3", kind="vo", text="Wake up slowly.")],
        music=[MusicUse(title="Dawn Pad (library)", mood="calm")], talent=[TalentUse(name="Maya Okafor")],
        visuals=[VisualItem(id="endcard", kind="endcard", colors=["#2B1A12", "#F6EBDD", "#F2A03D"], contrast_pairs=[{"fg": "#F6EBDD", "bg": "#2B1A12", "label": "text"}])],
    )
    report = build_report(s, ctx)
    assert report.verdict == "pass", [(f.rule_id, f.message) for f in report.findings]
    assert report.score == 100


def test_eu_market_blocks_unauthorised_health_claims_but_us_does_not(ctx):
    txt = [TextItem(id="v", text="A healthy start to your day.")]
    assert "claims.prohibited" in rules(run_rules(subject(markets=["DE"], texts=txt), ctx))
    assert "claims.prohibited" not in rules(run_rules(subject(markets=["US"], texts=txt), ctx))
    assert market_matches(["EU"], ["PL"]) and not market_matches(["EU"], ["US"]) and market_matches(["*"], ["US"])


def test_needs_substantiation_is_resolved_by_a_source_super(ctx):
    s = subject(texts=[TextItem(id="v", text="Our beans are Fair Trade certified.")])
    f = next(f for f in run_rules(s, ctx) if f.rule_id == "claims.needs_substantiation")
    assert f.fix["op"] == "append_text"
    assert apply_fix(s, f.fix, ctx)
    assert not [x for x in run_rules(s, ctx) if x.rule_id == "claims.needs_substantiation"]


def test_auto_revise_converges_on_all_seeded_violations_at_once(ctx):
    s = subject(
        type="spot", has_video=True, captions_present=False, markets=["DE"], channels=["youtube"],
        texts=[
            TextItem(id="b1:vo", text="Dawn Roast cures morning anxiety!!"),
            TextItem(id="b2:vo", text="A cheap boost of energy for early shifts."),
        ],
        music=[MusicUse(title="Sunrise Anthem", mood="warm")], talent=[TalentUse(name="Jonas Weber")], stock=[StockUse(title="Stock photo: latte art hero")],
        visuals=[VisualItem(id="endcard", kind="endcard", colors=["#FF2BD6", "#F6EBDD"])],
        disclosure=Disclosure(ai_generated=True, label_present=False),
    )
    before = build_report(s, ctx)
    assert before.verdict == "block"
    expect = {"claims.prohibited", "voice.forbidden_word", "rights.unlicensed", "rights.expired", "visual.off_palette", "disclosure.missing_label", "claims.missing_disclaimer", "rights.territory"}
    assert expect <= {f.rule_id for f in before.findings}, {f.rule_id for f in before.findings}
    for _ in range(3):
        applied = revise_once(s, run_rules(s, ctx), ctx)
        if not applied:
            break
    after = build_report(s, ctx)
    assert after.verdict != "block", [(f.rule_id, f.message) for f in after.findings if f.severity == "block"]
    assert "cures" not in " ".join(t.text for t in s.texts).lower()
    assert s.music[0].title.endswith("(library)") and not s.talent and not s.stock


def test_waived_finding_no_longer_blocks_but_costs_score(ctx):
    s = subject(texts=[TextItem(id="b1:vo", text="Dawn Roast cures morning anxiety.")])
    f = next(f for f in run_rules(s, ctx) if f.rule_id == "claims.prohibited")
    ctx.waivers = [f.id]
    rep = build_report(s, ctx)
    assert rep.verdict != "block" and any(x.waived for x in rep.findings) and rep.score < 100


def test_rights_expiry_alerts_and_claim_matching_edge_cases(ctx):
    assert any(a["state"] == "expired" and "Jonas" in a["title"] for a in expiring(ctx.rights, 30, now=__import__("datetime").date(2026, 11, 17)))
    hits = find_hits("It treats stress and fatigue", ctx.claims, ["US"], "beverage")
    assert hits and hits[0].rule.id == "clm-cure"
    assert not find_hits("A calm, honest cup of coffee", ctx.claims, ["US"], "beverage")


def test_colour_science_sanity():
    assert col.contrast_ratio("#000000", "#FFFFFF") == 21.0
    near, d = col.nearest_palette("#F3A13E", ["#F2A03D"])
    assert near == "#F2A03D" and d < 2
    _, far = col.nearest_palette("#00FF00", [p["hex"] for p in data.PALETTE])
    assert far > 18  # beyond the spec-colour tolerance


def test_image_palette_check_passes_brand_imagery_and_blocks_off_brand_imagery(ctx):
    import io

    from PIL import Image

    from spotlight.core.ai.stubs import render_stub_scene

    def dom(img):
        buf = io.BytesIO()
        img.save(buf, "JPEG")
        return col.dominant_colors(buf.getvalue(), 6)

    good = subject(type="storyboard", visuals=[VisualItem(id="f1", dominant=dom(render_stub_scene("dawn", (480, 320), None, 3)))])
    assert not [f for f in run_rules(good, ctx) if f.rule_id == "visual.image_palette"]
    bad = subject(type="storyboard", visuals=[VisualItem(id="f2", dominant=dom(Image.new("RGB", (120, 120), (255, 43, 214))))])
    f = next(f for f in run_rules(bad, ctx) if f.rule_id == "visual.image_palette")
    assert f.severity == "block"


def test_logo_size_and_clear_space_rules(ctx):
    ok = VisualItem(id="end", logo={"x": 500, "y": 40, "w": 280, "h": 170, "frame_w": 1280, "frame_h": 720}, elements=[{"name": "headline", "x": 400, "y": 330, "w": 480, "h": 60}])
    assert not [f for f in run_rules(subject(type="spot", visuals=[ok]), ctx) if f.check == "visual_identity"]
    small = VisualItem(id="end", logo={"x": 560, "y": 40, "w": 100, "h": 62, "frame_w": 1280, "frame_h": 720})
    f = next(f for f in run_rules(subject(type="spot", visuals=[small]), ctx) if f.rule_id == "visual.logo_size")
    assert f.severity == "block" and f.fix["op"] == "resize_logo"
    crowded = VisualItem(id="end", logo={"x": 500, "y": 40, "w": 280, "h": 170, "frame_w": 1280, "frame_h": 720}, elements=[{"name": "headline", "x": 400, "y": 215, "w": 480, "h": 60}])
    assert any(f.rule_id == "visual.logo_clear_space" for f in run_rules(subject(type="spot", visuals=[crowded]), ctx))
