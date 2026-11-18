"""Platform behaviour tests: repository + blob abstractions, Cosmos query builder, Bicep/collections consistency, audit chain,
budget guard + metering, SSRF guard, rate limiter, roles, ROI parity, provenance, job runner, prompt cache."""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import pytest

from spotlight.core.ai.base import set_ctx
from spotlight.core.audit import AuditLog, entry_hash
from spotlight.core.blobs import LocalDirBlobStore, MemoryBlobStore
from spotlight.core.notify import INTERNAL_SINK, format_payload, validate_webhook_url
from spotlight.core.repo import COLLECTIONS, MemoryRepository, validate_field
from spotlight.core.repo.cosmos import build_query
from spotlight.errors import BudgetExceeded, Conflict, RateLimited, ValidationFailed
from spotlight.roles import PERMISSIONS, Actor, Role
from spotlight.security import RateLimiter, client_ip, redact

ROOT = Path(__file__).resolve().parents[2]


# --------------------------------------------------------------------------------------------- repository / Cosmos


async def test_memory_repository_semantics_match_the_cosmos_contract():
    r = MemoryRepository()
    await r.create("claims", {"id": "a", "pk": "nw", "type": "approved", "n": 3, "tags": ["x", "y"], "meta": {"k": 1}})
    with pytest.raises(Conflict):
        await r.create("claims", {"id": "a", "pk": "nw"})
    await r.upsert("claims", {"id": "b", "pk": "nw", "type": "prohibited", "n": 7, "tags": ["y"]})
    await r.upsert("claims", {"id": "c", "pk": "other", "type": "approved", "n": 9})
    assert {d["id"] for d in await r.query("claims", {"type": "approved"})} == {"a", "c"}  # cross-partition
    assert {d["id"] for d in await r.query("claims", {"type": "approved"}, pk="nw")} == {"a"}  # single partition
    assert [d["id"] for d in await r.query("claims", {"n": {"$gte": 3, "$lt": 9}}, order_by="n", desc=True)] == ["b", "a"]
    assert [d["id"] for d in await r.query("claims", {"tags": {"$contains": "y"}}, order_by="id")] == ["a", "b"]
    assert [d["id"] for d in await r.query("claims", {"id": {"$in": ["a", "c"]}, "meta.k": 1})] == ["a"]
    assert await r.count("claims", {"type": {"$ne": "approved"}}) == 1 and len(await r.query("claims", limit=2)) == 2
    assert (await r.get("claims", "a", pk="nw"))["n"] == 3 and await r.get("claims", "a", pk="wrong") is None
    assert await r.delete("claims", "a", pk="nw") and not await r.delete("claims", "a", pk="nw")
    assert await r.upsert_many("claims", [{"id": f"m{i}", "pk": "nw"} for i in range(5)]) == 5
    got = await r.get("claims", "m1", pk="nw")
    got["mutated"] = True
    assert "mutated" not in (await r.get("claims", "m1", pk="nw"))  # callers never share state with the store
    assert (await r.ping())["backend"] == "memory"


def test_cosmos_queries_are_parameterised_and_field_names_validated_against_injection():
    sql, params = build_query({"type": "approved", "n": {"$gte": 3}, "tags": {"$contains": "y"}, "meta.k": {"$in": [1, 2]}}, "created_at", True, 10)
    assert sql == "SELECT * FROM c WHERE c.type = @p0 AND c.n >= @p1 AND ARRAY_CONTAINS(c.tags, @p2) AND ARRAY_CONTAINS(@p3, c.meta.k) ORDER BY c.created_at DESC OFFSET 0 LIMIT 10"
    assert [p["value"] for p in params] == ["approved", 3, "y", [1, 2]]
    assert build_query(None, None, False, 5)[0] == "SELECT TOP 5 * FROM c"
    assert "IS_DEFINED" in build_query({"x": {"$exists": True}}, None, False, None)[0]
    for evil in ("type = 1 OR 1=1", "a; DROP", "x.", "1abc", "a b"):
        with pytest.raises(ValueError):
            build_query({evil: 1}, None, False, None)
    with pytest.raises(ValueError):
        build_query({"a": {"$where": "1"}}, None, False, None)
    with pytest.raises(ValueError):
        validate_field("c.x) OR (1=1")
    # values never reach the SQL text
    assert "DROP" not in build_query({"name": "x'; DROP TABLE c; --"}, None, False, None)[0]


