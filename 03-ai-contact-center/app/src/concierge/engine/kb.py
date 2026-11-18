"""Knowledge base (CC-03): heading-aware chunking, embeddings, hybrid retrieval (vector + BM25), citations, document versions with
draft -> publish -> rollback, injection quarantine, groundedness checks. In-process index persisted in Cosmos (AI Search = scale-out path)."""

from __future__ import annotations

import hashlib
import html.parser
import io
import math
import re
import time
from collections import Counter
from functools import lru_cache
from typing import Any

import numpy as np

from ..core.ai.embedding import cosine_matrix
from ..core.langid import detect_language
from ..core.repo import Repository
from .audit import AuditLog
from .guard import sanitize_untrusted_document
from .understanding import fold

_STOP = frozenset(["a", "an", "the", "and", "or", "of", "to", "in", "on", "at", "for", "with", "is", "are", "was", "were", "be", "been", "it", "this", "that", "these", "those", "i", "you", "we", "they", "he", "she", "my", "your", "our", "do", "does", "did", "can", "could", "would", "should", "will", "may", "might", "have", "has", "had", "not", "no", "yes", "if", "so", "but", "as", "by", "from", "about", "into", "than", "then", "them", "us", "its", "it's"])
_TOK = re.compile(r"[a-z0-9äöüß]+")


def _stem(t: str) -> str:
    if len(t) > 4:
        if t.endswith("ies"):
            return t[:-3] + "y"
        for suf in ("ung", "ing", "ed", "es", "en", "er", "te", "ten"):
            if t.endswith(suf) and len(t) - len(suf) >= 4:
                return t[: -len(suf)]
        if t.endswith(("s", "e", "t")) and not t.endswith("ss") and len(t) > 5:
            return t[:-1]
    return t


# Domain synonym map (query expansion for the offline lexical/hashed retrieval path; real embeddings handle this natively)
SYNONYMS: dict[str, list[str]] = {
    "late": ["delay", "delayed"], "compensation": ["goodwill", "credit"], "compensate": ["goodwill", "credit"], "voucher": ["goodwill", "credit"],
    "date": ["reschedule", "window"], "change": ["reschedule", "move"], "postpone": ["reschedule"], "cost": ["price", "eur"], "fee": ["cost", "eur"],
    "broken": ["damaged"], "cracked": ["damaged"], "money": ["refund"], "back": ["return"], "send": ["return"], "wrong": ["incorrect", "address"],
    "nobody": ["missed", "attempt"], "home": ["missed", "attempt"], "absent": ["missed"], "installer": ["installation", "appointment"],
    "installing": ["installation"], "install": ["installation"], "guarantee": ["warranty"], "repair": ["warranty"],
    "sms": ["otp", "code"], "recording": ["record", "disclosure"], "delete": ["deletion", "data"], "personal": ["data"],
    "beschädigt": ["damaged", "schaden"], "geliefert": ["lieferung", "delivery"], "rückgabe": ["return"], "erstattung": ["refund"], "garantie": ["warranty"],
    "abholung": ["pickup"], "lieferung": ["delivery"], "schaden": ["damage", "damaged"],
}


