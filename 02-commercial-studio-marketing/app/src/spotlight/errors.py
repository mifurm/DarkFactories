"""Application errors with stable machine-readable codes (rendered as JSON by the API layer)."""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    status = 400
    code = "bad_request"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        status: int | None = None,
        hint: str | None = None,
        details: Any = None,
        params: dict[str, Any] | None = None,
        key: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        if status:
            self.status = status
        self.hint = hint
        self.details = details
        self.params = params or {}
        self.key = key  # catalog key; defaults to ``err.<code>`` (variants: ``err.<code>.<variant>``)

    def localized(self, locale: str | None = None) -> tuple[str, str | None]:
        """(message, hint) in ``locale``. English keeps the text exactly as raised; other languages come from the catalog by ``code``.

        A catalog template whose placeholders are not all supplied by ``params`` is never shown half-rendered ("{id}"): the English text as
        raised is used instead (a unit test scans every raise site so this fallback is never needed in practice)."""
        from .i18n import DEFAULT, current_locale, has, placeholders
        from .i18n import t as tr
        from .i18n.catalog import entry

        loc = locale or current_locale()
        if loc == DEFAULT:
            return self.message, self.hint
        key = self.key or f"err.{self.code}"
        if not has(key, loc):
            return self.message, self.hint
        raw = entry(key, loc)
        need = set().union(*(placeholders(x) for x in (raw.values() if isinstance(raw, dict) else [raw])))
        if need - set(self.params):
            return self.message, self.hint
        hint = tr(f"{key}.hint", loc, **self.params) if has(f"{key}.hint", loc) else self.hint
        return tr(key, loc, **self.params), hint

    def to_dict(self, locale: str | None = None) -> dict[str, Any]:
        message, hint = self.localized(locale)
        out: dict[str, Any] = {"code": self.code, "message": message}
        if hint:
            out["hint"] = hint
        if self.details is not None:
            out["details"] = self.details
        return out


class NotFound(AppError):
    status = 404
    code = "not_found"


class Conflict(AppError):
    status = 409
    code = "conflict"


class Forbidden(AppError):
    status = 403
    code = "forbidden"


class ValidationFailed(AppError):
    status = 422
    code = "validation_failed"


class BudgetExceeded(AppError):
    status = 402
    code = "budget_exceeded"


class RateLimited(AppError):
    status = 429
    code = "rate_limited"


class GuardianBlocked(AppError):
    status = 422
    code = "guardian_blocked"


class ProviderUnavailable(AppError):
    status = 503
    code = "provider_unavailable"


class PayloadTooLarge(AppError):
    status = 413
    code = "payload_too_large"