def test_bicep_container_list_matches_the_repository_collections():
    bicep = (ROOT / "infra" / "modules" / "data.bicep").read_text(encoding="utf-8")
    declared = set(re.findall(r"'([a-z_]+)'", bicep.split("var containers", 1)[1].split("]", 1)[0])) if "var containers" in bicep else set()
    if not declared:  # fall back to scanning the whole file for quoted collection names
        declared = {c for c in COLLECTIONS if f"'{c}'" in bicep}
    assert declared == set(COLLECTIONS), f"infra/modules/data.bicep and core/repo.COLLECTIONS differ: {declared ^ set(COLLECTIONS)}"


def test_bicep_applies_the_governance_tags_to_the_resource_group_and_every_taggable_resource():
    infra = ROOT / "infra"
    main = (infra / "main.bicep").read_text(encoding="utf-8")
    tags = dict(re.findall(r"^\s{2}'?([\w-]+)'?: '?([\w-]+)'?$", main.split("var commonTags = {", 1)[1].split("}", 1)[0], re.M))
    assert tags["SecurityControl"] == "Ignore" and tags["SecurityExemption"] == "StorageAccountKeyAccess"
    assert {"project", "concept", "owner", "environment"} <= set(tags) and tags["concept"] == "studio" and tags["owner"] == "michalfu" and tags["environment"] == "demo"
    assert "SecurityExemption: 'Cosmos'" not in main
    rg_block = main.split("resource rg ", 1)[1].split("}\n", 1)[0]
    assert "tags: commonTags" in rg_block
    taggable = ("Microsoft.CognitiveServices/accounts@", "Microsoft.DocumentDB/databaseAccounts@", "Microsoft.Storage/storageAccounts@", "Microsoft.App/", "Microsoft.ContainerRegistry/", "Microsoft.OperationalInsights/", "Microsoft.Insights/components@", "Microsoft.ManagedIdentity/")
    for f in sorted((infra / "modules").glob("*.bicep")):
        text = f.read_text(encoding="utf-8")
        for m in re.finditer(r"^resource (\w+) '([^']+)' = (?:if \([^)]*\) )?\{", text, re.M):
            rtype = m.group(2)
            if rtype.startswith(taggable) and rtype.split("@")[0].count("/") == 1:  # top-level types only (sub-resources have no tags)
                body = text[m.end() : text.find("\n}\n", m.end())]
                assert re.search(r"tags:\s*(union\()?commonTags", body), f"{f.name}: {m.group(1)} ({rtype}) is missing commonTags"
    for call in re.finditer(r"^module (\w+) '[^']+' = \{(.*?)^\}", main, re.M | re.S):
        if call.group(1) not in {"appImage", "telemetryRoles"}:  # these two create no taggable resources (existing-app lookup, role assignments)
            assert "commonTags: commonTags" in call.group(2), f"module {call.group(1)} does not receive commonTags"


# --------------------------------------------------------------------------------------------- blob stores


@pytest.mark.parametrize("kind", ["memory", "localdir"])
async def test_blob_stores_round_trip_and_refuse_path_traversal(kind: str, tmp_path: Path):
    store = MemoryBlobStore() if kind == "memory" else LocalDirBlobStore(tmp_path / "blobs")
    info = await store.put("assets/c1/a.png", b"\x89PNG data", "image/png")
    assert info.size == 9 and info.content_type == "image/png"
    assert await store.get("assets/c1/a.png") == b"\x89PNG data" and await store.exists("assets/c1/a.png")
    await store.put("assets/c1/b.txt", b"hello")
    assert [b.path for b in await store.list("assets/c1/")] == ["assets/c1/a.png", "assets/c1/b.txt"]
    for bad in ("../secret", "/etc/passwd", "a/../../b", "a\\b"):
        with pytest.raises(Exception):
            await store.put(bad, b"x")
    assert await store.delete("assets/c1/a.png") and not await store.exists("assets/c1/a.png") and not await store.delete("assets/c1/a.png")
    with pytest.raises(Exception):
        await store.get("assets/c1/a.png")
    assert (await store.ping())["ok"]


# --------------------------------------------------------------------------------------------- audit chain


