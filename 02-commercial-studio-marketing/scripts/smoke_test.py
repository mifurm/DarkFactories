#!/usr/bin/env python
"""End-to-end smoke test of a DEPLOYED Spotlight instance (real Azure OpenAI / Cosmos / Blob when mode=azure).

    python scripts/smoke_test.py --base-url https://<app>.azurecontainerapps.io [--expect-mode azure] [--langs de,fr,pl]

Runs the demo narrative (brief -> strategy -> script -> Guardian block/auto-revise -> storyboard frames -> VO -> rendered
MP4 -> provenance -> approvals -> formats -> localization -> experiments -> performance -> planner -> ROI -> export) with
small, bounded AI spend (low-quality images, 15 s spot, short VO). Prints a PASS/FAIL table; exit code != 0 on failure.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

SAMPLE_BRIEF = """Brief — Dawn Roast launch (Northwind Coffee Roasters)

We launch Dawn Roast, our new medium roast, in the US, Germany, France and Poland this September.
Objective: drive trial among early-shift workers and commuters — 150,000 trial purchases in 8 weeks.
Audience: 28–45, early risers — nurses, bakers, commuting parents and remote workers who start before 7am.
Channels: YouTube pre-roll, Meta/Instagram reels, TikTok, CTV.
Budget: media EUR 400k; we want production to stay under EUR 30k.
Timeline: concept in 1 week, final spots in 3 weeks, live on Sept 14.
Mandatories: end on the tagline "Wake up slowly."; show the amber sun bag; the legal team wants the line "Dawn Roast cures morning anxiety." in the spot.
Tone: warm, unhurried, honest.
Music: something like "Sunrise Anthem" by the Goldfinch Kids — our CEO loves it.
Talent: Maya Okafor (voice-over).
"""


class Smoke:
    def __init__(self, base: str, timeout: float) -> None:
        self.base = base.rstrip("/")
        self.http = httpx.Client(base_url=self.base, timeout=timeout, headers={"X-Studio-User": "smoke-test"}, limits=httpx.Limits(max_keepalive_connections=0))
        self.rows: list[tuple[str, bool, float, str]] = []
        self.ctx: dict[str, Any] = {}

    def call(self, method: str, path: str, role: str = "creative", **kw: Any) -> httpx.Response:
        headers = {"X-Studio-Role": role, **kw.pop("headers", {})}
        return self.http.request(method, path, headers=headers, **kw)

    def job(self, method: str, path: str, role: str = "creative", **kw: Any) -> dict[str, Any]:
        """POST an async job with ?wait=true; poll if the server returned a still-running job."""
        sep = "&" if "?" in path else "?"
        r = self.call(method, f"{path}{sep}wait=true", role, **kw)
        if r.status_code >= 400:
            raise AssertionError(f"{r.status_code} {r.text[:300]}")
        j = r.json()
        deadline = time.time() + 420
        while j.get("status") in {"queued", "running"} and time.time() < deadline:
            time.sleep(2)
            j = self.call("GET", f"/api/jobs/{j['id']}").json()
        if j.get("status") != "succeeded":
            raise AssertionError(f"job {j.get('status')}: {j.get('error')}")
        return j

    def step(self, name: str, fn: Callable[[], str | None]) -> None:
        t0 = time.perf_counter()
        try:
            detail = fn() or ""
            ok = True
        except Exception as exc:
            detail, ok = f"{type(exc).__name__}: {exc}"[:240], False
        ms = (time.perf_counter() - t0) * 1000
        self.rows.append((name, ok, ms, detail))
        print(f"  {'PASS' if ok else 'FAIL'}  {name:<62} {ms / 1000:6.1f}s  {detail[:110]}", flush=True)

    def table(self) -> int:
        print("\n| # | Check | Result | Time | Evidence |\n|---|---|---|---|---|")
        for i, (n, ok, ms, d) in enumerate(self.rows, 1):
            print(f"| {i} | {n} | {'PASS' if ok else 'FAIL'} | {ms / 1000:.1f}s | {d[:150].replace('|', '/')} |")
        failed = [r for r in self.rows if not r[1]]
        print(f"\n{len(self.rows) - len(failed)}/{len(self.rows)} checks passed" + (f"; FAILED: {[r[0] for r in failed]}" if failed else ""))
        return 1 if failed else 0


SMOKE_PREFIXES = ("Dawn Roast — Launch (smoke", "Smoke —", "E2E —", "Debug")


def cleanup_previous_runs(s: Smoke) -> int:
    """Remove campaigns left by earlier smoke / E2E runs so the demo environment stays tidy (the new run's campaign is kept)."""
    n = 0
    for c in s.call("GET", "/api/campaigns", role="admin").json():
        if c["name"].startswith(SMOKE_PREFIXES) and s.call("DELETE", f"/api/campaigns/{c['id']}", role="admin").status_code == 200:
            n += 1
    return n


def run(base: str, expect_mode: str | None, langs: list[str], timeout: float, keep_previous: bool = False) -> int:
    s = Smoke(base, timeout)
    if not keep_previous:
        removed = cleanup_previous_runs(s)
        print(f"(removed {removed} campaign(s) from earlier smoke/E2E runs)")
    u0 = s.call("GET", "/api/usage").json()
    spend0 = u0["total_usd"]
    print(f"Smoke test against {base}\n")

    def health() -> str:
        assert s.call("GET", "/healthz").json()["status"] == "ok"
        r = s.call("GET", "/readyz?deep=true")
        d = r.json()
        if d.get("status") != "ready":  # a cold replica can time out on its very first credential acquisition
            time.sleep(3)
            r = s.call("GET", "/readyz?deep=true")
            d = r.json()
        failing = {k: v.get("error") for k, v in d.get("dependencies", {}).items() if not v.get("ok")}
        assert r.status_code == 200 and d["status"] == "ready", f"degraded: {failing}"
        if expect_mode:
            assert d["mode"] == expect_mode, d["mode"]
        s.ctx["mode"] = d["mode"]
        return f"mode={d['mode']} deps=" + ",".join(f"{k}:{v['ms']:.0f}ms" for k, v in d["dependencies"].items())

    s.step("healthz + readyz (Cosmos, Blob, Azure OpenAI, Content Safety, Speech, ffmpeg)", health)

    def features() -> str:
        f = s.call("GET", "/api/features").json()
        impl = [x for x in f if x["status"] == "implemented"]
        assert len(f) == 24 and len(impl) == 24, f"{len(impl)}/{len(f)}"
        spa = s.call("GET", "/features")
        assert spa.status_code == 200 and "<div id=\"root\">" in spa.text
        return "24/24 implemented; SPA served"

    s.step("feature registry (24/24) + SPA + Feature Map route", features)

    def budget_guard() -> str:
        m = s.call("GET", "/api/meta").json()
        u = s.call("GET", "/api/usage").json()
        assert u["budget"]["guard_active"] and u["budget"]["daily_cap_usd"] > 0
        return f"daily cap ${u['budget']['daily_cap_usd']}; models={list(m['models'].values())[:3]}…"

    s.step("meta + usage: daily AI budget guard active", budget_guard)

    def brain() -> str:
        r = s.call("GET", "/api/brand/search", params={"q": "what is the brand voice and tone?"}).json()
        assert r["hits"] and r["hits"][0]["title"], r
        return f"{len(r['hits'])} cited passages (top: {r['hits'][0]['title'][:40]!r}, score {r['hits'][0]['score']})"

    s.step("CS-01 Brand Brain retrieval with citations (embeddings)", brain)

    def claims() -> str:
        bad = s.call("POST", "/api/claims/check", json={"text": "Dawn Roast cures morning anxiety.", "market": ["US"]}).json()
        ok = s.call("POST", "/api/claims/check", json={"text": "Some mornings deserve a slower start.", "market": ["US"]}).json()
        assert bad["verdict"] == "block" and ok["verdict"] == "pass"
        return "prohibited claim -> block; compliant line -> pass"

    s.step("CS-02 claims library: prohibited blocked / compliant passes", claims)

    def rights() -> str:
        a = s.call("POST", "/api/rights/check", json={"kind": "music", "title": "Sunrise Anthem", "markets": ["US"]}).json()
        b = s.call("POST", "/api/rights/check", json={"kind": "talent", "title": "Jonas Weber", "markets": ["DE"]}).json()
        c = s.call("POST", "/api/rights/check", json={"kind": "music", "title": "Dawn Pad (library)", "markets": ["DE"], "channels": ["youtube"]}).json()
        assert not a["cleared"] and not b["cleared"] and c["cleared"]
        return "unlicensed music + expired consent blocked; library track cleared"

    s.step("CS-03 rights registry: unlicensed / expired blocked, library cleared", rights)

    def brief() -> str:
        r = s.call("POST", "/api/campaigns", json={"name": f"Dawn Roast — Launch (smoke {time.strftime('%Y-%m-%d %H:%M')} UTC)", "markets": ["US", "DE"], "channels": ["youtube", "meta"]})
        assert r.status_code == 200, r.text
        cid = r.json()["id"]
        s.ctx["cid"] = cid
        s.call("PUT", f"/api/campaigns/{cid}/brief", json={"raw_text": SAMPLE_BRIEF})
        a = s.call("POST", f"/api/campaigns/{cid}/brief/analyze")
        assert a.status_code == 200, a.text
        b = a.json()
        assert 1 <= len(b["questions"]) <= 3 and b["completeness"]["missing"], b["completeness"]
        r = s.call("POST", f"/api/campaigns/{cid}/brief/answers", json={"answers": {"key_message": "A slower start, made well.", "cta": "Find Dawn Roast at northwind.example/dawn", "duration_targets": [15]}})
        assert r.json()["completeness"]["missing"] == [], r.json()["completeness"]
        f = s.call("POST", f"/api/campaigns/{cid}/brief/finalize")
        assert f.status_code == 200, f.text
        s.ctx["brief_art"] = f.json()["artifact"]["id"]
        rules = {x["rule_id"] for x in f.json()["guardian_report"]["findings"] if x["severity"] == "block"}
        assert {"claims.prohibited", "rights.unlicensed"} <= rules, rules
        return f"{len(b['questions'])} clarifying questions: {[q['field'] for q in b['questions']]}; Guardian flags {sorted(rules)}"

    s.step("CS-04 briefing agent: <=3 questions, normalized brief, early Guardian flags", brief)
    cid = s.ctx.get("cid")
    if not cid:
        return s.table()

    def strategy() -> str:
        s.job("POST", f"/api/campaigns/{cid}/strategy/generate", json={})
        st = s.call("GET", f"/api/campaigns/{cid}/strategy").json()["latest"]
        assert 3 <= len(st["territories"]) <= 5 and st["citations"], st
        s.call("POST", f"/api/campaigns/{cid}/strategy/select", json={"territory_id": st["territories"][0]["id"]})
        return f"{len(st['territories'])} territories (e.g. {st['territories'][0]['name']!r}), {len(st['citations'])} citations, guardian={st['guardian']['verdict']}"

    s.step("CS-05 strategy agent: 3+ territories grounded with citations", strategy)

    def script() -> str:
        s.job("POST", f"/api/campaigns/{cid}/script/generate", json={"durations": [15], "tone": "warm"})
        sc = s.call("GET", f"/api/campaigns/{cid}/script").json()["scripts"][0]
        s.ctx["script"] = sc["id"]
        spoken = " ".join(b["vo"] for b in sc["beats"])
        assert "cures morning anxiety" in spoken.lower(), spoken
        assert sc["guardian"]["verdict"] == "block", sc["guardian"]
        return f"{len(sc['beats'])} beats, {sc['word_count']} words; Guardian BLOCKS (blocks={sc['guardian']['blocks']}, score={sc['guardian']['score']})"

    s.step("CS-06 script agent writes 15 s script; Guardian blocks the mandatory claim + music cue", script)

    def revise() -> str:
        r = s.call("POST", f"/api/campaigns/{cid}/guardian/run", json={"artifact_id": s.ctx["script"], "auto_revise": True})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["converged"] and d["report"]["verdict"] != "block", d["report"]["verdict"]
        ops = sorted({f["op"] for it in d["iterations"] for f in it["fixes"]})
        sc = s.call("GET", f"/api/campaigns/{cid}/script/{s.ctx['script']}").json()
        assert "cures" not in " ".join(b["vo"] for b in sc["beats"]).lower()
        return f"converged in {len(d['iterations'])} iteration(s); fixes={ops}; verdict={d['report']['verdict']}; music -> {sc['music']['title']}"

    s.step("CS-12 Guardian auto-revise converges (claim rewritten, music swapped to licensed track)", revise)

    def board() -> str:
        s.job("POST", f"/api/campaigns/{cid}/storyboard/generate", json={"script_id": s.ctx["script"]})
        sb = s.call("GET", f"/api/campaigns/{cid}/storyboard").json()["latest"]
        s.job("POST", f"/api/campaigns/{cid}/storyboard/{sb['id']}/frames", json={"quality": "low"})
        sb = s.call("GET", f"/api/campaigns/{cid}/storyboard").json()["latest"]
        ready = [x for x in sb["shots"] if x["image_status"] == "ready"]
        assert len(ready) >= 3, [x["image_status"] for x in sb["shots"]]
        s.ctx["sb"] = sb["id"]
        img = s.call("GET", f"/api/library/assets/{ready[0]['asset_id']}/content")
        assert img.status_code == 200 and img.headers["content-type"].startswith("image/") and len(img.content) > 10_000
        return f"{len(ready)}/{len(sb['shots'])} keyframes ({sb['shots'][0].get('image_model')}, low), first image {len(img.content) // 1024} KB; guardian={sb['guardian']['verdict']}"

    s.step("CS-07 storyboard: shot list + >=3 gpt-image keyframes (low quality)", board)

    def voice() -> str:
        s.job("POST", f"/api/campaigns/{cid}/audio/generate", json={"script_id": s.ctx["script"]})
        v = s.call("GET", f"/api/campaigns/{cid}/audio").json()["latest"]
        assert v["lines"] and not v["overflow_lines"], v.get("overflow_lines")
        s.ctx["voice"] = v["id"]
        return f"{len(v['lines'])} lines, {v['total_vo_seconds']}s of VO, voice={v['voice']}, cost ${v['cost_usd']}"

    s.step("CS-09 voice-over timed to script beats (tts-hd) + SRT", voice)

    def render() -> str:
        j = s.job("POST", f"/api/campaigns/{cid}/spot/render", json={"script_id": s.ctx["script"], "storyboard_id": s.ctx["sb"], "voice_id": s.ctx["voice"]})
        res = j["result"]
        assert abs(res["duration"] - 15.0) <= 0.5 and abs(res["loudness_lufs"] - (-16.0)) <= 1.5, res
        spots = s.call("GET", f"/api/campaigns/{cid}/spot").json()["spots"]
        sp = spots[0]
        s.ctx["spot"], s.ctx["video"] = sp["id"], sp["assets"]["video"]
        r = s.call("GET", f"/api/library/assets/{s.ctx['video']}/content", headers={"Range": "bytes=0-2047"})
        assert r.status_code == 206 and r.content[4:8] == b"ftyp"
        full = s.call("GET", f"/api/library/assets/{s.ctx['video']}/content")
        s.ctx["mp4"] = full.content
        probe = ""
        if shutil.which("ffprobe"):
            with tempfile.TemporaryDirectory(dir=str(Path(__file__).resolve().parents[1] / "app")) as td:
                p = Path(td) / "spot.mp4"
                p.write_bytes(full.content)
                out = json.loads(subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(p)], capture_output=True, text=True, check=True).stdout)
                v = next(x for x in out["streams"] if x["codec_type"] == "video")
                a = next(x for x in out["streams"] if x["codec_type"] == "audio")
                assert v["codec_name"] == "h264" and a["codec_name"] == "aac" and (v["width"], v["height"]) == (1280, 720)
                assert abs(float(out["format"]["duration"]) - 15.0) <= 0.5
                probe = f"ffprobe: {v['codec_name']}/{a['codec_name']} {v['width']}x{v['height']} {float(out['format']['duration']):.2f}s"
        return f"{res['duration']}s MP4 {len(full.content) // 1024} KB, {res['loudness_lufs']} LUFS, render {res['render_seconds']}s; {probe}; guardian={res['guardian']['verdict']}"

    s.step("CS-08 compositor: 15 s H.264/AAC MP4 retrievable via API (ffprobe, loudness, range)", render)

    def prov() -> str:
        r = s.call("POST", "/api/provenance/verify", json={"asset_id": s.ctx["video"], "tamper_test": True}).json()
        assert r["result"]["ok"] and r["tamper_detected"], r
        side = s.call("GET", f"/api/provenance/assets/{s.ctx['video']}/sidecar.json").json()
        pack = s.call("GET", f"/api/provenance/assets/{s.ctx['video']}/pack", role="creative_director")
        assert pack.status_code == 200 and pack.content[:2] == b"PK"
        return f"manifest verifies ({len(r['result']['checks'])} checks, key {side['signature']['key_id']}); tampered asset+manifest rejected; pack {len(pack.content) // 1024} KB"

    s.step("CS-14 provenance manifest verifies; tampering is detected; pack export", prov)

    def approvals() -> str:
        order = ["brief", "concept", "script", "storyboard", "final"]
        blocked_seen = False
        for stage in order:
            pipe = s.call("GET", f"/api/campaigns/{cid}").json()["pipeline"]
            art_id = next(p for p in pipe if p["gate"] == stage)["artifact_id"]
            r = s.call("POST", f"/api/campaigns/{cid}/approvals", json={"stage": stage})
            assert r.status_code == 200, (stage, r.text)
            apr = r.json()
            for role in apr["required_roles"]:
                d = s.call("POST", f"/api/approvals/{apr['id']}/decide", role=role, json={"decision": "approve", "comment": "smoke"})
                if d.status_code == 422 and d.json()["error"]["code"] == "guardian_blocked":
                    blocked_seen = True
                    s.call("POST", f"/api/campaigns/{cid}/guardian/run", json={"artifact_id": art_id, "auto_revise": True})
                    d = s.call("POST", f"/api/approvals/{apr['id']}/decide", role=role, json={"decision": "approve", "comment": "smoke after fixes"})
                assert d.status_code == 200, (stage, role, d.text)
        pipe = s.call("GET", f"/api/campaigns/{cid}").json()["pipeline"]
        assert all(p["artifact_status"] == "approved" for p in pipe), [(p["gate"], p["artifact_status"]) for p in pipe]
        bad = s.call("POST", f"/api/approvals/{apr['id']}/decide", role="creative", json={"decision": "approve"})
        assert bad.status_code in {403, 409}
        return f"5/5 gates approved by role; Guardian-gated={blocked_seen}; non-approver refused ({bad.status_code})"

    s.step("CS-13 approvals: stage gates, roles enforced, Guardian-gated approval", approvals)

    def audit() -> str:
        a = s.call("GET", f"/api/campaigns/{cid}/audit").json()
        assert a["verification"]["ok"] and a["total"] >= 15
        return f"hash-chain verified: {a['total']} entries, head {a['verification']['head_hash'][:12]}…"

    s.step("CS-13 immutable audit log verifies (hash chain)", audit)

    def formats() -> str:
        s.job("POST", f"/api/campaigns/{cid}/formats/generate", json={"aspects": ["9:16", "1:1"], "cutdowns": [6]})
        tree = s.call("GET", f"/api/campaigns/{cid}/formats/tree").json()["nodes"]
        kids = [n for n in tree if n["parent_id"]]
        sizes = {}
        for n in kids:
            r = s.call("GET", f"/api/library/assets/{n['video_asset_id']}/content")
            if shutil.which("ffprobe"):
                with tempfile.TemporaryDirectory(dir=str(Path(__file__).resolve().parents[1] / "app")) as td:
                    p = Path(td) / "v.mp4"
                    p.write_bytes(r.content)
                    out = json.loads(subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(p)], capture_output=True, text=True, check=True).stdout)
                    v = next(x for x in out["streams"] if x["codec_type"] == "video")
                    sizes[n["label"]] = (v["width"], v["height"], round(float(out["format"]["duration"]), 1))
        assert len(kids) == 3, [n["label"] for n in tree]
        if sizes:
            assert any(w == 720 and h == 1280 for w, h, _ in sizes.values()) and any(w == h == 720 for w, h, _ in sizes.values()) and any(d <= 6.6 for _, _, d in sizes.values()), sizes
        s.ctx["format_ids"] = [n["id"] for n in kids]
        return f"version tree: master + {len(kids)} derived {sizes}"

    s.step("CS-11 format factory: 9:16, 1:1 and 6 s bumper from the master", formats)

    def approve_versions() -> str:
        r = s.call("POST", f"/api/campaigns/{cid}/formats/versions/approve", role="creative_director", json={"spot_ids": s.ctx["format_ids"]})
        assert r.status_code == 200, r.text
        d = r.json()
        return f"approved {len(d['approved'])} derived versions; refused {len(d['refused'])}"

    s.step("CS-11/13 derived versions approved (Guardian-gated)", approve_versions)

    def localize() -> str:
        j = s.job("POST", f"/api/campaigns/{cid}/localization/generate", json={"script_id": s.ctx["script"], "langs": langs})
        locs = s.call("GET", f"/api/campaigns/{cid}/localization").json()["localizations"]
        assert len(locs) >= len(langs)
        det = []
        for loc in locs[: len(langs)]:
            assert not [i for i in loc["glossary_issues"] if not i.get("repaired")], loc["glossary_issues"]
            assert all("Dawn Roast" in ln["text"] for ln in loc["lines"] if "Dawn Roast" in ln["source"]), loc["lines"]
            assert loc.get("video_asset_id")
            det.append(f"{loc['lang']}: minsim={loc['min_similarity']}, review={len(loc['needs_review'])}, guardian={loc['guardian']['verdict']}")
        _ = j
        return "; ".join(det)

    s.step(f"CS-10 localization {','.join(langs)}: glossary kept, back-translation QA, localized VO + render", localize)

    def score() -> str:
        r = s.call("POST", f"/api/campaigns/{cid}/scorecard", json={"spot_id": s.ctx["spot"]})
        assert r.status_code == 200, r.text
        d = r.json()
        assert "simulated" in d["label"].lower() and d["panel"]
        return f"predicted {d['predicted_score']}/100 (heuristic {d['heuristic_score']}, panel avg {d['panel_avg_appeal']}); suggestions={len(d['suggestions'])}"

    s.step("CS-16 pre-flight scorecard (labelled predictive/simulated)", score)

    def experiment() -> str:
        e = s.call("POST", "/api/experiments", json={"campaign_id": cid, "name": "Smoke bandit"}).json()
        assert len(e["variants"]) == 12
        pre = s.call("POST", f"/api/experiments/{e['id']}/preflight")
        assert pre.status_code == 200, pre.text
        sim = s.call("POST", f"/api/experiments/{e['id']}/simulate", json={"hours": 24})
        assert sim.status_code == 200, sim.text
        d = s.call("GET", f"/api/experiments/{e['id']}", params={"reveal": "true"}).json()
        truth_best = max(d["variants"], key=lambda v: v["truth"]["ctr"])
        leader_truth = next(v for v in d["variants"] if v["id"] == d["leader"]["id"])["truth"]["ctr"]
        paused = [v for v in d["variants"] if v["status"] == "paused"]
        assert leader_truth >= 0.95 * truth_best["truth"]["ctr"], (d["leader"], truth_best["id"])
        assert d["last_run"]["uplift_vs_uniform_pct"] > 0
        s.ctx["exp"] = e["id"]
        top = max(d["variants"], key=lambda v: v["share"])
        return f"leader {d['leader']['id']} within {100 * (1 - leader_truth / truth_best['truth']['ctr']):.1f}% of the simulator's best ({truth_best['id']}); {len(paused)} losers auto-paused; +{d['last_run']['uplift_vs_uniform_pct']}% clicks vs uniform; top share {top['share']:.0%}"

    s.step("CS-17 12-variant experiment: Thompson sampling converges to the best arm in 24 simulated hours", experiment)

    def perf() -> str:
        r = s.call("POST", "/api/performance/connectors/meta/sync", json={"campaign_id": cid, "days": 7})
        assert r.status_code == 200, r.text
        csv_text = "date,platform,variant_id,impressions,clicks,conversions,spend,revenue\n2026-11-01,google,v01,50000,900,40,450,580\n2026-11-02,google,v02,50000,700,25,450,362\n"
        r = s.call("POST", "/api/performance/ingest/csv", data={"campaign_id": cid}, files={"file": ("perf.csv", csv_text.encode(), "text/csv")})
        assert r.status_code == 200 and r.json()["ingested"] == 2, r.text
        m = s.call("GET", "/api/performance", params={"campaign_id": cid}).json()
        t = m["totals"]
        ins = s.call("POST", "/api/performance/insights/generate", json={"campaign_id": None})
        assert ins.status_code == 200, ins.text
        learnings = s.call("GET", "/api/brand/learnings").json()
        assert learnings
        return f"{m['rows']} rows; CTR {t['ctr']:.3%} CVR {t['cvr']:.2%} CPA ${t['cpa']:.2f} ROAS {t['roas']:.2f}; {ins.json()['written_to_brand_brain']} insight(s) -> Brand Brain ({len(learnings)} learnings)"

    s.step("CS-18 performance: connector sync + CSV ingest + insights written to Brand Brain", perf)

    def planner() -> str:
        r = s.call("POST", "/api/planner/plan", json={"budget_usd": 400000, "objective": "roas"})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["vs_uniform_split"]["uplift_pct"] >= 0
        return f"{len(d['allocation'])} channels; ROAS p10/p50/p90 {d['ranges']['roas_p10']}/{d['ranges']['roas_p50']}/{d['ranges']['roas_p90']}; +{d['vs_uniform_split']['uplift_pct']}% vs uniform split"

    s.step("CS-19 planner: media-mix with diminishing returns + ranges (illustrative)", planner)

    def library() -> str:
        r = s.call("GET", "/api/library/search", params={"q": "sunrise kitchen coffee pour"}).json()
        assert r["results"], r
        up = s.call("POST", "/api/library/assets", data={"tags": "smoke,logo", "description": "smoke upload", "campaign_id": cid}, files={"file": ("note.txt", b"smoke test asset", "text/plain")})
        assert up.status_code == 200, up.text
        aid = up.json()["id"]
        v2 = s.call("POST", f"/api/library/assets/{aid}/version", data={"note": "v2"}, files={"file": ("note.txt", b"smoke test asset v2", "text/plain")})
        assert v2.status_code == 200 and v2.json()["version"] == 2
        return f"semantic search -> {len(r['results'])} hits; upload + version v{v2.json()['version']}"

    s.step("CS-21 asset library: semantic search, upload, versions, range streaming", library)

    def hooks() -> str:
        w = s.call("POST", "/api/team/webhooks", role="admin", json={"name": "smoke sink", "url": "internal://sink", "format": "teams", "events": ["approval.requested"]})
        assert w.status_code == 200, w.text
        bad = s.call("POST", "/api/team/webhooks", role="admin", json={"name": "ssrf", "url": "https://169.254.169.254/latest", "format": "generic"})
        assert bad.status_code == 422
        d = s.call("POST", f"/api/team/webhooks/{w.json()['id']}/test", role="admin").json()
        assert d["ok"] and d["payload"]["@type"] == "MessageCard"
        s.call("DELETE", f"/api/team/webhooks/{w.json()['id']}", role="admin")
        return "Teams MessageCard delivered to internal sink; SSRF target (metadata IP) rejected"

    s.step("CS-22 webhooks: Teams-compatible delivery + SSRF guard; roles enforced", hooks)

    def export() -> str:
        j = s.job("POST", f"/api/campaigns/{cid}/export", role="creative_director")
        res = j["result"]
        z = s.call("GET", res["download"])
        assert z.status_code == 200 and z.content[:2] == b"PK"
        names = res["files"]
        assert any(n.startswith("videos/") for n in names) and any(n.startswith("provenance/") for n in names) and "manifest.json" in names
        return f"pack {res['size'] // 1024} KB with {len(names)} files (videos, keyframes, captions, provenance, csv)"

    s.step("CS-22 campaign pack export (mp4/png/csv/provenance zip)", export)

    def roi() -> str:
        meta = s.call("GET", "/api/roi/meta").json()
        assert meta["model_version"] == "1.1.0" and {"expansion_scale", "e1_scale", "e4_scale"} <= set(meta["overrides"]) and meta["advanced"], meta["model_version"]
        ref = s.call("GET", "/api/roi/reference").json()
        assert ref["parity_ok"], [p for p in ref["parity"] if not p["ok"]]
        base = s.call("POST", "/api/roi/compute", json={"scenario": "base"}).json()
        up = s.call("POST", "/api/roi/compute", json={"scenario": "upside"}).json()
        r = base["roi"]
        near = lambda x, y: abs(x - y) <= 0.005 * abs(y)  # noqa: E731 - published reference values, +-0.5 %
        assert near(r["npv"], 6_980_000) and near(r["roi_pct"], 140) and near(r["payback_months"], 15.0), r
        assert [round(v / 1000) for v in base["acr"]["by_year"][1:]] == [65, 305, 465], base["acr"]["by_year"]
        assert near(up["acr"]["run_rate_year3"], 973_000), up["acr"]["run_rate_year3"]
        tiers = {t["tier"]: t for t in base["acr"]["tiers"]}
        assert len(tiers) == 5 and near(tiers["enterprise_scale"]["acr_run_rate_usd"], 2_630_000), list(tiers)
        parts = {"breadth": tiers["enterprise_scale"]["expansion"]["core_run_rate_usd"], **tiers["enterprise_scale"]["expansion"]["by_lever_usd"]}
        assert set(parts) == {"breadth", "e1", "e2", "e3", "e4"} and near(sum(parts.values()), tiers["enterprise_scale"]["acr_run_rate_usd"])
        on = s.call("POST", "/api/roi/compute", json={"scenario": "base", "overrides": {"expansion_scale": 1}}).json()
        assert on["acr"]["by_year"][3] > 1.9 * base["acr"]["by_year"][3] and all(sum(on["acr"]["by_lever"][k]) > 0 for k in ("e1", "e2", "e3", "e4"))
        assert sum(sum(base["acr"]["by_lever"][k]) for k in ("e1", "e2", "e3", "e4")) == 0  # Base = expansion off
        c = s.call("POST", "/api/roi/compute", json={"scenario": "base", "overrides": {"markets": 16}}).json()
        assert c["roi"]["npv"] != r["npv"]
        live = s.call("GET", "/api/roi/live").json()
        return (f"model v{meta['model_version']} parity OK (±0.5%); Base NPV ${r['npv']:,.0f}, ROI {r['roi_pct']}%, payback {r['payback_months']} mo, ACR Y1/Y2/Y3 "
                f"${base['acr']['by_year'][1]:,.0f}/${base['acr']['by_year'][2]:,.0f}/${base['acr']['by_year'][3]:,.0f}; Upside Y3 ${up['acr']['run_rate_year3']:,.0f}; "
                f"Enterprise tier ${tiers['enterprise_scale']['acr_run_rate_usd']:,.0f}/yr; expansion on Y3 ${on['acr']['by_year'][3]:,.0f}; live $/approved asset={live['kpi']['cost_per_approved_asset_usd']}")

    s.step("CS-23 ROI & ACR calculator reproduces outputs.json; overrides recompute", roi)

    def meter() -> str:
        b = s.call("GET", "/api/budget").json()
        k = b["kpi"]
        row = next(c for c in b["campaigns"] if c["campaign_id"] == cid)
        assert row["approved_assets"] >= 1 and row["cost_per_approved_asset_usd"] is not None
        return f"campaign spend ${row['spent_usd']:.3f}, {row['approved_assets']} approved assets -> ${row['cost_per_approved_asset_usd']}/asset vs agency ${k['agency_baseline_per_asset_usd']:.0f} (-{row['savings_pct']}%)"

    s.step("CS-15 cost meter: $ per approved asset vs agency baseline", meter)

    def cap() -> str:
        c = s.call("POST", "/api/campaigns", json={"name": "Smoke cap test", "markets": ["US"], "channels": ["youtube"]}).json()
        s.call("PUT", f"/api/campaigns/{c['id']}/budget", role="brand_manager", json={"cap_usd": 0.0001})
        s.call("PUT", f"/api/campaigns/{c['id']}/brief", json={"raw_text": SAMPLE_BRIEF})
        r = s.call("POST", f"/api/campaigns/{c['id']}/brief/analyze")
        assert r.status_code == 402 and r.json()["error"]["code"] == "campaign_budget_exceeded", (r.status_code, r.text[:200])
        s.call("DELETE", f"/api/campaigns/{c['id']}", role="admin")
        return "generation refused with 402 campaign_budget_exceeded: " + r.json()["error"]["message"][:80]

    s.step("CS-15 budget guard fails closed with a clear message (per-campaign cap)", cap)

    def ops() -> str:
        st = s.call("GET", "/api/ops/status").json()
        mt = s.call("GET", "/api/ops/metrics").json()
        assert st["limits"]["rate_per_ip_spend_per_min"] > 0 and mt["routes"]
        return f"telemetry={'App Insights' if st['telemetry_enabled'] else 'off'}; {len(mt['routes'])} routes metered; AI calls {mt['ai_calls_by_kind']}"

    s.step("CS-24 observability: status, per-route metrics, AI usage meter", ops)

    u1 = s.call("GET", "/api/usage").json()
    spent = round(u1["total_usd"] - spend0, 4)
    print(f"\nAI spend incurred by this run (list-price estimate): ${spent:.4f}")
    code = s.table()
    print(f"\nTOTAL_AI_SPEND_USD={spent}")
    return code


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--expect-mode", default=None, choices=["azure", "offline"])
    ap.add_argument("--langs", default="de,fr,pl")
    ap.add_argument("--timeout", type=float, default=200.0)
    ap.add_argument("--keep-previous", action="store_true", help="do not delete campaigns from earlier smoke/E2E runs")
    a = ap.parse_args()
    sys.exit(run(a.base_url, a.expect_mode, [x.strip() for x in a.langs.split(",") if x.strip()], a.timeout, a.keep_previous))


if __name__ == "__main__":
    main()
