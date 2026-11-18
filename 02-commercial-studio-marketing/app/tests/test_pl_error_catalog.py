"""Every ``raise`` of an application error has a Polish message: its catalog entry exists and all of its placeholders are supplied by the raise site.

Without this a Polish user could read "{id}" or an English fallback; ``AppError.localized`` keeps such a gap harmless at runtime, this test keeps it from existing."""

from __future__ import annotations

import ast
import pathlib

from spotlight.errors import AppError
from spotlight.errors import __dict__ as errors_namespace
from spotlight.i18n import CATALOGS, has, placeholders

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "spotlight"
APP_ERRORS = {name: cls for name, cls in errors_namespace.items() if isinstance(cls, type) and issubclass(cls, AppError)}


def _forms(value):
    return list(value.values()) if isinstance(value, dict) else [value]


def _const(node: ast.AST | None):
    return node.value if isinstance(node, ast.Constant) else None


def _raise_sites():
    for path in sorted(SRC.rglob("*.py")):
        if "vendor" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call) and isinstance(node.exc.func, ast.Name) and node.exc.func.id in APP_ERRORS):
                continue
            call = node.exc
            kw = {k.arg: k.value for k in call.keywords if k.arg}
            default_code = APP_ERRORS[call.func.id].code
            yield f"{path.relative_to(SRC)}:{node.lineno}", default_code, kw


def test_every_raise_site_has_a_polish_catalog_entry_and_supplies_its_placeholders():
    checked = dynamic = 0
    problems: list[str] = []
    for where, default_code, kw in _raise_sites():
        code = _const(kw.get("code")) if "code" in kw else default_code
        key = _const(kw["key"]) if "key" in kw else (f"err.{code}" if code else None)
        if key is None:  # a computed key/code (re-raised from a stored record): covered by the localized() fallback
            dynamic += 1
            continue
        checked += 1
        if not (has(key, "pl") and key in CATALOGS["pl"]):
            if code in {"not_found", "conflict", "forbidden", "validation_failed", "bad_request"} and "code" not in kw:
                problems.append(f"{where}: raised with the generic class code '{code}' (give it a specific code= and a catalog entry)")
            else:
                problems.append(f"{where}: no Polish catalog entry for {key}")
            continue
        params = kw.get("params")
        if params is None:
            supplied: set[str] | None = set()
        elif isinstance(params, ast.Dict) and all(isinstance(k, ast.Constant) for k in params.keys):
            supplied = {str(k.value) for k in params.keys if isinstance(k, ast.Constant)}
        else:
            supplied = None  # dynamic params (e.g. ``exc.params``): checked at runtime by ``localized``
        if supplied is None:
            continue
        for k in (key, f"{key}.hint"):
            if k not in CATALOGS["pl"]:
                continue
            need = set().union(*(placeholders(x) for x in _forms(CATALOGS["pl"][k])))
            if need - supplied:
                problems.append(f"{where}: {k} needs {sorted(need - supplied)} but the raise site supplies {sorted(supplied)}")
    assert checked > 100, (checked, dynamic)
    assert not problems, "\n".join(problems)


def test_every_error_catalog_entry_exists_in_both_languages_with_the_same_placeholders():
    en, pl = CATALOGS["en"], CATALOGS["pl"]
    for key in (k for k in en if k.startswith("err.")):
        assert key in pl, key
        assert set().union(*(placeholders(x) for x in _forms(en[key]))) == set().union(*(placeholders(x) for x in _forms(pl[key]))), key