# Polish concept -> English words (query expansion for the offline lexical / hashed retrieval path; real embeddings are cross-lingual natively)
_SYN_PL_WORDS: dict[str, list[str]] = {
    "uszkodzony": ["damaged", "damage", "broken"], "zniszczony": ["damaged", "damage"], "rozbity": ["damaged", "broken"], "pekniety": ["damaged", "cracked"], "uszkodzenie": ["damaged", "damage"],
    "zwrot": ["return", "refund"], "zwrocic": ["return"], "zwracam": ["return"], "odeslac": ["return"], "pieniadze": ["refund", "money"], "pieniedzy": ["refund", "money"], "srodkow": ["refund"],
    "wymiana": ["replacement", "exchange"], "wymienic": ["replacement", "exchange"], "gwarancja": ["warranty", "guarantee"], "rekojmia": ["warranty"], "reklamacja": ["warranty", "claim", "complaint"],
    "naprawa": ["repair", "warranty"], "dostawa": ["delivery"], "dostarczyc": ["delivery"], "przesylka": ["delivery", "shipment", "parcel"], "paczka": ["delivery", "parcel"], "kurier": ["carrier", "delivery"],
    "przewoznik": ["carrier"], "termin": ["date", "window", "reschedule"], "przelozyc": ["reschedule"], "zmiana": ["change"], "zmienic": ["change"], "adres": ["address"], "montaz": ["installation", "assembly"],
    "monter": ["installer", "installation", "appointment"], "faktura": ["invoice"], "platnosc": ["payment"], "karta": ["card"], "karty": ["card"], "raty": ["instalments", "payment"], "bon": ["voucher", "credit", "goodwill"],
    "rekompensata": ["compensation", "goodwill", "credit"], "odszkodowanie": ["compensation", "goodwill"], "opoznienie": ["delay", "delayed", "late"], "opozniony": ["delay", "delayed", "late"],
    "dane": ["data", "personal"], "rodo": ["gdpr", "data", "privacy", "deletion"], "usunac": ["deletion", "delete", "data"], "usuniecie": ["deletion", "delete", "data"], "nagrywanie": ["recording", "record"],
    "nagrywana": ["recording", "record"], "weryfikacja": ["verification", "identity", "otp"], "godziny": ["hours", "opening"], "odbior": ["pickup", "collection"], "bezplatny": ["free"], "bezplatnie": ["free"],
    "materac": ["mattress"], "sofa": ["sofa"], "kanapa": ["sofa"], "pralka": ["washing", "machine"], "zmywarka": ["dishwasher"], "lodowka": ["fridge"], "szafa": ["wardrobe"], "piekarnik": ["oven"],
    "gaz": ["gas", "smell", "safety"], "gazu": ["gas", "smell", "safety"], "dym": ["smoke", "safety"], "iskry": ["sparks", "safety"], "pozar": ["fire", "safety"], "skarga": ["complaint", "complaints"],
    "rzecznik": ["ombudsman", "consumer"], "czyszczenie": ["cleaning", "care"], "pielegnacja": ["care", "cleaning"], "okres": ["period", "days"], "dni": ["days"], "czas": ["time", "days"], "kosztuje": ["cost", "price"],
    "cena": ["price", "cost"], "metody": ["methods"], "tracking": ["tracking"], "sledzenie": ["tracking", "status"], "odstapienie": ["withdrawal", "return"], "umowy": ["return"],
}  # fmt: skip


@lru_cache(maxsize=1)
def _syn_pl() -> dict[str, list[str]]:
    return {_stem_pl(k): v for k, v in _SYN_PL_WORDS.items()}


def expand_pl(text: str) -> list[str]:
    """English words that stand for the Polish concepts in `text` (stem lookup)."""
    syn = _syn_pl()
    out: list[str] = []
    for tok in _TOK.findall(fold(text)):
        out.extend(syn.get(_stem_pl(tok), []))
    return list(dict.fromkeys(out))


# "how long / how much time" questions are answered by the article's term ("termin") and number of days: Polish stand-ins appended to the Polish query tokens
_SYN_PL_PL: dict[str, list[str]] = {"czas": ["termin", "dni"], "dlugo": ["termin", "dni"], "kiedy": ["termin"], "terminie": ["dni"]}


def expand_pl_pl(text: str) -> list[str]:
    out: list[str] = []
    for tok in _TOK.findall(fold(text)):
        out.extend(_SYN_PL_PL.get(_stem_pl(tok), _SYN_PL_PL.get(tok, [])))
    return list(dict.fromkeys(out))


def expand(text: str) -> str:
    extra: list[str] = []
    for tok in _TOK.findall(fold(text)):
        extra.extend(SYNONYMS.get(tok, []))
    return text + " " + " ".join(extra) if extra else text


