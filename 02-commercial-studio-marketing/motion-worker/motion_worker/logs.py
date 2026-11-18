"""JSON-lines logging (one object per line on stdout) so Container Apps / Log Analytics can query fields."""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any, TextIO

LOG = logging.getLogger("motion_worker")

_CORE_KEYS = frozenset({"ts", "level", "logger", "event"})


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        doc: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            doc.update({k: v for k, v in fields.items() if k not in _CORE_KEYS})
        if record.exc_info:
            doc["exc"] = self.formatException(record.exc_info)[-4000:]
        return json.dumps(doc, ensure_ascii=False, default=str, separators=(",", ":"))


def configure_logging(level: str = "INFO", stream: TextIO | None = None) -> None:
    """Idempotent: replaces the handlers of the ``motion_worker`` logger."""
    handler = logging.StreamHandler(stream or sys.stdout)
    handler.setFormatter(JsonFormatter())
    LOG.handlers[:] = [handler]
    LOG.setLevel(getattr(logging, str(level).upper(), logging.INFO))
    LOG.propagate = False


def event(name: str, /, level: int = logging.INFO, **fields: Any) -> None:
    """Emit a structured event, e.g. ``event("job_done", job_id=..., gpu_seconds=...)``.

    ``name`` is positional-only so that a field called ``name`` can never collide with it.
    """
    LOG.log(level, name, extra={"fields": fields})


def exception_event(name: str, /, **fields: Any) -> None:
    LOG.error(name, extra={"fields": fields}, exc_info=True)
