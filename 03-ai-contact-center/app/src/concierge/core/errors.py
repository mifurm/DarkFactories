"""Localized, backward-compatible error bodies.

Every error response keeps its historic shape (`detail`, `error`, ...) and gains stable `code` plus localized `message` / `hint` rendered in the
request locale from the message catalogs. The English `detail` strings raised across the features are mapped to stable codes here, so the
call sites do not change."""

from __future__ import annotations

from typing import Any

from . import i18n

ERROR_BY_TEXT: dict[str, str] = {
    "conversation not found": "conversation_not_found",
    "run not found": "run_not_found",
    "unknown scenario": "unknown_scenario",
    "approval not found": "approval_not_found",
    "take over the conversation first": "takeover_required",
    "order not found": "order_not_found",
    "unknown payment session": "unknown_payment_session",
    "digit must be 0-9, * or #": "invalid_digit",
    "no handoff for this conversation": "no_handoff",
    "conversation is not waiting for a human": "not_waiting_for_human",
    "customer not found": "customer_not_found",
    "wrap-up not generated yet": "wrapup_not_ready",
    "unknown disposition code": "unknown_disposition",
    "review not found": "review_not_found",
    "scores must use the rubric dimensions with values 1-5": "invalid_scores",
    "trace not found": "trace_not_found",
    "config not found": "config_not_found",
    "already active": "already_active",
    "history not seeded yet": "history_not_seeded",
    "topic not found": "topic_not_found",
    "document not found": "document_not_found",
    "document or version not found": "document_not_found",
    "file too large": "file_too_large",
    "supported: .md .txt .html .pdf": "unsupported_file_type",
    "chunk not found": "chunk_not_found",
    "q must be 2-300 characters": "invalid_query",
    "no earlier version to roll back to": "no_earlier_version",
    "as_of must be an ISO timestamp": "invalid_timestamp",
    "no campaign for this trigger": "campaign_not_found",
    "campaign not found": "campaign_not_found",
    "no preferences on file": "no_preferences",
    "worker not found": "worker_not_found",
    "conversation already ended": "conversation_ended",
    "no matching customer": "no_matching_customer",
    "source must be all | synthetic | live": "invalid_source",
}
ERROR_BY_PREFIX: tuple[tuple[str, str], ...] = (
    ("unknown variant", "unknown_variant"),
    ("unknown queue", "unknown_queue"),
    ("already ", "already_decided"),
    ("invalid token", "invalid_token"),
)
STATUS_CODE: dict[int, str] = {400: "validation_error", 401: "invalid_token", 403: "forbidden", 404: "not_found", 405: "method_not_allowed", 409: "knowledge_conflict", 413: "payload_too_large", 422: "validation_error", 429: "rate_limited", 500: "internal_error", 503: "voice_busy"}


def code_for(status: int, detail: Any) -> str:
    if isinstance(detail, dict) and isinstance(detail.get("error"), str):
        return detail["error"]
    if isinstance(detail, str):
        if detail in ERROR_BY_TEXT:
            return ERROR_BY_TEXT[detail]
        for prefix, code in ERROR_BY_PREFIX:
            if detail.startswith(prefix):
                return code
    return STATUS_CODE.get(status, "generic")


def error_fields(code: str, lang: str | None = None, *, fallback: str | None = None) -> dict[str, str]:
    """Stable `code` plus localized `message` / `hint` (hint only when the catalog has one). English keeps the historic message text when one exists."""
    lang = i18n.normalize(lang) or i18n.current_locale()
    out = {"code": code}
    key = f"err.{code}"
    if lang == "en" and fallback:
        out["message"] = fallback
    else:
        out["message"] = i18n.msg(key, lang) if i18n.has(key) else (fallback or i18n.msg("err.generic", lang))
    if i18n.has(f"{key}.hint"):
        out["hint"] = i18n.msg(f"{key}.hint", lang)
    return out


def error_body(status: int, detail: Any, *, request_id: str | None = None, lang: str | None = None) -> dict[str, Any]:
    lang = i18n.normalize(lang) or i18n.current_locale()
    code = code_for(status, detail)
    fallback = detail if isinstance(detail, str) else (detail.get("message") if isinstance(detail, dict) else None)
    fields = error_fields(code, lang, fallback=fallback if isinstance(fallback, str) else None)
    body: dict[str, Any] = {"detail": detail, "error": code, **fields}
    if lang != "en" and i18n.has(f"err.{code}"):
        if isinstance(detail, dict):
            body["detail"] = {**detail, "message": fields["message"], **({"hint": fields["hint"]} if "hint" in fields else {})}
        elif isinstance(detail, str):
            body["detail"] = fields["message"]
    if request_id:
        body["request_id"] = request_id
    return body
