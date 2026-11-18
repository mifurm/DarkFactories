#!/usr/bin/env python3
"""Post-deployment smoke test for Nightshift: end-to-end checks against a RUNNING instance (local or the Azure Container App).

Real Azure OpenAI, Cosmos DB and Blob are exercised when the target runs in ``mode=azure``. Prints a PASS/FAIL table, exits non-zero on
any failure and (by default) publishes the result table to the app (Deployment page -> "Smoke test results").
Uses only the standard library. AI spend per run is small (a few thousand tokens) and bounded by the app's daily budget guard.

    python scripts/smoke_test.py --base-url https://<app>.azurecontainerapps.io
    python scripts/smoke_test.py --base-url http://127.0.0.1:8101 --offline      # skip checks that need real Azure
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

ENG = {"X-Demo-Role": "engineer"}
OPERATOR = {"X-Demo-Role": "operator"}
AUDITOR = {"X-Demo-Role": "auditor"}


class Client:
    def __init__(self, base: str, timeout: float = 60.0) -> None:
        self.base, self.timeout = base.rstrip("/"), timeout

    def call(self, method: str, path: str, body: Any = None, headers: dict[str, str] | None = None, timeout: float | None = None) -> tuple[int, Any]:
        data = None if body is None else json.dumps(body).encode()
        h = {"Accept": "application/json", **(headers or {})}
        if data is not None:
            h["Content-Type"] = "application/json"
        req = urllib.request.Request(self.base + path, data=data, headers=h, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as r:
                raw = r.read()
                ctype = r.headers.get("content-type", "")
                return r.status, (json.loads(raw) if "json" in ctype and raw else raw)
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                return e.code, json.loads(raw)
            except Exception:
                return e.code, raw

    def get(self, path: str, **kw: Any) -> tuple[int, Any]:
        return self.call("GET", path, **kw)

    def post(self, path: str, body: Any = None, **kw: Any) -> tuple[int, Any]:
        return self.call("POST", path, {} if body is None else body, **kw)

    def put(self, path: str, body: Any, **kw: Any) -> tuple[int, Any]:
        return self.call("PUT", path, body, **kw)


class Check(Exception):
    pass


def need(cond: Any, msg: str) -> None:
    if not cond:
        raise Check(msg)


def wait_for(fn: Callable[[], Any], timeout: float, every: float = 1.5, what: str = "condition") -> Any:
    end = time.time() + timeout
    last: Any = None
    while time.time() < end:
        last = fn()
        if last:
            return last
        time.sleep(every)
    raise Check(f"timed out after {timeout:.0f}s waiting for {what}")


def run(base: str, offline: bool, report: bool, reset: bool = True, only: list[str] | None = None) -> int:
    c = Client(base)
    results: list[dict[str, Any]] = []
    state: dict[str, Any] = {}

    def check(name: str, fn: Callable[[], str], azure_only: bool = False) -> None:
        if only and not any(o in name.lower() for o in only):
            return
        if azure_only and offline:
            results.append({"name": name, "status": "SKIP", "detail": "needs mode=azure", "ms": 0})
            return
        t0 = time.perf_counter()
        try:
            detail = fn() or ""
            status = "PASS"
        except Check as e:
            detail, status = str(e), "FAIL"
        except Exception as e:  # noqa: BLE001
            detail, status = f"{type(e).__name__}: {e}"[:300], "FAIL"
        results.append({"name": name, "status": status, "detail": detail[:300], "ms": (time.perf_counter() - t0) * 1000})

    if reset:  # deterministic starting point: re-seed the primary plant (the decision ledger chain continues, nothing is rewritten)
        try:
            c.post("/api/admin/reseed?plant=KAT-1", {}, headers={"X-Demo-Role": "admin"}, timeout=90)
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------ platform
    def healthz() -> str:
        s, d = c.get("/healthz")
        need(s == 200 and d["status"] == "ok", f"{s} {d}")
        return f"uptime {d['uptime_s']:.0f}s"

    def readyz() -> str:
        s, d = c.get("/readyz?fresh=1", timeout=90)
        need(s == 200 and d["status"] == "ready", f"{s} {json.dumps(d)[:200]}")
        ch = d["checks"]
        state["mode"] = d["mode"]
        need(all(v["status"] == "ok" for v in ch.values()), json.dumps(ch)[:240])
        return f"mode={d['mode']} " + ", ".join(f"{k}:{v['backend']} {v.get('latency_ms', 0):.0f}ms" for k, v in ch.items())

    def meta() -> str:
        s, d = c.get("/api/meta")
        need(s == 200 and d["synthetic_data"] is True, "meta missing synthetic flag")
        if not offline:
            need(d["mode"] == "azure" and d["persistence"]["repository"] == "cosmos" and d["persistence"]["blobs"] == "azure-blob", json.dumps(d)[:240])
            need(d["persistence"]["write_behind"]["failed"] == 0, "Cosmos write-behind failures")
        return f"{d['version']} build {d['build_id']} {d['persistence']['repository']}/{d['persistence']['blobs']} written={d['persistence']['write_behind']['written']}"

    def features() -> str:
        s, d = c.get("/api/features")
        need(s == 200 and len(d) == 25 and all(f["status"] == "implemented" for f in d), f"{sum(f['status'] == 'implemented' for f in d)}/25 implemented")
        return "25/25 implemented"

    def spa() -> str:
        s, d = c.get("/", headers={"Accept": "text/html"})
        need(s == 200 and b'id="root"' in d and b"/assets/" in d, "SPA index not served")
        s2, d2 = c.get("/features", headers={"Accept": "text/html"})
        need(s2 == 200 and b'id="root"' in d2, "SPA deep link not served")
        s3, _ = c.get("/docs", headers={"Accept": "text/html"})
        need(s3 == 200, "/docs")
        return "index, deep link and /docs served"

    check("healthz", healthz)
    check("readyz: Cosmos + Blob + Azure OpenAI over managed identity", readyz)
    check("meta: azure mode, Cosmos + Blob persistence", meta)
    check("features: 25/25 implemented", features)
    check("SPA + OpenAPI docs served", spa)

    # ------------------------------------------------------------------ simulation + agents
    def sim() -> str:
        s, d = c.get("/api/sim/state")
        need(s == 200 and len(d["assets"]) == 20, f"{s}")
        state["speed0"], state["paused0"] = d["speed"], d["paused"]
        s, t = c.get("/api/telemetry/tree")
        need(t["topics"] >= 90, f"{t['topics']} UNS topics")
        return f"20 assets, {t['topics']} UNS topics, t={d['t']}, {d['speed']} sim-min/s"

    def sse() -> str:
        req = urllib.request.Request(c.base + "/api/stream/plant?plant=KAT-1", headers={"Accept": "text/event-stream"})
        seen: set[str] = set()
        with urllib.request.urlopen(req, timeout=20) as r:
            end = time.time() + 15
            while time.time() < end and not {"hello", "tick"} <= seen:
                line = r.readline().decode()
                if line.startswith("event: "):
                    seen.add(line[7:].strip())
        need({"hello", "tick"} <= seen, f"events seen: {seen}")
        return "SSE stream delivered hello + tick"

    check("simulator: state + UNS tree", sim)
    check("SSE stream (control-tower feed)", sse)

    def bearing_story() -> str:
        c.post("/api/sim/control", {"command": "speed", "value": 60}, headers=ENG)
        c.post("/api/sim/control", {"command": "resume"}, headers=ENG)
        health = c.get("/api/maintenance/health")[1]["assets"]
        pick = next(a["asset"] for a in health if a["ready"] and not a["alert"] and a["asset"].startswith("CNC") and a["asset"] != "CNC-04") if any(a["ready"] for a in health) else "CNC-03"
        state["asset"] = pick
        s, _ = c.post("/api/sim/faults", {"kind": "bearing_wear", "asset": pick, "params": {"ttf_h": 8}}, headers=ENG)
        need(s == 200, f"fault injection {s}")

        def alert() -> Any:
            row = next(a for a in c.get("/api/maintenance/health")[1]["assets"] if a["asset"] == pick)
            return row if row["alert"] else None

        row = wait_for(alert, 150, 2.0, f"PdM alert on {pick}")
        need(row["signature"]["name"] == "bearing_wear", f"signature {row['signature']}")

        def wo() -> Any:
            ws = [w for w in c.get("/api/maintenance/work-orders")[1] if w["asset"] == pick]
            return ws[0] if ws else None

        w = wait_for(wo, 90, 2.0, f"work order for {pick}")
        led = c.get(f"/api/ledger?asset={pick}&limit=30")[1]
        kinds = {e["kind"] for e in led["items"]}
        need({"proposal", "decision"} <= kinds, f"ledger kinds {kinds}")
        ok = c.get("/api/ledger/verify")[1]
        need(ok["ok"], f"hash chain broken: {ok}")
        return f"alert on {pick} (similarity {row['signature']['similarity']}), WO {w['id']} {w['status']}, ledger chain valid ({ok['length']} entries)"

    check("agents: bearing-wear fault -> PdM alert -> work order -> ledger (valid hash chain)", bearing_story)

    def approvals() -> str:
        prev = c.get("/api/policy")[1]["levels"]["maintenance.schedule"]
        s, _ = c.put("/api/policy/dial", {"levels": {"maintenance.schedule": 2}}, headers={"X-Demo-Role": "plant_manager"})
        need(s == 200, f"dial {s}")
        try:
            health = c.get("/api/maintenance/health")[1]["assets"]
            pick = next(a["asset"] for a in health if a["ready"] and not a["alert"] and a["asset"].startswith(("CNC", "PRESS")) and a["asset"] != state.get("asset"))
            c.post("/api/sim/faults", {"kind": "bearing_wear", "asset": pick, "params": {"ttf_h": 8}}, headers=ENG)

            def pending() -> Any:
                items = [i for i in c.get("/api/inbox?status=pending")[1]["items"] if i["status"] == "pending"]
                return items[0] if items else None

            item = wait_for(pending, 150, 2.0, "approval request in the inbox")
            s, _ = c.post(f"/api/inbox/{item['id']}/resolve", {"option": "approve", "comment": "smoke test"}, headers={"X-Demo-Role": "operator"})
            need(s == 403, f"operator must not approve (got {s})")
            s, d = c.post(f"/api/inbox/{item['id']}/resolve", {"option": "approve", "comment": "smoke test"}, headers=ENG)
            need(s == 200 and d["item"]["status"] == "approved", f"approve {s} {str(d)[:120]}")
            card = c.get(f"/api/inbox/{item['id']}/teams-card")[1]
            need(card["type"] == "AdaptiveCard", "no adaptive card")
            return f"{item['id']} ({item['decision_class']}) waited for a human, operator got 403, engineer approved, Teams card generated"
        finally:
            c.put("/api/policy/dial", {"levels": {"maintenance.schedule": prev}}, headers={"X-Demo-Role": "plant_manager"})

    check("autonomy dial L2 -> approval inbox -> RBAC -> approve -> Teams card", approvals)

    def specialists() -> str:
        sch = c.get("/api/planner/schedule")[1]
        need(sch["slots"] and sch["violations"] == [], f"planner schedule infeasible: {sch['violations'][:2]}")
        cmp_ = c.get("/api/planner/compare")[1]
        need({"planner", "fifo"} <= set(cmp_), "no planner-vs-FIFO comparison")
        mat = c.get("/api/materials/summary")[1]
        need({i["material"] for i in mat["inventory"]} >= {"BAR-AL", "RESIN-PA"} and mat["amr"], "materials summary incomplete")
        en = c.get("/api/energy/summary")[1]
        need(len(en["forecast"]) == 48 and en["shifts"], "energy forecast/shifts missing")
        pr = c.get("/api/process/summary")[1]
        need(pr["bounds"]["melt_temp_c"] and pr["enabled"] is False, "process agent should be a disabled pilot by default")
        k = c.get("/api/kpi?window_hours=8")[1]["plant_kpi"]
        need(0 <= k["oee"] <= 1, "KPI out of range")
        return f"planner {len(sch['slots'])} slots feasible; {len(mat['inventory'])} materials; energy {en['price_now']:.3f} EUR/kWh; OEE {k['oee'] * 100:.0f}%"

    check("planner / materials / energy / process / KPI endpoints return live, consistent data", specialists)

    def safety() -> str:
        deny = c.post("/api/safety/check", {"kind": "set_speed", "asset": "CNC-01", "params": {"pct": 240}})[1]
        need(deny["allowed"] is False and deny["violations"][0]["rule"] == "forbidden_setpoint", f"forbidden setpoint not denied: {deny}")
        before = len(c.get("/api/safety/summary")[1]["intrusions"])
        c.post("/api/sim/control", {"command": "speed", "value": 10}, headers=ENG)  # slow enough to observe the whole stop / veto / restart cycle
        s, _ = c.post("/api/sim/faults", {"kind": "human_intrusion", "zone": "Z-MOLD", "params": {"duration_min": 90}}, headers=ENG)
        need(s == 200, f"intrusion {s}")

        def stopped() -> Any:
            z = next(z for z in c.get("/api/safety/summary")[1]["zones"] if z["zone"] == "Z-MOLD")
            return z if z["occupied"] else None

        wait_for(stopped, 60, 0.5, "zone occupancy after the intrusion")
        veto = c.post("/api/safety/check", {"kind": "set_speed", "asset": "PRESS-01", "params": {"pct": 90}})[1]
        need(veto["allowed"] is False and any(v["rule"] == "zone_occupied" for v in veto["violations"]), f"zone-occupied veto missing: {veto}")
        led = c.get("/api/ledger?agent=safety&limit=30")[1]["items"]
        need(any("Z-MOLD" in e["summary"] or "PRESS" in e["summary"] or "MOLD" in e["summary"] for e in led) or len(c.get("/api/safety/summary")[1]["intrusions"]) > before, "no safety-agent record of the intrusion")

        def clear() -> Any:
            z = next(z for z in c.get("/api/safety/summary")[1]["zones"] if z["zone"] == "Z-MOLD")
            return z if not z["occupied"] and not z["locked_out"] else None

        wait_for(clear, 180, 1.0, "zone to clear and restart after verification")
        return "forbidden setpoint denied; intrusion -> zone occupied, restart vetoed (zone_occupied), safety agent logged it, zone cleared and restarted"

    check("safety: forbidden setpoint denied, human intrusion -> stop + veto -> verified restart", safety)

    def kill() -> str:
        s, _ = c.post("/api/policy/kill", {"on": True, "reason": "smoke test"}, headers={"X-Demo-Role": "plant_manager"})
        need(s == 200, f"kill {s}")
        try:
            snap = c.get("/api/tower/snapshot")[1]
            need(snap["kill_switch"] is True, "snapshot does not show the kill switch")
            s2, _ = c.post("/api/policy/kill", {"on": False}, headers=OPERATOR)
            need(s2 == 403, f"operator must not reset the kill switch (got {s2})")
        finally:
            c.post("/api/policy/kill", {"on": False, "reason": "smoke test done"}, headers={"X-Demo-Role": "plant_manager"})
        need(c.get("/api/tower/snapshot")[1]["kill_switch"] is False, "kill switch not released")
        return "kill switch engaged, visible in snapshot, operator reset denied (403), released by plant manager"

    c.post("/api/sim/control", {"command": "speed", "value": 60}, headers=ENG) if not only else None
    check("kill switch", kill)

    def whatif() -> str:
        t = c.get("/api/sim/state")[1]["t"]
        body = {"actions": [{"kind": "schedule_maintenance", "asset": "CNC-05", "start_t": t + 20, "duration": 45}], "horizon_min": 180}
        a = c.post("/api/twin/whatif", body)[1]
        b = c.post("/api/twin/whatif", body)[1]
        need(a["delta"] == b["delta"] or a["t"] != b["t"], "what-if not deterministic")
        need("accept" in a and a["explanation"], "no what-if verdict")
        return f"net value {a['delta']['net_value_eur']:+.1f} EUR, accept={a['accept']}: {a['explanation'][:90]}"

    check("digital twin what-if on a fork", whatif)

    # ------------------------------------------------------------------ real Azure OpenAI
    def copilot() -> str:
        s, d = c.post("/api/copilot/ask", {"messages": [{"role": "user", "content": "Which assets need attention right now and what did the agents decide about them? Cite your sources."}]}, timeout=120)
        need(s == 200 and d["answer"].strip(), f"{s} {str(d)[:200]}")
        need(d["mode"] == "azure", f"copilot fell back to {d['mode']}: {d.get('note')}")
        need(d["tools"], "the model called no tools")
        return f"model {d.get('model')} used tools {d['tools']}, {len(d['citations'])} citations, {len(d['answer'])} chars"

    check("copilot: Azure OpenAI tool calling with citations", copilot, azure_only=True)

    def vision() -> str:
        s, d = c.post("/api/quality/vision/batch", {"n": 6, "seed": 21}, timeout=180)
        need(s == 200, f"{s} {str(d)[:200]}")
        res = d["results"]
        azure = [r for r in res if r["source"].startswith("azure")]
        need(len(azure) >= 4, f"only {len(azure)}/6 classified by the Azure model (sources: {sorted({r['source'] for r in res})})")
        agree = sum(r["agree"] for r in azure) / len(azure)
        need(agree >= 0.5, f"model agreement {agree:.0%} below threshold")
        return f"{len(azure)}/6 images classified by {azure[0]['source']}, agreement with ground truth {agree:.0%}"

    check("vision: synthetic defect images classified by the Azure model", vision, azure_only=True)

    def handover() -> str:
        s, d = c.post("/api/handover/generate", {"window_hours": 4, "use_llm": True}, headers=ENG, timeout=120)
        need(s == 200 and d["markdown"], f"{s}")
        need(d["source"] == "azure", f"report narrated by {d['source']} (budget blocked: {d.get('budget_blocked')})")
        need(d["data"]["kpi"], "no KPI block")
        return f"{d['shift']} shift report narrated by {d['model']} ({len(d['markdown'])} chars)"

    check("shift handover report narrated by Azure OpenAI", handover, azure_only=True)

    def rca() -> str:
        s, d = c.post("/api/rca/narrate", {}, timeout=120)
        need(s == 200 and d["text"], f"{s}")
        need(d["source"] == "azure", f"RCA narrated by {d['source']}")
        return d["text"][:110]

    check("root-cause analysis narrated by Azure OpenAI", rca, azure_only=True)

    # ------------------------------------------------------------------ value
    def ab() -> str:
        s, j = c.post("/api/value/ab/run", {"n_seeds": 10, "horizon_h": 8, "window": "late"}, headers=ENG)
        if s == 409:
            j = {"id": None}
        else:
            need(s == 200, f"{s} {j}")

        def done() -> Any:
            if j["id"] is None:
                r = c.get("/api/value/ab/latest")[1]
                return r if r.get("available") else None
            r = c.get(f"/api/value/ab/jobs/{j['id']}")[1]
            need(r["status"] != "failed", r.get("error"))
            return r["result"] if r["status"] == "done" else None

        res = wait_for(done, 120, 1.0, "A/B replay")
        m = res["metrics"]
        need(len(res["seeds"]) >= 10, "fewer than 10 seeds")
        need(m["downtime_h"]["ci_low"] > 0 and m["late_orders"]["ci_low"] > 0, "downtime / late-order CI includes 0")
        return f"{len(res['seeds'])} seeds in {res['elapsed_s']}s: downtime {m['downtime_h']['improvement_pct']:.0f}% (CI {m['downtime_h']['ci_low']:.2f}..{m['downtime_h']['ci_high']:.2f} h), late orders {m['late_orders']['improvement_pct']:.0f}%, OEE +{m['oee']['improvement']:.1f} pts"

    check("A/B replay (>=10 seeds): significant downtime and late-order improvement", ab)

    def roi() -> str:
        def compute(scenario: str, overrides: dict | None = None, sens: bool = False) -> dict:
            st, d = c.post("/api/value/calculator/compute", {"scenario": scenario, "overrides": overrides or {}, "sensitivity": sens})
            need(st == 200, f"compute {scenario} -> {st}")
            return d

        def near(got: float, want: float, what: str, rel: float = 0.005) -> None:
            need(abs(got / want - 1) <= rel, f"{what}: {got:,.0f} vs reference {want:,.0f}")

        meta = c.get("/api/value/calculator/meta")[1]
        need(meta["meta"]["model_version"] == "1.1.0" and meta["counts"]["drivers"] > 250 and meta["counts"]["prices"] == 60, "calculator meta not generated from model v1.1.0")
        base = compute("base", sens=True)
        ref = c.get("/api/value/calculator/reference")[1]
        refb = ref["scenario_summaries"]["base"]
        need(abs(base["roi"]["npv"] / refb["npv"] - 1) < 0.005, f"NPV {base['roi']['npv']} vs reference {refb['npv']}")
        near(base["roi"]["npv"], 8.26e6, "Base NPV $8.3M")
        need(abs(base["roi"]["roi_pct"] - 104.2) < 0.2 and abs(base["roi"]["payback_months"] - 22.2) < 0.1, "Base ROI 104 % / payback 22.2 mo")
        near(base["acr"]["by_year"][2], 0.677e6, "Base year-3 ACR $0.68M")
        near(base["acr"]["run_rate_year3"], 0.910e6, "Base 8-plant run-rate $0.91M")
        near(base["acr"]["per_plant_year"], 114e3, "Base ACR per plant-year ~$114k", 0.01)
        need(base["sensitivity"] and base["acr_sensitivity"], "sensitivity missing")
        on = {s["key"]: s["on"] for s in meta["switches"]}
        lv = compute("base", on)
        near(lv["acr"]["by_year"][2], 1.28e6, "levers-on year-3 ACR $1.28M")
        near(lv["acr"]["run_rate_year3"], 1.87e6, "levers-on run-rate $1.87M")
        need(all(lv["acr"]["run_rate_by_lever"][k] > 0 for k in ("E1", "E2", "E3", "E4", "E5")), "ACR by lever empty")
        tiers = {t["id"]: t for t in lv["expansion"]["tiers"]}
        near(tiers["enterprise_25"]["without_levers"]["total"], 2.71e6, "25 plants core $2.71M")
        near(tiers["enterprise_25"]["with_levers"]["total"], 5.44e6, "25 plants with levers $5.44M")
        need(tiers["fleet"]["plants"] == 100 and tiers["fleet"]["with_levers"]["total"] > tiers["fleet"]["without_levers"]["total"], "fleet tier")
        up = compute("upside")
        near(up["acr"]["by_year"][2], 1.91e6, "Upside year-3 ACR $1.91M")
        near(up["acr"]["run_rate_year3"], 2.43e6, "Upside run-rate $2.43M")
        hi = compute("base", {"downtime_reduction_pct": 0.5})
        need(hi["roi"]["npv"] > base["roi"]["npv"], "overriding a driver did not change NPV")
        need(c.post("/api/value/calculator/compute", {"overrides": {"price.ghost": 1}})[0] == 422, "invalid override must be 422")
        return (
            f"Base NPV ${base['roi']['npv'] / 1e6:.2f}M, ROI {base['roi']['roi_pct']:.0f} %, payback {base['roi']['payback_months']:.1f} mo, "
            f"Y3 ACR ${base['acr']['by_year'][2] / 1e6:.2f}M, run-rate ${base['acr']['run_rate_year3'] / 1e6:.2f}M (${base['acr']['per_plant_year'] / 1e3:.0f}k/plant-yr); "
            f"levers on ${lv['acr']['by_year'][2] / 1e6:.2f}M / ${lv['acr']['run_rate_year3'] / 1e6:.2f}M; Upside ${up['acr']['by_year'][2] / 1e6:.2f}M / ${up['acr']['run_rate_year3'] / 1e6:.2f}M; "
            f"25 plants ${tiers['enterprise_25']['without_levers']['total'] / 1e6:.2f}M -> ${tiers['enterprise_25']['with_levers']['total'] / 1e6:.2f}M; model v{ref['model_version']}"
        )

    check("ROI / ACR calculator reproduces the business-case model", roi)

    def readiness() -> str:
        s, d = c.post("/api/readiness/assess", {"answers": {}, "target": 75}, headers=ENG)
        need(s == 200 and d["roadmap"], f"{s}")
        md = c.get("/api/readiness/export?format=md")
        need(md[0] == 200, "export")
        return f"{d['level']} ({d['overall']:.0f}/100), {len(d['roadmap'])} roadmap items"

    check("readiness assessment + export", readiness)

    def fleet() -> str:
        d = c.get("/api/fleet/compare")[1]
        need(len(d["plants"]) == 3 and all("rank" in p for p in d["plants"]), "fleet comparison incomplete")
        return ", ".join(f"{p['id']} OEE {p['oee'] * 100:.0f}%" for p in d["plants"])

    check("fleet comparison (3 plants)", fleet)

    # ------------------------------------------------------------------ governance, observability, deployment
    def rbac() -> str:
        need(c.put("/api/policy/dial", {"global_cap": 4}, headers=OPERATOR)[0] == 403, "operator may change the dial")
        need(c.get("/api/access/audit", headers={"X-Demo-Role": "plant_manager"})[0] == 403, "plant manager sees audit log")
        a = c.get("/api/access/audit", headers=AUDITOR)[1]
        need(a["denied_total"] >= 1, "denials not audited")
        return f"403s enforced; audit log has {a['entries']} entries, {a['denied_total']} denials"

    check("RBAC: server-side 403s and audit trail", rbac)

    def finops() -> str:
        f = c.get("/api/observability/finops")[1]
        need(f["guard"]["fails_closed"] and f["usage"]["daily_budget_usd"] > 0, "budget guard inactive")
        if not offline:
            need(f["usage"]["calls"] >= 3, f"only {f['usage']['calls']} model calls metered")
        m = c.get("/api/observability/metrics")[1]
        need(m["features"], "no per-feature metrics")
        return f"{f['usage']['calls']} calls, ${f['usage']['est_cost_usd']:.4f} of ${f['usage']['daily_budget_usd']:.0f} daily cap; blocked={f['guard']['blocked']}"

    check("FinOps: AI usage metered, daily budget guard active", finops)

    def persistence() -> str:
        def snaps() -> Any:
            d = c.get("/api/kpi/snapshots")[1]
            return d if d["persisted"] >= 1 else None

        d = wait_for(snaps, 150, 3.0, "hourly KPI snapshot persisted")
        need(offline or d["backend"] == "cosmos", f"backend {d['backend']}")
        m = c.get("/api/meta")[1]["persistence"]["write_behind"]
        need(m["failed"] == 0 and m["written"] > 0, f"write-behind {m}")
        return f"{d['persisted']} KPI snapshots in {d['backend']}; write-behind written={m['written']} failed={m['failed']} dropped={m['dropped']}"

    check("persistence: KPI snapshots + ledger written to Cosmos DB", persistence)

    def resources() -> str:
        d = c.get("/api/deployment/resources", timeout=60)[1]
        need(d["available"], d.get("reason", "ARM inventory unavailable"))
        names = [r["name"] for r in d["resources"]]
        need(len(names) >= 8, f"{len(names)} resources")
        tags = d["tags"]
        need(tags.get("SecurityControl") == "Ignore" and tags.get("SecurityExemption") == "StorageAccountKeyAccess", f"RG tags {tags}")
        untagged = [r["name"] for r in d["resources"] if r["tags"].get("SecurityControl") != "Ignore"]
        need(not untagged, f"resources without the governance tags: {untagged}")
        return f"{len(names)} resources in {d['resource_group']}; RG and all resources carry SecurityControl=Ignore / SecurityExemption=StorageAccountKeyAccess"

    check("deployment: ARM inventory with governance tags (managed identity)", resources, azure_only=True)

    # ------------------------------------------------------------------ restore live-demo state
    try:
        c.post("/api/sim/control", {"command": "speed", "value": state.get("speed0", 1)}, headers=ENG)
        if state.get("paused0"):
            c.post("/api/sim/control", {"command": "pause"}, headers=ENG)
    except Exception:  # noqa: BLE001
        pass

    width = max(len(r["name"]) for r in results)
    print(f"\nNightshift smoke test - {base}  (mode: {state.get('mode', '?')})\n")
    for i, r in enumerate(results, 1):
        mark = {"PASS": "PASS", "FAIL": "FAIL", "SKIP": "skip"}[r["status"]]
        print(f"{i:2d}. {mark}  {r['name']:<{width}}  {r['ms'] / 1000:6.1f}s  {r['detail']}")
    passed = sum(r["status"] == "PASS" for r in results)
    failed = sum(r["status"] == "FAIL" for r in results)
    print(f"\n{passed} passed, {failed} failed, {sum(r['status'] == 'SKIP' for r in results)} skipped")
    if report:
        s, _ = c.post("/api/deployment/smoke", {"results": results, "base_url": base, "duration_s": sum(r["ms"] for r in results) / 1000}, headers=ENG)
        print("published to the Deployment page" if s == 200 else f"could not publish results (HTTP {s})")
    return 1 if failed else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--offline", action="store_true", help="skip checks that need real Azure services")
    ap.add_argument("--no-report", action="store_true", help="do not publish the result table to the app")
    ap.add_argument("--keep-state", action="store_true", help="do not re-seed the primary plant before the run")
    ap.add_argument("--only", default="", help="comma-separated substrings; run only the matching checks (implies --no-report)")
    a = ap.parse_args()
    only = [o.strip().lower() for o in a.only.split(",") if o.strip()]
    return run(a.base_url, a.offline, not a.no_report and not only, not a.keep_state, only)


if __name__ == "__main__":
    sys.exit(main())
