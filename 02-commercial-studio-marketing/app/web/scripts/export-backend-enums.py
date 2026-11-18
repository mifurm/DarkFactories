#!/usr/bin/env python
"""Exports the enum-like values the BACKEND can return (what the UI renders through dictionary groups) to src/i18n/backend-enums.json.

    npm run export:backend-enums            # rewrite the file
    npm run export:backend-enums -- --check # exit 1 when the checked-in file is out of date (the vitest `backend-enums.test.ts` then keeps it in sync with the Polish dictionary)

No server is needed — two static sources of the BE (app/src/spotlight), read-only:
  catalog   the message catalog (i18n/messages_pl.py): families of stable ids with localized labels — audit actions, Guardian checks, gates, roles, rule packs,
            territories, channels, rights kinds, tones, beat roles, verdicts, cost-call kinds, text kinds …
  code      literals found with the `ast` module: adapter ids (`{"backend": "azure-blob"}`), job kinds (`submit_job(request, "spot.render", …)`), job steps
            (`progress(step="render")`, f-string prefixes such as `transcreate-{lang}`), cost kinds (`meter.record(kind="llm")`), readiness probes (`_timed("ffmpeg", …)`),
            the OpenAI voice ids
and one hand-kept section that no static scan can see:
  observed  values seen on the deployed azure-mode instance (cost features such as "CS-07", performance sources such as "connector:meta", …). Edit it by hand;
            the generator preserves it.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

WEB = Path(__file__).resolve().parents[1]
SRC = WEB.parent / "src" / "spotlight"
OUT = WEB / "src" / "i18n" / "backend-enums.json"

CATALOG_FAMILIES = {
    "audit": "audit.",
    "label.call": "label.call.",
    "label.channel": "label.channel.",
    "label.check": "label.check.",
    "label.claim_type": "label.claim_type.",
    "label.gate": "label.gate.",
    "label.kind": "label.kind.",
    "label.pack": "label.pack.",
    "label.rkind": "label.rkind.",
    "label.role": "label.role.",
    "label.state": "label.state.",
    "label.status": "label.status.",
    "label.territory": "label.territory.",
    "label.tone": "label.tone.",
    "label.beat": "label.beat.",
    "label.verdict": "label.verdict.",
}
NOT_IDS = {"audit": {"with_stage"}}


def const_str(node: ast.AST | None) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def callee(call: ast.Call) -> str:
    f = call.func
    return f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else ""


def catalog_keys() -> list[str]:
    tree = ast.parse((SRC / "i18n" / "messages_pl.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        value = node.value if isinstance(node, (ast.Assign, ast.AnnAssign)) else None
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
        if isinstance(value, ast.Dict) and any(isinstance(t, ast.Name) and t.id == "MESSAGES" for t in targets):
            return [k for k in (const_str(x) for x in value.keys) if k]
    raise SystemExit("MESSAGES not found in i18n/messages_pl.py")


def fstring_prefix(node: ast.JoinedStr) -> str | None:
    first = node.values[0] if node.values else None
    return const_str(first) if first is not None else None


def code_values() -> dict[str, set[str]]:
    out: dict[str, set[str]] = {k: set() for k in ("backend", "jobKind", "jobStep", "jobStepPrefix", "costKind", "opsDependency", "openaiVoice")}
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict):
                for k, v in zip(node.keys, node.values, strict=False):
                    if const_str(k) == "backend" and const_str(v):
                        out["backend"].add(const_str(v) or "")
            elif isinstance(node, ast.Call):
                name = callee(node)
                if name == "submit_job" and len(node.args) >= 2 and const_str(node.args[1]):
                    out["jobKind"].add(const_str(node.args[1]) or "")
                if name == "_timed" and node.args and const_str(node.args[0]):
                    out["opsDependency"].add(const_str(node.args[0]) or "")
                if name == "VoiceInfo" and node.args and (vid := const_str(node.args[0])) and vid.startswith("openai:"):
                    out["openaiVoice"].add(vid)
                for kw in node.keywords:
                    if kw.arg == "step":
                        if s := const_str(kw.value):
                            out["jobStep"].add(s)
                        elif isinstance(kw.value, ast.JoinedStr) and (prefix := fstring_prefix(kw.value)):
                            out["jobStepPrefix"].add(prefix)
                    if kw.arg == "kind" and name in {"record", "authorize"} and const_str(kw.value):
                        out["costKind"].add(const_str(kw.value) or "")
    return out


def build(previous: dict) -> dict:
    keys = catalog_keys()
    catalog: dict[str, list[str]] = {}
    for family, prefix in CATALOG_FAMILIES.items():
        ids = sorted({k[len(prefix):] for k in keys if k.startswith(prefix)} - NOT_IDS.get(family, set()))
        catalog[family] = ids
    return {
        "_about": "Generated by scripts/export-backend-enums.py from the backend sources (catalog + code); `observed` is kept by hand. Checked by src/i18n/backend-enums.test.ts.",
        "catalog": catalog,
        "code": {k: sorted(v) for k, v in code_values().items()},
        "observed": previous.get("observed", {}),
    }


def main() -> int:
    previous = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    text = json.dumps(build(previous), ensure_ascii=False, indent=2) + "\n"
    if "--check" in sys.argv:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != text:
            print("backend-enums.json is out of date — run `npm run export:backend-enums`", file=sys.stderr)
            return 1
        print("backend-enums.json is up to date")
        return 0
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT.relative_to(WEB)}: " + ", ".join(f"{k}={len(v)}" for k, v in json.loads(text)["code"].items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