# ---- Polish: light stemming (the endings of the Polish cases / genders are stripped, the stem is cut to six letters) and stop words - applied to Polish chunks and queries only
_STOP_PL = frozenset(["i", "w", "na", "z", "ze", "do", "nie", "to", "sie", "jest", "sa", "a", "o", "od", "po", "za", "dla", "czy", "jak", "co", "ale", "lub", "oraz", "przez", "przy", "ten", "ta", "te", "tym", "tego", "tej", "moze", "moga", "mozna", "mam", "ma", "mamy", "masz", "byl", "byla", "bylo", "bedzie", "tak", "juz", "tylko", "wiec", "bardzo", "tez", "ktory", "ktora", "ktore", "ktorzy", "gdy", "gdyby", "zeby", "aby", "by", "jesli", "bo", "pan", "pani", "panstwo", "panstwa", "prosze", "chce", "chcialbym", "chcialabym", "moj", "moja", "moje", "mojego", "mojej"])
_PL_ENDING = re.compile(r"(?:ami|ach|owi|ego|emu|ymi|imi|iem|ie|ia|ii|iu|om|ow|e|y|i|a|u|o)$")


def _stem_pl(t: str) -> str:
    if len(t) > 4:
        t = _PL_ENDING.sub("", t) if len(_PL_ENDING.sub("", t)) >= 4 else t
    return t[:6]


def is_polish(text: str) -> bool:
    lang, conf = detect_language(text, default="en")
    return lang == "pl" and conf >= 0.5


_EN_KEYWORDS = re.compile(r"(?im)^keywords \(en\):.*$")


def tokens(text: str, lang: str | None = None) -> list[str]:
    """Search tokens. `lang="pl"` (a Polish chunk or query) uses Polish stop words and stemming - except the `Keywords (en):` line of a Polish article, which is
    English and keeps the English stemmer so that English questions can reach the article; every other language keeps the historic English / German stemmer."""
    if lang == "pl":
        keywords = " ".join(m.group(0) for m in _EN_KEYWORDS.finditer(text))
        body = _EN_KEYWORDS.sub(" ", text)
        polish = [_stem_pl(t) for t in _TOK.findall(fold(body)) if t not in _STOP_PL and len(t) > 1]
        return polish + [_stem(t) for t in _TOK.findall(fold(keywords)) if t not in _STOP and len(t) > 1]
    return [_stem(t) for t in _TOK.findall(fold(text)) if t not in _STOP and len(t) > 1]


def chunk_markdown(text: str, max_chars: int = 760, overlap: int = 90) -> list[tuple[str, str]]:
    """Heading-aware chunking -> [(heading path, chunk text)]."""
    chunks: list[tuple[str, str]] = []
    heading = ""
    buf: list[str] = []

    def flush() -> None:
        body = "\n".join(buf).strip()
        if not body:
            return
        if len(body) <= max_chars:
            chunks.append((heading, body))
        else:
            start = 0
            while start < len(body):
                end = min(len(body), start + max_chars)
                cut = body.rfind(". ", start, end) if end < len(body) else end
                end = cut + 1 if cut > start + max_chars // 2 else end
                chunks.append((heading, body[start:end].strip()))
                if end >= len(body):
                    break
                start = max(end - overlap, start + 1)

    for line in text.splitlines():
        if re.match(r"^#{1,3}\s+", line):
            flush()
            buf = []
            heading = re.sub(r"^#{1,3}\s+", "", line).strip()
            buf.append(line)
        else:
            buf.append(line)
    flush()
    return [(h, t) for h, t in chunks if len(re.sub(r"^#{1,3}\s+.*$", "", t, flags=re.MULTILINE).strip()) > 40]


