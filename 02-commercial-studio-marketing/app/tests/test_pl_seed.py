"""Seeding the Polish content pack on a store that already holds a deployed (English-only) generation of the sample data.

The seeder only ever upserts deterministic ids: user work survives, nothing is wiped, English rows keep their ids/text, a second run adds nothing."""

from __future__ import annotations

from spotlight.seed import data, ensure_seeded

BRAND = data.BRAND_ID


async def _roll_back_to_the_previous_generation(svc) -> None:
    """Make the store look like a 2026.11.1 deployment: English rows only, no language tags, no Polish book / kit overlay / claims / campaign."""
    repo = svc.repo
    for c in await repo.query("claims", pk=BRAND):
        if c["id"].startswith("clm-pl-"):
            await repo.delete("claims", c["id"], pk=BRAND)
        else:
            await repo.upsert("claims", {k: v for k, v in c.items() if k not in {"lang", "text_i18n"}})
    await repo.delete("brands", "doc-brand-book-pl", pk=BRAND)
    await svc.vectors.delete_where(BRAND, {"meta.doc_id": "doc-brand-book-pl"})
    await svc.vectors.delete_where(BRAND, {"lang": "pl"})
    await repo.delete("campaigns", "dawn-roast-premiera-pl", pk="dawn-roast-premiera-pl")
    en_campaign = await repo.get("campaigns", "dawn-roast-launch", pk="dawn-roast-launch")
    await repo.upsert("campaigns", {**{k: v for k, v in en_campaign.items() if k != "language"}, "stage": "script"})  # a user moved it forward
    v1 = await repo.get("brands", f"{BRAND}@1", pk=BRAND)
    await repo.upsert("brands", {**v1, "kit": {k: v for k, v in v1["kit"].items() if k != "i18n"}})
    state = await repo.get("settings", "seed_state", pk="tenant")
    await repo.upsert("settings", {**state, "version": "2026.11.1"})


async def _add_user_work(svc) -> None:
    repo = svc.repo
    root = await repo.get("brands", BRAND, pk=BRAND)
    v1 = await repo.get("brands", f"{BRAND}@1", pk=BRAND)
    await repo.upsert("brands", {"id": f"{BRAND}@2", "pk": BRAND, "brand_id": BRAND, "type": "brand_version", "version": 2, "kit": {**v1["kit"], "tagline": "Wake up slowly, but louder."}, "note": "user edit", "author": "Ola"})
    await repo.upsert("brands", {**root, "active_version": 2})
    await repo.upsert("brands", {"id": "doc-user-1", "pk": BRAND, "brand_id": BRAND, "type": "brand_doc", "name": "packaging.md", "text": "Our packaging is kraft paper.", "chars": 29, "lang": "en", "quarantined": False})
    await svc.vectors.add(BRAND, "docs", [{"id": "doc-user-1-00", "text": "Our packaging is kraft paper, printed with soy ink.", "title": "Packaging", "source": "packaging.md", "meta": {"doc_id": "doc-user-1", "n": 0}}], kind="document")
    any_claim = (await repo.query("claims", pk=BRAND))[0]
    await repo.upsert("claims", {**any_claim, "id": "clm-user-1", "text": "Our own claim", "type": "approved", "patterns": ["our own claim"]})
    await repo.upsert("campaigns", {"id": "my-campaign", "pk": "my-campaign", "campaign_id": "my-campaign", "name": "My own campaign", "brand_id": BRAND, "status": "draft", "stage": "storyboard", "markets": ["US"], "channels": ["meta"]})


