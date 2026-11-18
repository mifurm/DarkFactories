"""Per-page quality checks used by journeys_pl.py: English leftovers, raw enums, pl-PL formatting, overflow / clipping, font glyphs.

The English-leftover heuristic is the one of tools/pl_audit/pl_audit.py (stop-words / UI vocabulary), tightened for this app:
text that is customer or generated CONTENT (campaign names, asset names, quoted copy, the English demo campaigns) is exempt,
as are code samples (API paths) and a short list of words that are ordinary Polish (limit, format, min, status …).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from playwright.sync_api import BrowserContext, Page

PL_CHARS = re.compile(r"[ąćęłńóśźżĄĆĘŁŃÓŚŹŻ]")

EN_STOP = {"the", "and", "for", "with", "your", "you", "from", "this", "that", "are", "is", "were", "be", "been", "have", "has", "not", "can", "will", "would", "should", "could", "of", "in", "at", "or", "an", "its", "our", "their", "they", "them", "we", "us", "all", "any", "more", "some", "such", "only", "than", "then", "there", "here", "what", "when", "where", "which", "who", "why", "how", "into", "about", "over", "after", "before", "between", "through", "during", "under", "again", "once", "per", "via", "each", "other", "new"}
EN_UI = {"save", "cancel", "create", "delete", "remove", "edit", "add", "search", "filter", "export", "import", "upload", "download", "close", "open", "back", "next", "previous", "submit", "apply", "reset", "refresh", "loading", "settings", "overview", "details", "name", "description", "title", "type", "date", "time", "total", "average", "count", "none", "yes", "today", "yesterday", "week", "month", "year", "min", "max", "draft", "approved", "rejected", "pending", "completed", "active", "paused", "blocked", "warning", "error", "success", "failed", "passed", "running", "queue", "customer", "customers", "order", "orders", "refund", "return", "returns", "show", "hide", "view", "select", "choose", "click", "enter", "send", "message", "messages", "history", "help", "about", "home", "dashboard", "login", "logout", "user", "users", "role", "roles", "team", "members", "share", "copy", "paste", "update", "updated", "created", "deleted", "retry", "continue", "finish", "done", "ready", "waiting", "online", "offline", "enabled", "disabled", "default", "custom", "advanced", "basic", "general", "summary", "report", "reports", "result", "results", "score", "scores", "rate", "rates", "cost", "costs", "price", "prices", "budget", "spend", "spent", "limit", "limits", "daily", "weekly", "monthly", "insights", "performance", "campaign", "campaigns", "brand", "rights", "claims", "library", "asset", "assets", "variant", "variants", "experiment", "experiments", "approvals", "audit", "trail", "guardian", "provenance"}
# raw status / enum values that must not stand alone in the UI (the dictionary has a label for each)
# words that are never Polish: descriptors of voices / styles and the Recharts legend aria-labels ("v01 legend icon") — one of them is enough to flag a text
EN_DESC = {"legend", "icon", "deep", "authoritative", "bright", "upbeat", "calm", "composed", "neutral", "clear", "friendly", "expressive", "storyteller", "warm", "neural", "voices", "voice", "sample", "preview"}
ENUM_RAW = {
    "draft", "approved", "rejected", "pending", "completed", "active", "paused", "blocked", "warn", "warning", "pass", "fail", "failed", "open", "closed", "resolved", "escalated",
    "running", "queued", "done", "error", "success", "published", "history", "block", "control", "localized", "cutdown", "synthetic", "live", "idle", "in_review", "changes_requested",
    "needs_substantiation", "prohibited", "expired", "revoked", "licensed", "unlicensed", "tampered", "verified",
}
# tokens that are fine in a Polish UI: product / brand names, acronyms and the loan words Polish professionals use unchanged
ALLOW_WORDS = {
    "contoso", "northwind", "azure", "openai", "spotlight", "swarmai", "dawn", "roast", "gpt", "api", "json", "csv", "pdf", "mp4", "srt", "sms", "otp", "kpi", "sla", "qa", "csat", "nps",
    "roas", "ctr", "cvr", "cpa", "roi", "acr", "npv", "irr", "ai", "llm", "rag", "pii", "rodo", "gdpr", "rbac", "ffprobe", "ffmpeg", "c2pa", "tts", "stt", "ok", "id", "url", "http", "https",
    "cosmos", "db", "blob", "sse", "tiktok", "youtube", "meta", "ctv", "linkedin", "display", "midnight", "blend", "cold", "brew", "cans", "wcag", "openapi", "swagger", "ed25519",
    "sha", "lufs", "h264", "aac", "e2e", "fabric", "onelake", "videoprovider", "iac", "bicep", "r128", "ebu", "wav", "png", "zip", "readyz", "healthz", "dam", "adls", "sku", "skus", "cu", "tb",
    "usd", "eur", "pln", "instagram", "google", "p50", "p95", "p10", "p90", "thompson", "ucb",
    # ordinary Polish words / loan words that Polish marketing professionals use unchanged
    "limit", "format", "min", "status", "audio", "video", "model", "persona", "region", "premium", "generator", "logo", "studio", "master", "claim", "claims", "brand", "hook", "cta", "render",
    "talent", "stock", "webhook", "webhooks", "storyboard", "spot", "bumper", "poster", "feed", "reel", "reels", "story", "stories", "bandit", "seed", "simulated",
    # territory / language codes
    "us", "uk", "gb", "eu", "de", "fr", "pl", "es", "it", "nl", "en", "pt",
}
# multi-word product names stay as they are (removed before the text is scored)
PRODUCT_NAMES = re.compile(
    r"Azure AI (?:Content Safety|Search|Speech|Language|Foundry)|Azure Cosmos DB|Azure OpenAI|Azure Retail Prices API|Service Bus|Event Grid|Front Door|Container Apps|Brand Brain|Brand Guardian|"
    r"Content Safety|Prompt Shields|Entra ID|Microsoft Fabric|Application Insights|Log Analytics|Key Vault|Blob Storage|Teams|Slack|OpenAPI|"
    # technical text that is not UI wording: licence names, model / voice ids ("neural:pl-PL-ZofiaNeural", "gpt-image-1.5"), price-tier names, Recharts' built-in aria-labels
    r"Open source|TTS (?:neural|standard|hd)|[a-z]+:[A-Za-z0-9_.-]+|gpt-[\w.-]+|legend icon",
    re.I,
)
# English headings of the sample campaigns / demo content may legitimately appear (the app ships an English and a Polish campaign side by side)
CONTENT_HINTS = ("Dawn Roast", "Midnight Blend", "Northwind", "E2E", "smoke", "Cold Brew")

JS_TEXT = r"""
() => {
  const out = [];
  const vis = (el) => {
    if (!el) return false;
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden' || cs.opacity === '0') return false;
    const r = el.getBoundingClientRect();
    return !(r.width === 0 && r.height === 0);
  };
  const skip = 'script,style,noscript,textarea,code,pre,kbd,samp,[data-user-content],[contenteditable=true],.recharts-wrapper svg text.nope';
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let n;
  while ((n = walker.nextNode())) {
    const t = (n.nodeValue || '').replace(/\s+/g, ' ').trim();
    if (!t) continue;
    const el = n.parentElement;
    if (!el || el.closest(skip) || !vis(el)) continue;
    if (el.tagName === 'OPTION') continue; // options are read below with their select
    out.push({ t, tag: el.tagName, cls: (el.className && el.className.toString().slice(0, 40)) || '' });
  }
  for (const s of document.querySelectorAll('select')) {
    if (!vis(s) || s.closest('[data-user-content]')) continue;
    for (const op of s.options) { const t = (op.textContent || '').replace(/\s+/g, ' ').trim(); if (t) out.push({ t, tag: 'OPTION', cls: 'select-option' }); }
  }
  for (const el of document.querySelectorAll('[placeholder],[aria-label],[title],img[alt]')) {
    if (!vis(el) || el.closest('[data-user-content],code,pre')) continue;
    for (const a of ['placeholder', 'aria-label', 'title', 'alt']) {
      const v = el.getAttribute(a);
      if (v && v.trim()) out.push({ t: v.trim(), tag: el.tagName, cls: '@' + a });
    }
  }
  return out;
}
"""

JS_OVERFLOW = r"""
() => {
  const res = { docX: 0, mainX: 0, clipped: [], selects: [], inputs: [] };
  const de = document.documentElement;
  res.docX = de.scrollWidth - de.clientWidth;
  const main = document.querySelector('main');
  if (main) res.mainX = main.scrollWidth - main.clientWidth;
  const visible = (el) => {
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };
  const isClip = (v) => v === 'hidden' || v === 'clip';
  // 1) text whose box leaves an ancestor that clips (overflow hidden/clip) — scroll containers (auto/scroll) are fine
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let n;
  const seen = new Set();
  while ((n = walker.nextNode())) {
    const txt = (n.nodeValue || '').replace(/\s+/g, ' ').trim();
    const el = n.parentElement;
    if (!txt || !el || el.closest('.sr-only,script,style,option') || !visible(el)) continue;
    const range = document.createRange();
    range.selectNodeContents(n);
    const rects = [...range.getClientRects()].filter((r) => r.width > 0 && r.height > 0);
    if (!rects.length) continue;
    const r = rects.reduce((a, b) => ({ left: Math.min(a.left, b.left), right: Math.max(a.right, b.right), top: Math.min(a.top, b.top), bottom: Math.max(a.bottom, b.bottom) }));
    for (let a = el; a && a !== document.documentElement; a = a.parentElement) {
      const cs = getComputedStyle(a);
      if (cs.display === 'contents') continue;
      const ar = a.getBoundingClientRect();
      const ox = isClip(cs.overflowX), oy = isClip(cs.overflowY);
      const scroll = /(auto|scroll)/.test(cs.overflowX + cs.overflowY);
      if (scroll && a !== document.body) break; // inside a scroller: it scrolls, nothing is lost
      if (ox && cs.textOverflow === 'ellipsis') break; // an ellipsis box is checked separately (it needs a tooltip with the full text)
      const outX = ox && (r.right > ar.right + 1.5 || r.left < ar.left - 1.5);
      const outY = oy && (r.bottom > ar.bottom + 1.5 || r.top < ar.top - 1.5);
      if (outX || outY) {
        const key = txt.slice(0, 40) + a.tagName;
        if (!seen.has(key)) {
          seen.add(key);
          res.clipped.push({ text: txt.slice(0, 80), by: a.tagName + '.' + (a.className || '').toString().slice(0, 40), kind: outX ? 'x' : 'y' });
        }
        break;
      }
    }
  }
  // 2) ellipsis without a tooltip carrying the full text
  for (const el of document.querySelectorAll('body *')) {
    if (!visible(el) || el.closest('.sr-only')) continue;
    const cs = getComputedStyle(el);
    if (cs.textOverflow === 'ellipsis' && el.scrollWidth > el.clientWidth + 1 && !el.getAttribute('title') && !el.closest('[title]')) {
      res.clipped.push({ text: (el.innerText || '').trim().slice(0, 80), by: el.tagName + ' (ellipsis, no title)', kind: 'x' });
    }
  }
  // 3) <select> whose selected option does not fit
  const ctx = document.createElement('canvas').getContext('2d');
  for (const s of document.querySelectorAll('select')) {
    if (!visible(s)) continue;
    const cs = getComputedStyle(s);
    ctx.font = `${cs.fontStyle} ${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`;
    const txt = s.options[s.selectedIndex]?.textContent || '';
    let widest = 0;
    for (const op of s.options) widest = Math.max(widest, ctx.measureText(op.textContent || '').width);
    const avail = s.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight) - 22; // native arrow
    if (ctx.measureText(txt).width > avail + 8 && !(window.__content || []).some((c) => txt.includes(c))) res.selects.push({ text: txt.slice(0, 60), need: Math.round(ctx.measureText(txt).width), have: Math.round(avail), widest: Math.round(widest) });
  }
  // 4) single-line inputs whose placeholder is cut off
  for (const i of document.querySelectorAll('input[placeholder],textarea[placeholder]')) {
    if (!visible(i) || i.value) continue;
    const cs = getComputedStyle(i);
    ctx.font = `${cs.fontStyle} ${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`;
    const avail = i.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
    const need = ctx.measureText(i.getAttribute('placeholder') || '').width;
    if (i.tagName === 'INPUT' && need > avail + 1) res.inputs.push({ text: (i.getAttribute('placeholder') || '').slice(0, 70), need: Math.round(need), have: Math.round(avail) });
  }
  return res;
}
"""

JS_GLYPH = (
    "() => { const d = document.createElement('div'); d.id='glyphprobe'; "
    "d.style.cssText='position:fixed;left:0;top:0;z-index:99999;background:#fff;color:#000;padding:8px;font-size:22px'; "
    "d.innerHTML = '<div data-gp=\"body\" style=\"font-family:var(--font-sans, inherit)\">ąćęłńóśźżĄĆĘŁŃÓŚŹŻ</div>"
    "<div data-gp=\"display\" style=\"font-family:var(--font-display, var(--font-sans, inherit))\">ąćęłńóśźżĄĆĘŁŃÓŚŹŻ</div>'; "
    "document.body.appendChild(d); }"
)

FORMAT_PATTERNS = [
    (re.compile(r"\b(?:NaN|undefined|null|Invalid Date)\b|\[object Object\]"), "bad value rendered"),
    (re.compile(r"\{[A-Za-z_][A-Za-z0-9_]*\}"), "unresolved {placeholder}"),
    (re.compile(r"\b(?:0?[1-9]|1[0-2])/(?:0?[1-9]|[12]\d|3[01])/20\d\d\b"), "US-style date (expected 18.11.2026)"),
    (re.compile(r"\b\d{1,2}:\d{2}\s?(?:AM|PM|am|pm)\b"), "12-hour clock (expected 24 h)"),
    (re.compile(r"\b\d{1,3}(?:,\d{3}){2,}\b"), "US-style number grouping (expected 1 234 567)"),
    (re.compile(r"[$£]\s?\d"), "currency symbol before the number"),
    (re.compile(r"\b[2-4] [a-ząćęłńóśźż]{3,}ów\b"), "genitive plural after 2-4 (expected nominative plural)"),
    (re.compile(r"\b1 [a-ząćęłńóśźż]{3,}(?:ów|ach|ami)\b"), "plural noun after 1"),
]


@dataclass
class PageFindings:
    route: str
    english: list[str] = field(default_factory=list)
    enums: list[str] = field(default_factory=list)
    formats: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    overflow: list[str] = field(default_factory=list)

    def problems(self) -> list[str]:
        out: list[str] = []
        out += [f"english: {x}" for x in self.english]
        out += [f"raw enum: {x}" for x in self.enums]
        out += [f"format: {x}" for x in self.formats]
        out += [f"i18n missing: {x}" for x in self.missing]
        out += [f"overflow: {x}" for x in self.overflow]
        return out


def _words(t: str) -> list[str]:
    return re.findall(r"[A-Za-z][A-Za-z'’-]*", t)


def english_score(t: str) -> tuple[bool, str]:
    if len(t) < 3 or not re.search(r"[A-Za-z]", t):
        return False, ""
    if re.fullmatch(r"[\W\d_]*[A-Z]{1,4}-?\d*[\W\d_]*", t):  # codes: CS-01, L1, P95
        return False, ""
    low = [w.lower().strip("'’-") for w in _words(PRODUCT_NAMES.sub(" ", t))]
    cand = [w for w in low if w not in ALLOW_WORDS]
    if not cand:
        return False, ""
    has_pl = bool(PL_CHARS.search(t))
    stops = [w for w in cand if w in EN_STOP and len(w) >= 3]  # "in", "we" … are abbreviations in Polish text (m.in., (WE))
    ui = [w for w in cand if w in EN_UI]
    desc = [w for w in cand if w in EN_DESC]
    if desc and not has_pl:
        return True, "English descriptor: " + ", ".join(sorted(set(desc))[:4])
    if len(stops) >= 2:
        return True, "stop-words: " + ", ".join(sorted(set(stops))[:5])
    if len(stops) == 1 and len(cand) <= 4 and not has_pl:
        return True, "word: " + stops[0]
    if ui and not has_pl and len(cand) <= 3 and all(w in EN_UI or w in ALLOW_WORDS for w in low):
        return True, "UI word: " + ", ".join(sorted(set(ui))[:4])
    if len(cand) >= 4 and not has_pl and len(ui) >= 1:
        return True, "UI vocabulary: " + ", ".join(sorted(set(ui))[:4])
    return False, ""


def is_raw_enum(t: str) -> bool:
    s = t.strip().strip(".:·•").lower()
    return s in ENUM_RAW and re.fullmatch(r"[A-Za-z _-]+", t.strip()) is not None


def scan_page(page: Page, route: str, content: set[str] | None = None, lang: str = "pl", extra_allow: list[str] | None = None) -> PageFindings:
    """Collects every finding for the page in its current state. `content` = customer/generated strings that may stay as they are."""
    f = PageFindings(route)
    content = content or set()
    allow = [re.compile(p) for p in (extra_allow or [])]
    miss = page.evaluate("() => (window.__i18nMissing ? Array.from(window.__i18nMissing).map((m) => `${m.kind}:${m.key}`) : ['window.__i18nMissing is not defined'])")
    f.missing = list(miss)[:20]
    seen: set[str] = set()
    for nd in page.evaluate(JS_TEXT):
        t = nd["t"]
        if t in seen:
            continue
        seen.add(t)
        if any(c and c in t for c in content) or any(h in t for h in CONTENT_HINTS) or any(a.search(t) for a in allow) or re.search(r"(^|\s)/api/|^(GET|POST|PUT|PATCH|DELETE) |^SSE: ", t):
            continue
        if lang == "pl":
            for rx, why in FORMAT_PATTERNS:
                if rx.search(t):
                    f.formats.append(f"{t[:90]!r} — {why}")
                    break
            flag, why = english_score(t)
            if flag:
                f.english.append(f"{t[:110]!r} — {why} [{nd['tag']} {nd['cls']}]")
            elif is_raw_enum(t):
                f.enums.append(f"{t[:60]!r} [{nd['tag']} {nd['cls']}]")
    page.evaluate("(c) => { window.__content = c; }", sorted(content))
    ov = page.evaluate(JS_OVERFLOW)
    if ov["docX"] > 1:
        f.overflow.append(f"document scrolls horizontally by {ov['docX']}px")
    if ov["mainX"] > 1:
        f.overflow.append(f"main area scrolls horizontally by {ov['mainX']}px")
    for c in ov["clipped"][:8]:
        f.overflow.append(f"text clipped ({c['kind']}) {c['text']!r} by {c['by']}")
    for s in ov["selects"][:6]:
        f.overflow.append(f"select cuts its value {s['text']!r} (needs {s['need']}px, has {s['have']}px)")
    for i in ov["inputs"][:6]:
        f.overflow.append(f"placeholder cut off {i['text']!r} (needs {i['need']}px, has {i['have']}px)")
    return f


def glyph_check(ctx: BrowserContext, page: Page) -> list[str]:
    """Polish letters must be drawn by the bundled Inter / Fraunces (latin-ext), not by a fallback font."""
    problems: list[str] = []
    page.evaluate(JS_GLYPH)
    page.wait_for_timeout(700)
    cdp = ctx.new_cdp_session(page)
    cdp.send("DOM.enable")
    cdp.send("CSS.enable")
    root = cdp.send("DOM.getDocument", {"depth": 1})["root"]["nodeId"]
    for kind, want in (("body", "Inter"), ("display", "Fraunces")):
        nid = cdp.send("DOM.querySelector", {"nodeId": root, "selector": f"[data-gp={kind}]"})["nodeId"]
        fonts = cdp.send("CSS.getPlatformFontsForNode", {"nodeId": nid})["fonts"]
        used = {x["familyName"]: x["glyphCount"] for x in fonts}
        if want not in used or not all(x["isCustomFont"] for x in fonts):
            problems.append(f"{kind}: Polish letters are not rendered by the bundled {want} (platform fonts: {used})")
        elif used[want] < 18:
            problems.append(f"{kind}: only {used[want]}/18 Polish letters come from {want} (rest: {used})")
    page.evaluate("() => document.getElementById('glyphprobe')?.remove()")
    return problems