class _HtmlText(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.out: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in ("script", "style"):
            self._skip += 1
        elif tag in ("h1", "h2", "h3"):
            self.out.append("\n" + "#" * int(tag[1]) + " ")
        elif tag == "li":
            self.out.append("\n- ")
        elif tag in ("p", "br", "div", "tr"):
            self.out.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style") and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.out.append(data)


def extract_text(filename: str, data: bytes, content_type: str = "") -> str:
    name = filename.lower()
    if name.endswith(".pdf") or content_type == "application/pdf":
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        return "\n\n".join((p.extract_text() or "") for p in reader.pages[:60])
    text = data.decode("utf-8", "replace")
    if name.endswith((".html", ".htm")) or "html" in content_type:
        parser = _HtmlText()
        parser.feed(text)
        return re.sub(r"\n{3,}", "\n\n", "".join(parser.out)).strip()
    return text


class BM25:
    def __init__(self, docs: list[list[str]], k1: float = 1.4, b: float = 0.75) -> None:
        self.k1, self.b = k1, b
        self.docs = [Counter(d) for d in docs]
        self.len = np.array([len(d) for d in docs], dtype=float)
        self.avg = float(self.len.mean()) if len(docs) else 0.0
        df: Counter[str] = Counter()
        for d in self.docs:
            df.update(d.keys())
        n = max(len(docs), 1)
        self.idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}

    def scores(self, query: list[str]) -> np.ndarray:
        out = np.zeros(len(self.docs))
        for i, d in enumerate(self.docs):
            s = 0.0
            for t in query:
                f = d.get(t, 0)
                if f:
                    s += self.idf.get(t, 0) * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * self.len[i] / (self.avg or 1)))
            out[i] = s
        return out


class GroupedBM25:
    """BM25 statistics are kept per language group (Polish chunks / every other chunk), so adding the Polish articles does not change a single score of the
    English and German ones; the per-group scores are merged into one array aligned with the chunk list."""

    def __init__(self, chunks: list[dict[str, Any]]) -> None:
        self.n = len(chunks)
        by_group: dict[str, list[int]] = {"pl": [], "other": []}
        doc_keywords: dict[str, str] = {}  # the `Keywords (en):` line sits in one chunk of a Polish article; every chunk of that article shares it
        for i, c in enumerate(chunks):
            by_group["pl" if c.get("lang") == "pl" else "other"].append(i)
            if c.get("lang") == "pl" and (line := _EN_KEYWORDS.search(c["text"])):
                doc_keywords[c["doc_id"]] = line.group(0)

        def doc_text(c: dict[str, Any]) -> str:
            text = f"{c['title']} {c['heading']} {c['text']}"
            kw = doc_keywords.get(c["doc_id"]) if c.get("lang") == "pl" else None
            return text if not kw or kw in text else f"{text}\n{kw}"

        self.groups = [
            (np.array(idx), BM25([tokens(doc_text(chunks[i]), chunks[i].get("lang")) for i in idx]))
            for idx in by_group.values() if idx
        ]  # fmt: skip

    def scores(self, query: list[str]) -> np.ndarray:
        out = np.zeros(self.n)
        for idx, bm in self.groups:
            out[idx] = bm.scores(query)
        return out


