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
    ) -> None:
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        if status:
            self.status = status
        self.hint = hint
        self.details = details

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.hint:
            out["hint"] = self.hint
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
