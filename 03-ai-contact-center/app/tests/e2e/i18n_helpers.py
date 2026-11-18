"""Shared helpers of the Polish journeys: the English-leftover scan, the missing-translation check and the overflow / clipping check.

The English word lists are shared with the UI dictionary lint (`web/src/i18n/leftovers.json`), so the unit test (vitest) and the browser scan agree on
what counts as an English leftover. Everything here only reads the rendered page; it works against any base URL (local build or the live app)."""

from __future__ import annotations

import json
import re
from pathlib import Path

from playwright.sync_api import Page

APP = Path(__file__).resolve().parents[2]
LISTS = json.loads((APP / "web" / "src" / "i18n" / "leftovers.json").read_text(encoding="utf-8"))
PL_CHARS = re.compile(r"[ąćęłńóśźżĄĆĘŁŃÓŚŹŻ]")
ENGLISH = {w.lower() for w in LISTS["functionWords"] + LISTS["uiWords"]}
ALLOW_WORDS = {w.lower() for w in LISTS["allowWords"]}
ALLOW_PHRASES = LISTS["allowPhrases"]
# technical names that look like English words but are proper names, identifiers or Polish words in this product
EXTRA_ALLOWED = {"home", "limit", "offline", "update", "audit", "total", "start", "reset", "login", "premium", "standard", "plan", "service", "region"}
# a lowercase compound identifier as a whole text node (`kb_embed`, `rules+llm`, `consent:email`) / snake_case or `+` token inside a sentence
IDENT_WHOLE = re.compile(r"[a-z][a-z0-9]*(?:[-_+:/][a-z0-9]+)+")  # dotted names (permissions, event names, hosts) are code, not enum values
IDENT_EMBEDDED = re.compile(r"(?<![\w.@/:-])[a-z][a-z0-9]*(?:[_+][a-z0-9]+)+(?![\w@-])")
# technical names that are meant to be shown as they are: the embedder id, connector names, user / actor ids, language-pair lists
TECH_OK = re.compile(r"e-mail|c-tf-idf|(?:azure|hash):[\w:.\-]+|[a-z]{2}(?:/[a-z]{2})+|mock-crm|generic-rest|dynamics365-dataverse|concierge-ai|demo-[a-z]+|(?:admin|agent|qa|supervisor|wfm|auditor|customer|system|ai):[\w\-]+")
# parameter / tag names that documentation sentences quote literally (Realtime VAD settings, legal-hold tag) and the tool names (engine/tools.py build_registry()): code, like the monospace chips
TECH_TOKENS = {
    "legal_hold", "server_vad", "interrupt_response",
    "check_return_eligibility", "create_ticket", "end_conversation", "escalate_to_human", "get_available_slots", "goodwill_credit", "initiate_return", "issue_refund",
    "list_orders", "lookup_customer", "lookup_order", "request_payment", "reschedule_delivery", "schedule_pickup", "search_knowledge", "send_confirmation",
    "start_verification", "track_shipment", "update_address", "update_ticket", "verify_kba", "verify_otp", "warranty_claim",
}  # fmt: skip

# visible text (nodes, placeholders, aria-labels, titles, option labels) outside user / conversation content
JS_VISIBLE_TEXT = """
() => {
  const out = [];
  const skip = '[data-user-content], [data-i18n-skip], [role=log], pre, code, textarea, script, style, noscript, .font-mono';
  const visible = (el) => {
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 || r.height > 0 || el.closest('.sr-only') !== null;
  };
  const foreignLang = (el) => {
    const l = el.closest('[lang]');
    return !!l && l !== document.documentElement && !(l.getAttribute('lang') || '').toLowerCase().startsWith('pl');
  };
  const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let n;
  while ((n = w.nextNode())) {
    const t = (n.nodeValue || '').replace(/\\s+/g, ' ').trim();
    const el = n.parentElement;
    if (!t || !el || el.closest(skip) || foreignLang(el) || !visible(el)) continue;
    out.push({ t, where: el.tagName.toLowerCase() + (el.className && typeof el.className === 'string' ? '.' + el.className.split(' ')[0] : '') });
  }
  for (const el of document.querySelectorAll('[placeholder],[aria-label],[title],img[alt]')) {
    if (el.closest(skip) || foreignLang(el) || !visible(el)) continue;
    for (const a of ['placeholder', 'aria-label', 'title', 'alt']) {
      const v = el.getAttribute(a);
      if (v && v.trim()) out.push({ t: v.trim(), where: '@' + a + ' ' + el.tagName.toLowerCase() });
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
    if (el.closest('.sr-only, [data-allow-clip]')) continue;
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') continue;
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;
    const ox = cs.overflowX, oy = cs.overflowY;
    const clipX = (ox === 'hidden' || ox === 'clip') && el.scrollWidth > el.clientWidth + 2;
    const clipY = (oy === 'hidden' || oy === 'clip') && el.scrollHeight > el.clientHeight + 2;
    const ell = cs.textOverflow === 'ellipsis' && el.scrollWidth > el.clientWidth + 1;
    if (!(clipX || clipY || ell)) continue;
    const text = (el.innerText || '').replace(/\\s+/g, ' ').trim();
    if (!text) continue;
    res.clipped.push({ tag: el.tagName.toLowerCase(), cls: (typeof el.className === 'string' ? el.className : '').slice(0, 60), kind: clipX ? 'x' : clipY ? 'y' : 'ellipsis', text: text.slice(0, 80), sw: el.scrollWidth, cw: el.clientWidth });
  }
  return res;
}
"""