async def test_audit_chain_is_append_only_and_detects_edits_deletions_and_reordering():
    repo = MemoryRepository()
    log = AuditLog(repo)
    actor = {"name": "tester", "role": "admin"}
    for i in range(5):
        e = await log.append("camp-1", actor, f"step.{i}", {"i": i}, {"x": i})
    assert e["seq"] == 5 and (await log.verify("camp-1"))["ok"] and (await log.verify("camp-1"))["entries"] == 5
    assert (await log.verify("empty"))["ok"]
    rows = await log.entries("camp-1")
    assert all(rows[i]["prev_hash"] == rows[i - 1]["hash"] for i in range(1, 5)) and entry_hash(rows[2]) == rows[2]["hash"]

    row = await repo.get("audit", "camp-1:00000003", pk="camp-1")  # edit an entry in place
    row["data"] = {"x": 999}
    await repo.upsert("audit", row)
    bad = await log.verify("camp-1")
    assert not bad["ok"] and bad["broken_at"] == 3 and "tampered" in bad["reason"]
    row["data"] = {"x": 2}
    await repo.upsert("audit", row)
    assert (await log.verify("camp-1"))["ok"]  # restoring the original content restores the chain

    await repo.delete("audit", "camp-1:00000002", pk="camp-1")  # delete an entry
    gap = await log.verify("camp-1")
    assert not gap["ok"] and gap["broken_at"] == 2 and "gap" in gap["reason"]


async def test_concurrent_appends_keep_a_single_consistent_chain():
    log = AuditLog(MemoryRepository())
    await asyncio.gather(*[log.append("c", {"name": "t"}, f"a{i}") for i in range(20)])
    v = await log.verify("c")
    assert v["ok"] and v["entries"] == 20


# --------------------------------------------------------------------------------------------- budget guard + metering


async def test_budget_guard_refuses_after_the_cap_with_a_clear_error_and_metering_matches_counted_calls(services):
    s = services
    s.guard.daily_cap = 0.20
    set_ctx(campaign_id=None, feature="test")
    ok = 0
    refusal = None
    for i in range(40):
        try:
            await s.image.generate(f"a sunrise over a kitchen {i}", size="1024x1024", quality="medium")
            ok += 1
        except BudgetExceeded as exc:
            refusal = exc
            break
    assert refusal is not None and ok >= 1 and s.image.calls == ok
    assert refusal.code == "daily_budget_exceeded" and "Daily AI budget reached" in refusal.message and "fails closed" in refusal.message
    assert refusal.status == 402 and refusal.details["cap_usd"] == 0.20 and refusal.hint
    summary = await s.meter.summary()
    assert summary["by_kind"]["image"]["calls"] == ok  # metering == counted calls (the refused one was never metered)
    assert summary["total_usd"] == pytest.approx(sum(e["cost_usd"] for e in await s.meter.events()), abs=1e-6)
    assert summary["total_usd"] <= 0.20 + 1e-9 and s.guard.refusals == 1
    caps = await s.guard.caps()
    assert caps["daily_remaining_usd"] == pytest.approx(0.20 - summary["total_usd"], abs=1e-6) and caps["guard_active"]


async def test_campaign_cap_and_premium_generation_gate(services):
    s = services
    await s.repo.upsert("campaigns", {"id": "cx", "pk": "cx", "campaign_id": "cx", "name": "x", "budget_cap_usd": 1.0, "premium_approved": False})
    set_ctx(campaign_id="cx", feature="test")
    with pytest.raises(BudgetExceeded) as hq:  # high quality needs an explicit approval even with budget left
        await s.image.generate("hero shot", size="1536x1024", quality="high")
    assert hq.value.code == "premium_requires_approval"
    await s.repo.upsert("campaigns", {"id": "cx", "pk": "cx", "campaign_id": "cx", "name": "x", "budget_cap_usd": 0.03, "premium_approved": False})
    await s.image.generate("draft frame", size="1024x1024", quality="low")  # within the cap
    with pytest.raises(BudgetExceeded) as cap:
        for i in range(10):
            await s.image.generate(f"draft frame {i}", size="1024x1024", quality="low")
    assert cap.value.code == "campaign_budget_exceeded" and "Campaign AI cap reached" in cap.value.message and "$0.03" in cap.value.message
    assert (await s.guard.caps("cx"))["campaign_remaining_usd"] >= 0


async def test_small_amounts_are_formatted_readably_in_refusals(services):
    s = services
    s.guard.daily_cap = 0.001
    with pytest.raises(BudgetExceeded) as e:
        await s.image.generate("x", size="1024x1024", quality="low")
    assert "$0.0010" in e.value.message and "$0.00 of $0.00" not in e.value.message


