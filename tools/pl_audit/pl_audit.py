#!/usr/bin/env python
"""pl_audit — independent audit of a localized SPA (built for the Polish localization of Spotlight and Concierge).

Crawls every UI route with ?lang=<lang>, then reports per route:
  * <html lang>, document title, console errors / page errors / failed requests
  * visible text nodes + attributes (placeholder, aria-label, title, alt) that still look ENGLISH (stop-word / UI-vocabulary heuristic)
  * raw enum-like values that should have been translated (DRAFT, APPROVED, COMPLETED, ...)
  * formatting / plural hygiene in pl mode: NaN/undefined/{placeholder}, US dates, 12 h clock, 1,234.56 grouping, "$" prefix, "2 plików"-type plurals
  * window.__i18nMissing (if the app exposes it)
  * horizontal overflow of the page and clipped / ellipsised elements (Polish text is ~25-35% longer)
  * which platform font actually renders Polish glyphs (CDP CSS.getPlatformFontsForNode) -> detects missing latin-ext
  * a screenshot per route

    /Users/michalfu/Dev/SwarmAI/.venv/bin/python tools/pl_audit/pl_audit.py --app studio --base-url https://... --out /tmp/pl-audit-studio [--lang pl] [--viewport 1600x900]

Exit code 0 always (it is a report); read report.md. Heuristics produce some false positives (proper nouns, loan words): review the flagged strings.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

PL_CHARS = re.compile(r"[ąćęłńóśźżĄĆĘŁŃÓŚŹŻ]")

# English function words that are NOT ordinary Polish words (ambiguous ones such as a, to, on, as, by, do, no, so, most, was, it removed)
EN_STOP = set(
    """the and for with your you from this that are is were be been have has not can will would should could of in at or an its our their they them we us all any more some such only
    than then there here what when where which who why how into about over after before between through during under again once per via each other new""".split()
)
# English UI vocabulary that is not a Polish loan word (status/start/stop/format/test/audio/video/spot/brief/agent/supervisor/QA/CSAT... are fine in Polish)
EN_UI = set(
    """save cancel create delete remove edit add search filter export import upload download close open back next previous submit apply reset refresh loading settings overview details
    name description title type date time total average count none yes today yesterday week month year min max draft approved rejected pending completed active paused blocked warning error success
    failed passed running queue customer customers order orders refund return returns show hide view select choose click enter send message messages history help about home dashboard
    login logout user users role roles team members share copy paste update updated created deleted retry continue finish done ready waiting online offline enabled disabled
    default custom advanced basic general summary report reports result results score scores rate rates cost costs price prices budget spend spent limit limits daily weekly monthly
    insights performance campaign campaigns brand rights claims library asset assets variant variants experiment experiments approvals audit trail guardian provenance""".split()
)
# raw enum-like values that must not be shown verbatim in a localized UI when they stand alone
ENUM_RAW = {
    "draft", "approved", "rejected", "pending", "completed", "active", "paused", "blocked", "warn", "warning", "pass", "fail", "failed", "open", "closed", "resolved", "escalated",
    "running", "queued", "done", "ok", "error", "success", "published", "history", "block", "control", "master", "localized", "cutdown", "format", "synthetic", "live", "idle",
}
PL_STOP = set(
    """i w z na do nie się jest to że jak dla po przez od oraz lub ale czy co tak już tylko bardzo ten ta te tego tej tych tym ich jego jej mój moje twoje nasz nasze proszę dzień dobry
    dziękuję zamówienie klient klienta konsultant kampania kampanii marka marki rozmowa rozmowy""".split()
)
# allowlist of tokens that are fine in a Polish UI (brand/product names, acronyms, loan words)
ALLOW_WORDS = {
    "contoso", "northwind", "azure", "openai", "spotlight", "concierge", "swarmai", "dawn", "roast", "gpt", "api", "json", "csv", "pdf", "mp4", "srt", "sms", "otp", "kpi", "sla", "qa",
    "csat", "aht", "fcr", "nps", "roas", "ctr", "cvr", "cpa", "roi", "acr", "npv", "irr", "ai", "llm", "rag", "pii", "pci", "rodo", "gdpr", "rbac", "ffprobe", "c2pa", "tts", "stt",
    "ok", "id", "url", "http", "https", "cosmos", "db", "blob", "realtime", "websocket", "sse", "tiktok", "youtube", "meta", "ctv", "linkedin", "display", "inpost", "dpd", "dhl",
    "midnight", "blend", "cold", "brew", "cans", "voc", "wfm", "crm", "erlang", "mape", "p50", "p95", "wcag", "axe",
}
# formatting / plural hygiene that the English-leftover heuristic cannot see (pl-PL: 1 234,56 · 18.11.2026 · 24 h · 1 plik / 2 pliki / 5 plików)
FORMAT_PATTERNS = [
    (re.compile(r"\b(?:NaN|undefined|null|Invalid Date)\b|\[object Object\]"), "bad value rendered"),
    (re.compile(r"\{[A-Za-z_][A-Za-z0-9_]*\}"), "unresolved {placeholder}"),
    (re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b"), "US-style date (expected 18.11.2026)"),
    (re.compile(r"\b\d{1,2}:\d{2}\s?(?:AM|PM|am|pm)\b"), "12-hour clock (expected 24 h)"),
    (re.compile(r"(?<![\d,.])[1-9]\d{0,2}(?:,\d{3})+(?:\.\d+)?(?![\d,])"), "US-style number grouping (expected 1 234,56)"),
    (re.compile(r"[$£]\s?\d"), "currency symbol before number"),
    (re.compile(r"\b[2-4] [a-ząćęłńóśźż]{3,}ów\b"), "genitive plural after 2-4 (expected nominative plural)"),
    (re.compile(r"\b1 [a-ząćęłńóśźż]{3,}(?:ów|ach|ami)\b"), "plural noun after 1"),
]


def http_json(url: str):
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "pl-audit"})
    with urllib.request.urlopen(req, timeout=40) as r:  # noqa: S310 - audit tool, explicit URL
        return json.loads(r.read().decode("utf8"))


JS_TEXT = """
() => {
  const out = [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let n;
  const vis = (el) => {
    if (!el) return false;
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden' || cs.opacity === '0') return false;
    const r = el.getBoundingClientRect();
    return !(r.width === 0 && r.height === 0);
  };
  while ((n = walker.nextNode())) {
    const t = (n.nodeValue || '').replace(/\\s+/g, ' ').trim();
    if (!t) continue;
    const el = n.parentElement;
    if (!el || ['SCRIPT', 'STYLE', 'NOSCRIPT', 'TEXTAREA', 'OPTION'].includes(el.tagName)) continue;
    if (!vis(el)) continue;
    if (el.closest('[data-user-content], [contenteditable=true], pre code')) continue;
    out.push({ t, tag: el.tagName, cls: (el.className && el.className.toString().slice(0, 50)) || '' });
  }
  for (const o of document.querySelectorAll('select')) {
    if (!vis(o)) continue;
    for (const op of o.options) { const t = (op.textContent || '').replace(/\\s+/g, ' ').trim(); if (t) out.push({ t, tag: 'OPTION', cls: 'select-option' }); }
  }
  for (const el of document.querySelectorAll('[placeholder],[aria-label],[title],img[alt]')) {
    if (!vis(el)) continue;
    for (const a of ['placeholder', 'aria-label', 'title', 'alt']) {
      const v = el.getAttribute(a);
      if (v && v.trim()) out.push({ t: v.trim(), tag: el.tagName, cls: '@' + a });
    }
  }
  return out;
}
"""

JS_OVERFLOW = """
() => {
  const de = document.documentElement;
  const res = { docOverflowX: de.scrollWidth - de.clientWidth, clipped: [] };
  for (const el of document.querySelectorAll('body *')) {
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') continue;
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;
    const ox = cs.overflowX, oy = cs.overflowY;
    const clipX = (ox === 'hidden' || ox === 'clip') && el.scrollWidth > el.clientWidth + 2;
    const clipY = (oy === 'hidden' || oy === 'clip') && el.scrollHeight > el.clientHeight + 2;
    const ell = cs.textOverflow === 'ellipsis' && el.scrollWidth > el.clientWidth + 1;
    if (clipX || clipY || ell) {
      const txt = (el.innerText || '').replace(/\\s+/g, ' ').trim();
      if (!txt) continue;
      res.clipped.push({ tag: el.tagName, cls: (el.className && el.className.toString().slice(0, 40)) || '', kind: clipX ? 'x' : clipY ? 'y' : 'ellipsis',
                         text: txt.slice(0, 90), sw: el.scrollWidth, cw: el.clientWidth, sh: el.scrollHeight, ch: el.clientHeight });
    }
  }
  res.clipped = res.clipped.slice(0, 40);
  return res;
}
"""

JS_SKELETON = "() => document.querySelectorAll('[class*=skeleton], .animate-pulse, [aria-busy=true]').length"
JS_PROBE_TEXT = (
    "() => { const el = [...document.querySelectorAll('h1,h2,h3,p,span,div,button,a,label,td,th,li')]"
    ".find(e => e.children.length===0 && /[ąćęłńóśźżĄĆĘŁŃÓŚŹŻ]/.test(e.textContent||'')); "
    "if (el) { el.setAttribute('data-pl-probe','1'); return (el.textContent||'').slice(0,60);} return null; }"
)
JS_GLYPH_DIV = (
    "() => { const d = document.createElement('div'); d.id='glyphprobe'; "
    "d.style.cssText='position:fixed;left:0;top:0;z-index:99999;background:#fff;color:#000;padding:8px;font-size:22px'; "
    "d.innerHTML = '<div data-gp=\"body\" style=\"font-family:var(--font-sans, inherit)\">Zażółć gęślą jaźń ĄĆĘŁŃÓŚŹŻ</div>"
    "<div data-gp=\"display\" style=\"font-family:var(--font-display, var(--font-sans, inherit))\">Zażółć gęślą jaźń ĄĆĘŁŃÓŚŹŻ</div>'; "
    "document.body.appendChild(d); }"
)


def words_of(t: str) -> list[str]:
    return re.findall(r"[A-Za-z][A-Za-z'’-]*", t)


def english_score(t: str) -> tuple[bool, str]:
    """Return (flag, reason)."""
    if len(t) < 3 or not re.search(r"[A-Za-z]", t):
        return False, ""
    if re.fullmatch(r"[\W\d_]*[A-Z]{1,4}-?\d*[\W\d_]*", t):  # codes like CS-01, L1, P95
        return False, ""
    ws = words_of(t)
    low = [w.lower().strip("'’-") for w in ws]
    cand = [w for w in low if w not in ALLOW_WORDS]
    if not cand:
        return False, ""
    has_pl = bool(PL_CHARS.search(t)) or any(w in PL_STOP for w in low)
    stops = [w for w in cand if w in EN_STOP]
    ui = [w for w in cand if w in EN_UI]
    if len(stops) >= 2:
        return True, "english stop-words: " + ", ".join(sorted(set(stops))[:5])
    if len(stops) == 1 and len(cand) <= 4 and not has_pl:
        return True, "english word: " + stops[0]
    if ui and not has_pl and len(cand) <= 3 and all(w in EN_UI or w in ALLOW_WORDS for w in low):
        return True, "english UI word: " + ", ".join(sorted(set(ui))[:4])
    if len(cand) >= 4 and not has_pl and len(ui) >= 1:
        return True, "english UI vocabulary: " + ", ".join(sorted(set(ui))[:4])
    return False, ""


def enum_raw(t: str) -> bool:
    s = t.strip().strip(".:·•").lower()
    return s in ENUM_RAW and re.fullmatch(r"[A-Za-z _-]+", t.strip()) is not None


def discover_routes(app: str, base: str) -> list[str]:
    feats = http_json(base + "/api/features")
    items = feats if isinstance(feats, list) else feats.get("features", feats)
    routes = {i.get("ui_route") for i in items if i.get("ui_route")}
    routes |= {"/", "/features"}
    out = sorted(routes)
    if app == "studio":
        camps = http_json(base + "/api/campaigns")
        camps = camps if isinstance(camps, list) else camps.get("campaigns") or camps.get("items") or []
        pl = [c for c in camps if (c.get("language") or c.get("lang")) == "pl"]
        pick = (pl or camps or [{}])[0].get("id")
        res = []
        for r in out:
            if ":id" in r:
                if pick:
                    res.append(r.replace(":id", str(pick)))
            else:
                res.append(r)
        out = res
        if pick:
            out.append(f"/campaigns/{pick}")
    return sorted(set(out))


def slug(route: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", route).strip("_") or "root"


def platform_fonts(ctx, page, selector: str):
    cdp = ctx.new_cdp_session(page)
    cdp.send("DOM.enable")
    cdp.send("CSS.enable")
    root = cdp.send("DOM.getDocument", {"depth": 1})["root"]["nodeId"]
    nid = cdp.send("DOM.querySelector", {"nodeId": root, "selector": selector})["nodeId"]
    return cdp.send("CSS.getPlatformFontsForNode", {"nodeId": nid})["fonts"]


def run(args: argparse.Namespace) -> int:
    out = Path(args.out)
    (out / "shots").mkdir(parents=True, exist_ok=True)
    vw, vh = (int(x) for x in args.viewport.split("x"))
    routes = args.routes.split(",") if args.routes else discover_routes(args.app, args.base_url)
    report: dict = {"app": args.app, "base_url": args.base_url, "lang": args.lang, "viewport": args.viewport, "routes": []}
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx = browser.new_context(viewport={"width": vw, "height": vh}, locale=args.browser_locale or "en-US")
        for route in routes:
            page = ctx.new_page()
            errs: list[str] = []
            failed: list[str] = []
            page.on("console", lambda m, errs=errs: errs.append(f"{m.type}: {m.text[:200]}") if m.type == "error" else None)
            page.on("pageerror", lambda e, errs=errs: errs.append(f"pageerror: {str(e)[:200]}"))
            page.on("requestfailed", lambda r, failed=failed: failed.append(f"{r.method} {r.url[:120]}"))
            sep = "&" if "?" in route else "?"
            url = args.base_url.rstrip("/") + route + (f"{sep}lang={args.lang}" if args.lang else "")
            entry: dict = {"route": route, "url": url}
            try:
                page.goto(url, wait_until="networkidle", timeout=60000)
            except Exception as e:  # noqa: BLE001
                entry["navigation_error"] = str(e)[:200]
            t0 = time.time()
            while time.time() - t0 < args.settle:  # never judge/screenshot a loading state
                try:
                    if page.evaluate(JS_SKELETON) == 0:
                        break
                except Exception:  # noqa: BLE001
                    break
                page.wait_for_timeout(400)
            page.wait_for_timeout(600)
            try:
                entry["html_lang"] = page.evaluate("() => document.documentElement.lang")
                entry["title"] = page.title()
                entry["skeletons_left"] = page.evaluate(JS_SKELETON)
                entry["i18n_missing"] = page.evaluate("() => (window.__i18nMissing ? Array.from(window.__i18nMissing).slice(0, 60) : null)")
                nodes = page.evaluate(JS_TEXT)
                entry["n_text"] = len(nodes)
                flagged, enums, fmt_bad, seen = [], [], [], set()
                for nd in nodes:
                    t = nd["t"]
                    if t in seen:
                        continue
                    seen.add(t)
                    for rx, why in FORMAT_PATTERNS:
                        if args.lang == "pl" and rx.search(t):
                            fmt_bad.append({"text": t[:140], "why": why, "tag": nd["tag"], "where": nd["cls"]})
                            break
                    f, why = english_score(t)
                    if f:
                        flagged.append({"text": t[:140], "why": why, "tag": nd["tag"], "where": nd["cls"]})
                    elif enum_raw(t):
                        enums.append({"text": t[:60], "tag": nd["tag"], "where": nd["cls"]})
                entry["english_suspects"] = flagged[:80]
                entry["raw_enums"] = enums[:30]
                entry["format_suspects"] = fmt_bad[:30]
                ov = page.evaluate(JS_OVERFLOW)
                entry["doc_overflow_x"] = ov["docOverflowX"]
                entry["clipped"] = ov["clipped"]
                if args.fonts:
                    probe = page.evaluate(JS_PROBE_TEXT)
                    entry["font_probe_text"] = probe
                    if probe:
                        try:
                            entry["fonts_for_polish_text"] = platform_fonts(ctx, page, "[data-pl-probe]")
                        except Exception as e:  # noqa: BLE001
                            entry["fonts_error"] = str(e)[:120]
                shot = out / "shots" / (slug(route) + ".png")
                page.screenshot(path=str(shot), full_page=False)
                entry["screenshot"] = str(shot)
            except Exception as e:  # noqa: BLE001
                entry["audit_error"] = str(e)[:200]
            entry["console_errors"] = errs[:10]
            entry["failed_requests"] = [f for f in failed if "favicon" not in f][:10]
            report["routes"].append(entry)
            page.close()
        if args.glyph_probe:
            page = ctx.new_page()
            page.goto(args.base_url.rstrip("/") + "/" + (f"?lang={args.lang}" if args.lang else ""), wait_until="networkidle", timeout=60000)
            page.evaluate(JS_GLYPH_DIV)
            page.wait_for_timeout(900)
            gp: dict = {}
            try:
                for kind in ("body", "display"):
                    gp[kind] = platform_fonts(ctx, page, f"[data-gp={kind}]")
            except Exception as e:  # noqa: BLE001
                gp["error"] = str(e)[:150]
            page.screenshot(path=str(out / "shots" / "_glyph_probe.png"), clip={"x": 0, "y": 0, "width": 760, "height": 110})
            report["glyph_probe"] = gp
            page.close()
        browser.close()
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf8")
    write_md(report, out / "report.md")
    tot_en = sum(len(r.get("english_suspects", [])) for r in report["routes"])
    tot_enum = sum(len(r.get("raw_enums", [])) for r in report["routes"])
    tot_err = sum(len(r.get("console_errors", [])) for r in report["routes"])
    tot_missing = sum(len(r.get("i18n_missing") or []) for r in report["routes"])
    tot_fmt = sum(len(r.get("format_suspects", [])) for r in report["routes"])
    print(
        f"audited {len(report['routes'])} routes: english suspects={tot_en} raw enums={tot_enum} format suspects={tot_fmt} "
        f"i18n missing={tot_missing} console errors={tot_err}"
    )
    print(f"report: {out / 'report.md'}")
    return 0


def write_md(rep: dict, path: Path) -> None:
    L = [f"# pl_audit — {rep['app']} ({rep['base_url']}) lang={rep['lang']} viewport={rep['viewport']}\n"]
    L.append("| route | html lang | text nodes | English suspects | raw enums | format suspects | i18n missing | doc overflow-x | clipped | console errors | skeletons |")
    L.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for r in rep["routes"]:
        L.append(
            f"| `{r['route']}` | {r.get('html_lang')} | {r.get('n_text', '?')} | {len(r.get('english_suspects', []))} | {len(r.get('raw_enums', []))} | "
            f"{len(r.get('format_suspects', []))} | {len(r.get('i18n_missing') or [])} | {r.get('doc_overflow_x', '?')} | {len(r.get('clipped', []))} | "
            f"{len(r.get('console_errors', []))} | {r.get('skeletons_left', '?')} |"
        )
    if rep.get("glyph_probe"):
        L.append("\n## Glyph probe (platform fonts used for `Zażółć gęślą jaźń ĄĆĘŁŃÓŚŹŻ`)\n")
        L.append("```json\n" + json.dumps(rep["glyph_probe"], ensure_ascii=False, indent=1) + "\n```")
    for r in rep["routes"]:
        L.append(f"\n## `{r['route']}`  — title: {r.get('title')!r}\n")
        if r.get("navigation_error"):
            L.append(f"- NAVIGATION ERROR: {r['navigation_error']}")
        if r.get("audit_error"):
            L.append(f"- AUDIT ERROR: {r['audit_error']}")
        for k in ("english_suspects", "raw_enums", "format_suspects"):
            if r.get(k):
                L.append(f"**{k}** ({len(r[k])}):")
                for s in r[k][:40]:
                    L.append(f"- `{s['text']}`" + (f" — {s['why']}" if "why" in s else "") + f"  [{s['tag']} {s['where']}]")
        if r.get("i18n_missing"):
            L.append("**window.__i18nMissing**: " + "; ".join(map(str, r["i18n_missing"][:30])))
        if r.get("clipped"):
            L.append(f"**clipped / ellipsised** ({len(r['clipped'])}):")
            for c in r["clipped"][:15]:
                L.append(f"- [{c['kind']}] `{c['text']}` ({c['tag']} {c['cls']}; sw={c['sw']} cw={c['cw']} sh={c['sh']} ch={c['ch']})")
        if r.get("fonts_for_polish_text"):
            L.append(f"fonts for Polish text `{r.get('font_probe_text')}`: " + json.dumps(r["fonts_for_polish_text"], ensure_ascii=False))
        if r.get("console_errors"):
            L.append("**console errors**: " + " | ".join(r["console_errors"][:5]))
        if r.get("failed_requests"):
            L.append("**failed requests**: " + " | ".join(r["failed_requests"][:5]))
    path.write_text("\n".join(L) + "\n", encoding="utf8")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--app", choices=["studio", "concierge"], required=True)
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--lang", default="pl")
    ap.add_argument("--viewport", default="1600x900")
    ap.add_argument("--routes", default="", help="comma-separated routes (default: discovered from /api/features)")
    ap.add_argument("--settle", type=float, default=12.0, help="max seconds to wait for skeletons/spinners per route")
    ap.add_argument("--browser-locale", default="", help="Playwright locale for the browser context (default en-US)")
    ap.add_argument("--no-fonts", dest="fonts", action="store_false", help="skip the CDP platform-font probe on page text")
    ap.add_argument("--no-glyph-probe", dest="glyph_probe", action="store_false", help="skip the injected glyph probe")
    sys.exit(run(ap.parse_args()))
