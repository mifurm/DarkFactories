"""Lightweight in-process trace buffer (CC-22): spans for chat turns, tool calls and voice turns so a voice turn can be followed from the relay to the
model in the UI. When Azure Monitor OpenTelemetry is configured the same spans are also exported (Application Insights), so both views agree."""

from __future__ import annotations

import time
import uuid
from collections import deque
from typing import Any


class TraceBuffer:
    def __init__(self, maxlen: int = 1500) -> None:
        self.spans: deque[dict[str, Any]] = deque(maxlen=maxlen)
        self.export_otel = False

    def record(self, trace_id: str, name: str, start_ts: float, duration_ms: float, *, parent: str | None = None, **attrs: Any) -> str:
        span_id = uuid.uuid4().hex[:8]
        self.spans.append({"trace_id": trace_id, "span_id": span_id, "parent": parent, "name": name, "start": start_ts, "duration_ms": round(duration_ms, 1), "attrs": {k: v for k, v in attrs.items() if v is not None}})
        if self.export_otel:  # pragma: no cover - needs Azure Monitor
            try:
                from .telemetry import get_tracer

                span = get_tracer().start_span(name, start_time=int(start_ts * 1e9), attributes={"trace.key": trace_id, **{k: str(v)[:120] for k, v in attrs.items() if v is not None}})
                span.end(end_time=int((start_ts + duration_ms / 1000) * 1e9))
            except Exception:
                pass
        return span_id

    def trace(self, trace_id: str) -> list[dict[str, Any]]:
        return sorted((s for s in self.spans if s["trace_id"] == trace_id), key=lambda s: s["start"])

    def recent(self, kind: str = "", limit: int = 20) -> list[dict[str, Any]]:
        """Most recent traces whose root span name starts with `kind` (e.g. 'voice', 'chat')."""
        roots = [s for s in reversed(self.spans) if s["parent"] is None and s["name"].startswith(kind)]
        out = []
        for r in roots[: max(1, min(limit, 50))]:
            spans = self.trace(r["trace_id"])
            out.append({"trace_id": r["trace_id"], "name": r["name"], "start": r["start"], "duration_ms": r["duration_ms"], "attrs": r["attrs"], "spans": spans})
        return out


def now_ts() -> float:
    return time.time()