async def test_budget_alerts_fire_once_per_threshold(services):
    s = services
    seen: list[dict] = []

    async def on_alert(event: str, payload: dict) -> None:
        seen.append(payload)

    s.guard.on_alert = on_alert
    s.guard.daily_cap = 0.05  # low-quality 1024² images cost $0.009 each
    set_ctx(campaign_id=None, feature="test")
    for i in range(30):
        try:
            await s.image.generate(f"alert frame {i}", size="1024x1024", quality="low")
        except BudgetExceeded:
            break
    thresholds = [a["threshold"] for a in seen if a["scope"].startswith("daily")]
    assert thresholds == [0.8, 1.0]  # each threshold alerts exactly once


# --------------------------------------------------------------------------------------------- SSRF / rate limits / roles


async def test_webhook_url_validator_blocks_ssrf_targets():
    assert await validate_webhook_url(INTERNAL_SINK) == INTERNAL_SINK
    with pytest.raises(ValidationFailed):
        await validate_webhook_url(INTERNAL_SINK, allow_internal=False)
    for evil in (
        "http://hooks.slack.com/services/x",  # not https
        "https://169.254.169.254/metadata",  # IP literal (cloud metadata)
        "https://127.0.0.1/x",
        "https://[::1]/x",
        "https://evil.example.com/hook",  # not on the allow-list
        "https://user:pw@hooks.slack.com/x",  # credentials
        "https://hooks.slack.com:8443/x",  # non-standard port
        "https://hooks.slack.com.evil.com/x",  # suffix trick
        "file:///etc/passwd",
    ):
        with pytest.raises(ValidationFailed):
            await validate_webhook_url(evil)


def test_webhook_payloads_for_teams_slack_and_generic():
    t = format_payload("teams", "approval.requested", {"campaign": "Dawn Roast", "stage": "Script"})
    assert t["@type"] == "MessageCard" and "Approval requested" in t["title"] and "Dawn Roast" in t["text"]
    assert "blocks" in format_payload("slack", "budget.alert", {"scope": "daily", "spent_usd": 4.0})
    assert format_payload("generic", "job.failed", {"x": 1})["payload"] == {"x": 1}


def test_rate_limiter_is_a_token_bucket_with_retry_hint():
    rl = RateLimiter(True)
    for _ in range(3):
        rl.check("spend", "1.2.3.4", 3)
    with pytest.raises(RateLimited) as e:
        rl.check("spend", "1.2.3.4", 3)
    assert e.value.status == 429 and e.value.details["retry_after_s"] >= 1
    rl.check("spend", "5.6.7.8", 3)  # other clients are unaffected
    RateLimiter(False).check("spend", "x", 1)  # disabled limiter never raises
    off = RateLimiter(True)
    for _ in range(10):
        off.check("x", "k", 0)  # per_min <= 0 means unlimited


def test_client_ip_and_log_redaction():
    assert client_ip({"x-forwarded-for": "203.0.113.9, 10.0.0.1"}, "10.0.0.1") == "203.0.113.9"
    assert client_ip({}, "198.51.100.2") == "198.51.100.2"
    cleaned = redact("mail jane.doe@contoso.com or call +1 (415) 555-0100 from 203.0.113.77")
    assert "jane.doe" not in cleaned and "555-0100" not in cleaned and "203.0.x.x" in cleaned


def test_role_permission_matrix_encodes_the_gate_policy():
    assert Role.LEGAL.value == "legal"
    can = lambda role, perm: Actor(name="t", role=role).can(perm)  # noqa: E731
    assert can(Role.ADMIN, "admin") and not can(Role.CREATIVE, "admin")
    assert can(Role.LEGAL, "waive") and not can(Role.CREATIVE_DIRECTOR, "waive")
    assert can(Role.CREATIVE, "generate") and can(Role.AGENCY_GUEST, "generate") and not can(Role.AGENCY_GUEST, "approve")
    assert not can(Role.AGENCY_GUEST, "performance.write") and not can(Role.CREATIVE, "webhooks.write") and can(Role.LEGAL, "claims.write")
    assert can(Role.BRAND_MANAGER, "brand.write") and not can(Role.CREATIVE, "brand.write")
    assert can(Role.CREATIVE_DIRECTOR, "approve") and not can(Role.CREATIVE, "approve")
    assert "premium.approve" in PERMISSIONS and all(isinstance(v, (set, frozenset, tuple, list)) for v in PERMISSIONS.values())


# --------------------------------------------------------------------------------------------- ROI calculator parity (CS-23)