def english_tokens(text: str) -> list[str]:
    """English function / UI words in `text` (ids, placeholders, brand names and allow-listed phrases removed first)."""
    s = re.sub(r"\b[A-Za-z]{1,4}[-_][0-9A-Za-z]{5,}\b", " ", text)  # cv_0be6107d7f, out-27c2d24202, CH-100350, H-01861 …
    for phrase in ALLOW_PHRASES:
        s = s.replace(phrase, " ")
    tokens = re.findall(r"[^\W\d_]+", s.lower())
    return sorted({t for t in tokens if t in ENGLISH and t not in ALLOW_WORDS and t not in EXTRA_ALLOWED})


def looks_english(text: str) -> str | None:
    """Reason when `text` is an English leftover (two or more English words, or a short text with one and no Polish letters)."""
    found = english_tokens(text)
    if len(found) >= 2:
        return "english words: " + ", ".join(found[:5])
    if len(found) == 1 and not PL_CHARS.search(text) and len(re.findall(r"[^\W\d_]+", text)) <= 4:
        return "english word: " + found[0]
    return None


def raw_identifier(text: str) -> str | None:
    """Why `text` is a machine identifier shown to a Polish reader (rules+llm, kb_embed, consent:email, azure_prompt_shields), or None.
    Whole text nodes made of one lowercase compound token, and snake_case / `+` tokens inside a sentence (a code quoted in parentheses is a reference, not the label);
    technical names, ids and versions (anything with a digit) are exempt."""
    t = text.strip()
    if IDENT_WHOLE.fullmatch(t):
        if re.search(r"\d", t) or TECH_OK.fullmatch(t) or t.startswith(("cv_", "out-", "camp-")):  # record ids: conversations, outbound messages, campaigns
            return None
        return "raw identifier"
    for token in IDENT_EMBEDDED.findall(re.sub(r"\([^)]*\)", " ", t)):
        if not re.search(r"\d", token) and token not in TECH_TOKENS and not token.startswith(("cv_", "out_")):
            return f"raw identifier {token!r} inside a sentence"
    return None


def scan_english(page: Page) -> list[str]:
    """Visible UI text that still looks English, plus raw machine identifiers (monospace identifiers and user content are exempt). Chart text (SVG axes) is included."""
    bad: list[str] = []
    seen: set[str] = set()
    for item in page.evaluate(JS_VISIBLE_TEXT):
        text = item["t"]
        if text in seen:
            continue
        seen.add(text)
        why = looks_english(text) or raw_identifier(text)
        if why:
            bad.append(f"{text[:100]!r} ({why}) [{item['where']}]")
    return bad


def missing_keys(page: Page) -> list[str]:
    return list(page.evaluate("() => (window.__i18nMissing ? Array.from(window.__i18nMissing) : [])"))


# one entry per message row of every transcript (role=log); tool chips, monospace identifiers and buttons are not message text
JS_TRANSCRIPT = """
(selector) => {
  const out = [];
  for (const root of document.querySelectorAll(selector)) {
    for (const row of root.children) {
      const c = row.cloneNode(true);
      c.querySelectorAll('.font-mono, pre, code, [data-user-content], span[title], button, .sr-only, [aria-hidden=true]').forEach((e) => e.remove());
      const t = (c.textContent || '').replace(/\\s+/g, ' ').trim();
      if (t) out.push(t);
    }
  }
  return out;
}
"""
IDENTIFIER = re.compile(r"\b[a-z]+(?:[_.][a-z]+)+\b")  # search_knowledge, realtime.call.incoming


def scan_transcript(page: Page, selector: str = "[role=log]") -> list[str]:
    """Messages of the transcripts that are not Polish: what the assistant, the system and the captions say must follow the conversation language."""
    bad: list[str] = []
    for text in page.evaluate(JS_TRANSCRIPT, selector):
        why = looks_english(IDENTIFIER.sub(" ", text))
        if why:
            bad.append(f"{text[:140]!r} ({why})")
    return bad


def assert_text_polish(text: str, *, where: str = "") -> None:
    """Model-written prose that is shown as the model wrote it (a hand-off summary): no English words. Codes the model quotes (`legal_threat`) are not judged here."""
    why = looks_english(IDENTIFIER.sub(" ", text))
    assert not why, f"English in a Polish text [{where}]: {text[:160]!r} ({why})"


def assert_transcript_polish(page: Page, *, where: str = "", selector: str = "[role=log]", allow_english: tuple[str, ...] = ()) -> None:
    """A Polish conversation has Polish assistant / system / caption messages (the page scan skips transcripts, so this checks them separately)."""
    label = f" [{where or page.url}]"
    rows = page.evaluate(JS_TRANSCRIPT, selector)
    assert rows, f"no transcript message found{label}"
    bad = [b for b in scan_transcript(page, selector) if not any(a in b for a in allow_english)]
    assert not bad, f"English in a Polish transcript{label}: {bad[:5]}"


def overflow(page: Page) -> dict:
    return page.evaluate(JS_OVERFLOW)


def assert_polish(page: Page, *, where: str = "", allow_english: tuple[str, ...] = (), check_overflow: bool = True) -> None:
    """The page is fully Polish: `<html lang=pl>`, no missing translation, no English leftover, no horizontal overflow or clipped text."""
    label = f" [{where or page.url}]"
    assert page.evaluate("document.documentElement.lang") == "pl", "html lang must be pl" + label
    assert not missing_keys(page), f"window.__i18nMissing is not empty{label}: {missing_keys(page)[:10]}"
    leftovers = [b for b in scan_english(page) if not any(a in b for a in allow_english)]
    assert not leftovers, f"English leftovers{label}: {leftovers[:8]}"
    if check_overflow:
        o = overflow(page)
        assert o["docOverflowX"] <= 1, f"the page scrolls horizontally by {o['docOverflowX']}px{label}"
        assert not o["clipped"], f"clipped or ellipsised text{label}: {o['clipped'][:6]}"