async def test_reseeding_a_deployed_english_store_adds_polish_and_keeps_all_user_work(services):
    repo = services.repo
    en_claims_before = {c["id"]: c["text"] for c in data.claims()}
    await _roll_back_to_the_previous_generation(services)
    await _add_user_work(services)
    chunks_before = len(await repo.query("brand_chunks", pk=BRAND))

    out = await ensure_seeded(services)
    assert out["seeded"] is True and out["version"] == data.SEED_VERSION

    claims = await repo.query("claims", pk=BRAND)
    by_id = {c["id"]: c for c in claims}
    assert {i: by_id[i]["text"] for i in en_claims_before} == en_claims_before  # English rules: same ids, same text
    assert all(by_id[i].get("lang") == "en" for i in en_claims_before)  # ... now tagged with their language (additive)
    pl_ids = {c["id"] for c in data.claims_pl()}
    assert pl_ids and pl_ids <= set(by_id) and all(by_id[i]["lang"] == "pl" for i in pl_ids)
    assert len(claims) == len(en_claims_before) + len(pl_ids) + 1  # + the user's own claim
    assert by_id["clm-user-1"]["text"] == "Our own claim"

    campaigns = {c["id"]: c for c in await repo.query("campaigns")}
    assert campaigns["dawn-roast-premiera-pl"]["language"] == "pl" and campaigns["dawn-roast-premiera-pl"]["name"] == "Dawn Roast — premiera w Polsce"
    assert campaigns["dawn-roast-launch"]["language"] == "en" and campaigns["dawn-roast-launch"]["stage"] == "script"  # tagged, progress kept
    assert campaigns["my-campaign"]["stage"] == "storyboard" and "language" not in campaigns["my-campaign"]  # user campaigns are never touched

    root = await repo.get("brands", BRAND, pk=BRAND)
    v2 = await repo.get("brands", f"{BRAND}@2", pk=BRAND)
    assert root["active_version"] == 2 and v2["kit"]["tagline"] == "Wake up slowly, but louder." and v2["author"] == "Ola"  # the user's kit stays active and as written
    assert v2["kit"]["i18n"]["pl"]["tagline"].startswith("Obudź się powoli")  # ... and gains the Polish overlay
    assert (await repo.get("brands", "doc-brand-book-pl", pk=BRAND))["lang"] == "pl" and (await repo.get("brands", "doc-user-1", pk=BRAND))["name"] == "packaging.md"

    hits = await services.vectors.search(BRAND, "kraft paper packaging", k=3)
    assert any(h["id"] == "doc-user-1-00" for h in hits)  # the uploaded document keeps its embeddings
    pl_hits = await services.vectors.search(BRAND, "Obudź się powoli — palenie w małych partiach", k=5, prefer_lang="pl")
    assert pl_hits and any(h["lang"] == "pl" for h in pl_hits)
    assert len(await repo.query("brand_chunks", pk=BRAND)) > chunks_before  # Polish passages added, nothing removed


async def test_a_second_run_is_a_no_op_and_a_forced_run_creates_no_duplicates(services):
    repo = services.repo
    again = await ensure_seeded(services)
    assert again == {"seeded": False, "version": data.SEED_VERSION}

    def counts():
        return {coll: repo.query(coll, pk=pk) for coll, pk in (("claims", BRAND), ("brand_chunks", BRAND), ("brands", BRAND), ("rights", BRAND))}

    before = {k: len(await v) for k, v in counts().items()}
    ids_before = {c["id"] for c in await repo.query("claims", pk=BRAND)}
    forced = await ensure_seeded(services, force=True)
    after = {k: len(await v) for k, v in counts().items()}
    assert forced["seeded"] is True and after == before
    assert {c["id"] for c in await repo.query("claims", pk=BRAND)} == ids_before
    assert len([c for c in await repo.query("campaigns") if c["id"] in {"dawn-roast-launch", "dawn-roast-premiera-pl"}]) == 2


async def test_polish_brand_book_and_kit_facts_are_retrievable_and_ranked_by_the_viewers_language(services):
    pl = await services.vectors.search(BRAND, "ton i głos marki, zakazane słowa", k=4, prefer_lang="pl")
    assert pl and pl[0]["lang"] == "pl" and all(h["lang"] == "pl" for h in pl[:2])
    en = await services.vectors.search(BRAND, "brand voice and forbidden words", k=4, prefer_lang="en")
    assert en and en[0]["lang"] == "en"
    diacritic_free = await services.vectors.search(BRAND, "zakazane slowa i ton marki", k=4, prefer_lang="pl")  # typed on a phone, without Polish letters
    assert diacritic_free and diacritic_free[0]["lang"] == "pl"