def _assert_tree_close(live, ref, path: str = "") -> None:
    """Recursive comparison: identical structure, strings/bools equal, numbers within 0.5 %."""
    if isinstance(ref, dict):
        assert isinstance(live, dict) and set(live) == set(ref), f"{path}: keys differ {set(live) ^ set(ref) if isinstance(live, dict) else type(live)}"
        for k in ref:
            _assert_tree_close(live[k], ref[k], f"{path}.{k}")
    elif isinstance(ref, list):
        assert isinstance(live, list) and len(live) == len(ref), f"{path}: length differs"
        for i, (a, b) in enumerate(zip(live, ref, strict=True)):
            _assert_tree_close(a, b, f"{path}[{i}]")
    elif ref is None or isinstance(ref, (bool, str)):
        assert live == ref, (path, live, ref)
    else:
        assert live == pytest.approx(ref, rel=0.005, abs=1e-6), (path, live, ref)


def test_roi_calculator_reproduces_the_published_business_case_within_half_a_percent():
    from spotlight.vendor import model

    vendor = ROOT / "app" / "src" / "spotlight" / "vendor"
    a = model.load_assumptions(str(vendor / "assumptions.json"))
    ref = json.loads((vendor / "outputs.json").read_text(encoding="utf-8"))
    for f in ("model.py", "assumptions.json", "outputs.json"):  # the three files are always vendored together, byte for byte
        assert (vendor / f).read_bytes() == (ROOT / "business-case" / f).read_bytes(), f"vendored {f} is stale: run scripts/sync_business_case.py"
    assert ref["meta"]["model_version"] == model.MODEL_VERSION and ref["meta"]["assumptions_sha256"] == model.assumptions_hash(a)
    for scenario in model.SCENARIOS:  # the complete compute() output of every scenario, not just the headline numbers
        _assert_tree_close(model.compute(a, scenario), ref["scenarios"][scenario], scenario)
        summary = ref["meta"]["summary"][scenario]
        live = model.compute(a, scenario)
        assert live["roi"]["npv"] == pytest.approx(summary["npv"], rel=0.005) and live["acr"]["run_rate_year3"] == pytest.approx(summary["acr_run_rate_year3"], rel=0.005)
        full = model.compute(a, scenario, {"expansion_scale": 1.0})
        assert full["roi"]["npv"] == pytest.approx(summary["full_expansion_npv"], rel=0.005)
        assert full["acr"]["by_year"][3] == pytest.approx(summary["full_expansion_acr_by_year"][3], rel=0.005)


def test_roi_headline_numbers_and_the_expansion_levers_match_the_published_reference_values():
    from spotlight.vendor import model

    a = model.load_assumptions(str(ROOT / "app" / "src" / "spotlight" / "vendor" / "assumptions.json"))
    base, upside = model.compute(a, "base"), model.compute(a, "upside")
    assert base["roi"]["npv"] == pytest.approx(6_980_000, rel=0.005) and base["roi"]["roi_pct"] == pytest.approx(140, rel=0.005) and base["roi"]["payback_months"] == pytest.approx(15.0, rel=0.005)
    assert [round(x / 1000) for x in base["acr"]["by_year"][1:]] == [65, 305, 465]  # Y1 / Y2 / Y3 Azure consumed revenue
    assert upside["acr"]["run_rate_year3"] == pytest.approx(973_000, rel=0.005)
    tiers = {t["tier"]: t for t in base["acr"]["tiers"]}
    assert list(tiers) == ["pilot", "one_brand", "global_portfolio", "agency_network", "enterprise_scale"]
    ent = tiers["enterprise_scale"]
    assert ent["acr_run_rate_usd"] == pytest.approx(2_630_000, rel=0.005)
    parts = {"breadth": ent["expansion"]["core_run_rate_usd"], **ent["expansion"]["by_lever_usd"]}  # breadth + E1 video + E2 catalog + E3 personalization + E4 data platform
    assert set(parts) == {"breadth", "e1", "e2", "e3", "e4"} and sum(parts.values()) == pytest.approx(ent["acr_run_rate_usd"], rel=0.005) and all(v > 0 for v in parts.values())
    # Base = expansion off: the exp_* benefit and expansion_* cost categories exist but are zero-filled; ACR by lever is all core
    assert all(sum(base["benefits"]["by_category"][k]) == 0 for k in base["benefits"]["by_category"] if k.startswith("exp_"))
    assert all(sum(base["costs"]["other_by_category"][k]) == 0 for k in base["costs"]["other_by_category"] if k.startswith("expansion_"))
    assert sum(base["acr"]["by_lever"]["e1"] + base["acr"]["by_lever"]["e2"] + base["acr"]["by_lever"]["e3"] + base["acr"]["by_lever"]["e4"]) == 0
    assert base["acr"]["by_lever"]["core"] == base["acr"]["by_year"]
    # expansion on (expansion_scale 0 -> 1) adds consumption in every lever, benefits and the expansion cost categories
    on = model.compute(a, "base", {"expansion_scale": 1.0})
    assert all(sum(on["acr"]["by_lever"][k]) > 0 for k in ("core", "e1", "e2", "e3", "e4"))
    assert on["acr"]["by_year"][3] == pytest.approx(sum(on["acr"]["by_lever"][k][3] for k in on["acr"]["by_lever"]), rel=1e-6) and on["acr"]["by_year"][3] > 1.9 * base["acr"]["by_year"][3]
    assert all(sum(on["benefits"]["by_category"][k]) > 0 for k in on["benefits"]["by_category"] if k.startswith("exp_"))
    assert all(sum(on["costs"]["other_by_category"][k]) > 0 for k in on["costs"]["other_by_category"] if k.startswith("expansion_"))
    half, single = model.compute(a, "base", {"expansion_scale": 0.5}), model.compute(a, "base", {"e3_scale": 1.0})
    assert base["acr"]["by_year"][3] < half["acr"]["by_year"][3] < on["acr"]["by_year"][3]
    assert sum(single["acr"]["by_lever"]["e3"]) > 0 and sum(single["acr"]["by_lever"]["e1"]) == 0  # levers can be switched individually
    more = model.compute(a, "base", {"agency_cost_scale": 1.5})
    assert more["roi"]["npv"] > base["roi"]["npv"]  # costlier agencies -> more savings


