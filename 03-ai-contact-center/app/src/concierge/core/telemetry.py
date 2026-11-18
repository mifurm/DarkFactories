"""Structured JSON logging (PII-redacted, request-id correlated) and OpenTelemetry -> Application Insights (Entra ingestion)."""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from typing import Any

from .config import Settings
from .redaction import redact_text
from .security import request_id_var

_RESERVED = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)) + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "msg": redact_text(record.getMessage()),
            "request_id": request_id_var.get(),
        }
        for k, v in record.__dict__.items():
            if k not in _RESERVED and not k.startswith("_"):
                payload[k] = redact_text(v) if isinstance(v, str) else v
        if record.exc_info:
            payload["exc"] = redact_text(self.formatException(record.exc_info))
        return json.dumps(payload, default=str)


def configure_logging() -> None:
    root = logging.getLogger()
    if any(getattr(h, "_concierge", False) for h in root.handlers):
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler._concierge = True  # type: ignore[attr-defined]
    root.handlers = [handler]
    root.setLevel(os.environ.get("LOG_LEVEL", "INFO"))
    for noisy in ("azure", "httpx", "httpcore", "websockets", "openai", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def configure_azure_monitor_if_enabled(settings: Settings) -> bool:  # pragma: no cover - needs Azure
    """Send traces/metrics/logs to Application Insights using the managed identity (local auth is disabled on the resource)."""
    if not (settings.is_azure and settings.app_insights_connection):
        return False
    try:
        from azure.identity import ManagedIdentityCredential
        from azure.monitor.opentelemetry import configure_azure_monitor

        cred = ManagedIdentityCredential(client_id=settings.client_id or None)
        configure_azure_monitor(
            connection_string=settings.app_insights_connection,
            credential=cred,
            logger_name="concierge",
            enable_live_metrics=False,
        )
        return True
    except Exception as exc:
        logging.getLogger("concierge").warning("azure monitor not configured: %s", exc)
        return False


def instrument_app(app: Any) -> None:  # pragma: no cover - needs Azure
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app, excluded_urls="healthz,readyz")
    except Exception as exc:
        logging.getLogger("concierge").warning("fastapi instrumentation skipped: %s", exc)


def get_tracer():
    from opentelemetry import trace

    return trace.get_tracer("concierge")


def get_meter():
    from opentelemetry import metrics

    return metrics.get_meter("concierge")