class KnowledgeBase:
    def __init__(self, repo: Repository, llm: Any, audit: AuditLog, guard: Any | None = None) -> None:
        self.repo = repo
        self.llm = llm
        self.audit = audit
        self.guard = guard
        self.chunks: list[dict[str, Any]] = []
        self._emb: np.ndarray = np.zeros((0, 512))
        self._bm25: GroupedBM25 | None = None
        self.embedder_id = "hash:512" if getattr(llm, "deterministic", True) else "azure:text-embedding-3-small:512"
        self.min_cosine = 0.17 if self.embedder_id.startswith("hash") else 0.30
        self.min_bm25 = 7.5
        self.version = 0  # index generation counter

    # ------------------------------------------------------------------ index
    async def load_index(self) -> dict[str, int]:
        rows = await self.repo.query("kb_chunks", {"status": "published"})
        stale = [r for r in rows if r.get("embedder") != self.embedder_id]
        if stale:
            vecs = await self.llm.embed([r["text"] for r in stale], feature="kb_embed")
            for r, v in zip(stale, vecs, strict=True):
                r["embedding"] = [round(float(x), 5) for x in v]
                r["embedder"] = self.embedder_id
            await self.repo.put_many("kb_chunks", stale)
        rows.sort(key=lambda r: (r["doc_id"], r["n"]))
        self.chunks = rows
        self._emb = np.array([r["embedding"] for r in rows], dtype=np.float64) if rows else np.zeros((0, 512))
        self._bm25 = GroupedBM25(rows) if rows else None
        self.version += 1
        return {"chunks": len(rows), "re_embedded": len(stale)}

    # ------------------------------------------------------------------ documents
    async def ingest(
        self, *, title: str, text: str, category: str = "general", lang: str = "en", tags: list[str] | None = None, doc_id: str | None = None,
        source: str = "upload", author: str = "system", publish: bool = False, note: str = "", reindex: bool = True, sanitize: bool = True,
    ) -> dict[str, Any]:  # fmt: skip
        text = text.strip()[:200_000]
        doc_id = doc_id or f"kb-{re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')[:40]}-{hashlib.sha1(title.encode()).hexdigest()[:6]}"
        clean, reasons = sanitize_untrusted_document(text) if sanitize else (text, [])
        digest = hashlib.sha256(clean.encode()).hexdigest()
        doc = await self.repo.get("kb_docs", doc_id) or {
            "id": doc_id, "title": title, "category": category, "lang": lang, "tags": tags or [], "source": source,
            "published_version": None, "latest_version": 0, "quarantined": False, "created_at": time.time(),
        }  # fmt: skip
        latest = await self.repo.get("kb_versions", f"{doc_id}@{doc['latest_version']}") if doc["latest_version"] else None
        if latest and latest["hash"] == digest and doc["title"] == title:
            if publish and doc["published_version"] != latest["version"]:
                await self.publish(doc_id, latest["version"], actor=author, reindex=reindex)
                return {"doc_id": doc_id, "version": latest["version"], "unchanged": True, "published": True}
            return {"doc_id": doc_id, "version": latest["version"], "unchanged": True, "published": doc["published_version"] == latest["version"]}
        version = doc["latest_version"] + 1
        doc.update({"title": title, "category": category, "lang": lang, "tags": tags or doc.get("tags", []), "latest_version": version, "updated_at": time.time(), "quarantined": bool(reasons) or doc.get("quarantined", False)})
        await self.repo.put("kb_versions", {"id": f"{doc_id}@{version}", "doc_id": doc_id, "version": version, "title": title, "text": clean, "hash": digest, "status": "draft", "created_at": time.time(), "created_by": author, "note": note, "quarantine_reasons": reasons})
        await self.repo.put("kb_docs", doc)
        await self.audit.log("kb.ingest", actor=author, resource=f"{doc_id}@{version}", detail={"title": title, "quarantine_reasons": reasons, "bytes": len(text)})
        if reasons and self.guard:
            self.guard.stats["kb_quarantined"] += 1
        if publish:
            await self.publish(doc_id, version, actor=author, reindex=reindex)
        return {"doc_id": doc_id, "version": version, "unchanged": False, "published": publish, "quarantine_reasons": reasons}

    async def ingest_file(self, filename: str, data: bytes, content_type: str = "", **meta: Any) -> dict[str, Any]:
        text = extract_text(filename, data, content_type)
        title = meta.pop("title", None) or re.sub(r"[_-]+", " ", filename.rsplit(".", 1)[0]).strip().title()
        return await self.ingest(title=title, text=text, **meta)

    async def publish(self, doc_id: str, version: int | None = None, actor: str = "system", reindex: bool = True) -> dict[str, Any]:
        doc = await self.repo.get("kb_docs", doc_id)
        if not doc:
            raise KeyError(doc_id)
        version = version or doc["latest_version"]
        ver = await self.repo.get("kb_versions", f"{doc_id}@{version}")
        if not ver:
            raise KeyError(f"{doc_id}@{version}")
        if doc["published_version"] == version and any(c["doc_id"] == doc_id and c["version"] == version for c in self.chunks):
            return {"doc_id": doc_id, "version": version, "already_published": True}
        previous = doc["published_version"]
        if previous and previous != version:
            for old in await self.repo.query("kb_chunks", {"doc_id": doc_id}):
                await self.repo.delete("kb_chunks", old["id"])
            prev = await self.repo.get("kb_versions", f"{doc_id}@{previous}")
            if prev:
                prev["status"] = "archived"
                await self.repo.put("kb_versions", prev)
        parts = chunk_markdown(ver["text"])
        vecs = await self.llm.embed([f"{doc['title']}\n{h}\n{t}" for h, t in parts], feature="kb_embed")
        rows = [
            {"id": f"{doc_id}@{version}.{i}", "doc_id": doc_id, "version": version, "n": i, "title": doc["title"], "heading": h, "text": t, "category": doc["category"], "lang": doc["lang"], "tags": doc["tags"], "status": "published", "embedding": [round(float(x), 5) for x in v], "embedder": self.embedder_id}
            for i, ((h, t), v) in enumerate(zip(parts, vecs, strict=True))
        ]  # fmt: skip
        await self.repo.put_many("kb_chunks", rows)
        ver["status"] = "published"
        await self.repo.put("kb_versions", ver)
        doc["published_version"] = version
        doc["updated_at"] = time.time()
        await self.repo.put("kb_docs", doc)
        await self.audit.log("kb.publish", actor=actor, resource=f"{doc_id}@{version}", detail={"chunks": len(rows), "previous": previous})
        if reindex:
            await self.load_index()
        return {"doc_id": doc_id, "version": version, "chunks": len(rows), "previous": previous}

    async def rollback(self, doc_id: str, actor: str = "system") -> dict[str, Any]:
        doc = await self.repo.get("kb_docs", doc_id)
        if not doc or not doc["published_version"]:
            raise KeyError(doc_id)
        earlier = sorted((v for v in await self.repo.query("kb_versions", {"doc_id": doc_id}) if v["version"] < doc["published_version"]), key=lambda v: v["version"])
        if not earlier:
            raise ValueError("no earlier version to roll back to")
        target = earlier[-1]["version"]
        res = await self.publish(doc_id, target, actor=actor)
        await self.audit.log("kb.rollback", actor=actor, resource=doc_id, detail={"to_version": target})
        return {**res, "rolled_back_to": target}

    async def list_docs(self) -> list[dict[str, Any]]:
        docs = await self.repo.query("kb_docs", order_by="id")
        counts = Counter(c["doc_id"] for c in self.chunks)
        return [{**d, "chunks": counts.get(d["id"], 0)} for d in docs]

    async def get_doc(self, doc_id: str) -> dict[str, Any] | None:
        doc = await self.repo.get("kb_docs", doc_id)
        if not doc:
            return None
        versions = sorted(await self.repo.query("kb_versions", {"doc_id": doc_id}), key=lambda v: v["version"], reverse=True)
        return {**doc, "versions": versions}

    async def chunk(self, chunk_id: str) -> dict[str, Any] | None:
        for c in self.chunks:
            if c["id"] == chunk_id:
                return {k: v for k, v in c.items() if k != "embedding"}
        row = await self.repo.get("kb_chunks", chunk_id)
        return {k: v for k, v in row.items() if k != "embedding"} if row else None

    # ------------------------------------------------------------------ retrieval
    async def search(self, query: str, k: int = 4, category: str | None = None, include_drafts: bool = False, prefer_lang: str | None = None) -> dict[str, Any]:
        pool_chunks, pool_emb, pool_bm = self.chunks, self._emb, self._bm25
        if include_drafts:
            drafts = []
            for d in await self.repo.query("kb_docs"):
                if d["latest_version"] and d["latest_version"] != d["published_version"]:
                    ver = await self.repo.get("kb_versions", f"{d['id']}@{d['latest_version']}")
                    if ver:
                        for i, (h, t) in enumerate(chunk_markdown(ver["text"])):
                            drafts.append({"id": f"{d['id']}@{ver['version']}.{i}", "doc_id": d["id"], "version": ver["version"], "n": i, "title": d["title"], "heading": h, "text": t, "category": d["category"], "lang": d["lang"], "tags": d["tags"], "status": "draft"})
            if drafts:
                vecs = await self.llm.embed([f"{c['title']}\n{c['heading']}\n{c['text']}" for c in drafts], feature="kb_embed")
                for c, v in zip(drafts, vecs, strict=True):
                    c["embedding"] = v
                pool_chunks = self.chunks + drafts
                pool_emb = np.vstack([self._emb, np.array([c["embedding"] for c in drafts])]) if len(self._emb) else np.array([c["embedding"] for c in drafts])
                pool_bm = GroupedBM25(pool_chunks)
        if not pool_chunks or pool_bm is None:
            return {"hits": [], "answerable": False, "best_cosine": 0.0, "best_bm25": 0.0, "embedder": self.embedder_id}
        polish = prefer_lang == "pl" or is_polish(query)
        if polish:
            extras = expand_pl(query) if self.embedder_id.startswith("hash") else []
            q = f"{query} {' '.join(extras)}".strip()
            q_tokens = tokens(query + " " + " ".join(expand_pl_pl(query)), "pl") + tokens(" ".join(extras), "en")  # the Polish words are stemmed the Polish way, their English stand-ins the English way
        else:
            q = expand(query) if self.embedder_id.startswith("hash") else query
            q_tokens = tokens(q)
        qv = np.array((await self.llm.embed([q], feature="kb_query"))[0], dtype=np.float64)
        cos = cosine_matrix(qv, pool_emb)
        bm = pool_bm.scores(q_tokens)
        bm_n = bm / (bm.max() or 1.0)
        fused = 0.6 * np.clip(cos, 0, 1) + 0.4 * bm_n
        if prefer_lang:
            fused = fused + np.array([0.08 if c.get("lang") == prefer_lang else 0.0 for c in pool_chunks])  # answer a Polish question from the Polish article when both exist
        order = np.argsort(-fused)
        hits: list[dict[str, Any]] = []
        for idx in order:
            c = pool_chunks[int(idx)]
            if category and c["category"] != category:
                continue
            hits.append({"doc_id": c["doc_id"], "chunk_id": c["id"], "title": c["title"], "heading": c["heading"], "text": c["text"], "version": c["version"], "category": c["category"], "lang": c["lang"], "status": c.get("status", "published"), "score": round(float(fused[idx]), 4), "cosine": round(float(cos[idx]), 4), "bm25": round(float(bm[idx]), 3)})
            if len(hits) >= k:
                break
        best_cos = max((h["cosine"] for h in hits), default=0.0)
        best_bm = max((h["bm25"] for h in hits), default=0.0)
        if self.embedder_id.startswith("hash"):
            answerable = best_bm >= 9.0 or (best_bm >= 5.8 and best_cos >= 0.12) or (best_cos >= 0.45 and best_bm >= 3.5)
        else:
            answerable = best_cos >= 0.32 or (best_cos >= 0.22 and best_bm >= 5.8) or best_bm >= 9.0
        answerable = bool(hits) and answerable
        return {"hits": hits, "answerable": answerable, "best_cosine": best_cos, "best_bm25": best_bm, "embedder": self.embedder_id}

    async def seed(self, force: bool = False) -> dict[str, Any]:
        """Idempotent and self-repairing: unchanged published documents are skipped; documents left half-published by an interrupted start are completed."""
        from .kb_seed import KB_DOCS
        from .kb_seed_pl import KB_DOCS_PL

        created = 0
        for d in [*KB_DOCS, *KB_DOCS_PL]:
            res = await self.ingest(doc_id=d["id"], title=d["title"], text=d["text"], category=d["category"], lang=d["lang"], tags=d["tags"], source="seed", author="seed", publish=True, reindex=False)
            created += 0 if res.get("unchanged") and res.get("published") else 1
        stats = await self.load_index()
        return {"documents": len(KB_DOCS) + len(KB_DOCS_PL), "created": created, "polish_documents": len(KB_DOCS_PL), **stats}