# --------------------------------------------------------------------------------------------- jobs / cache / vectors / provenance


async def test_job_runner_persists_progress_and_failures(services):
    from spotlight.core.jobs import JobContext

    async def ok(job: JobContext) -> dict:
        await job.progress(0.5, "halfway", step="half")
        return {"answer": 42}

    async def boom(job: JobContext) -> dict:
        raise ValidationFailed("nope", code="bad_thing")

    j1 = await services.jobs.submit("test.ok", ok, campaign_id="c1", title="ok job")
    j2 = await services.jobs.submit("test.fail", boom, campaign_id="c1", title="failing job")
    for _ in range(100):
        a, b = await services.jobs.get(j1["id"]), await services.jobs.get(j2["id"])
        if a["status"] in {"succeeded", "failed"} and b["status"] in {"succeeded", "failed"}:
            break
        await asyncio.sleep(0.05)
    assert a["status"] == "succeeded" and a["result"] == {"answer": 42} and a["progress"] == 1 and any(s["name"] == "half" for s in a["steps"])
    assert b["status"] == "failed" and "nope" in b["error"]
    assert {j["id"] for j in await services.jobs.list("c1", 10)} >= {j1["id"], j2["id"]}


async def test_prompt_hash_cache_returns_identical_results_without_new_spend(services):
    from spotlight.core.ai.cache import AICache

    cache = AICache(services.repo, services.blobs)
    assert await cache.get_json("k1") is None
    await cache.put_json("k1", {"a": 1})
    assert await cache.get_json("k1") == {"a": 1}
    assert await cache.get_bytes("img1") is None
    await cache.put_bytes("img1", b"\xff\xd8jpeg", {"model": "gpt-image-1.5"}, "image/jpeg")
    data, meta = await cache.get_bytes("img1")
    assert data == b"\xff\xd8jpeg" and meta["model"] == "gpt-image-1.5"
    assert cache.stats()["hits"] >= 2 and cache.stats()["misses"] >= 2


async def test_vector_index_returns_the_semantically_closest_passage_first(services):
    v = services.vectors
    await v.add("t", "docs", [{"id": "d1", "text": "We sound warm, unhurried and honest. Never shout.", "title": "Voice", "source": "book"}, {"id": "d2", "text": "The logo must be at least 12% of the frame width with clear space.", "title": "Logo", "source": "book"}], kind="document")
    hits = await v.search("t", "how big must the logo be in the frame", k=2, version=["docs"])
    assert hits[0]["id"] == "d2" and hits[0]["score"] >= hits[1]["score"]
    assert await v.search("nobody", "anything", k=3) == []
