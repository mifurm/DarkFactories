"""Observability primitives: JSON logging with PII redaction, in-process metrics registry, OpenTelemetry -> App Insights."""

from __future__ import annotations

import json
import logging
import re
import statistics
import time
from collections import defaultdict, deque
from typing import Any

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_JWT = re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")
_BEARER = re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]{12,}")
_SECRETISH = re.compile(r"(?i)(sig|key|secret|password|token)=([^&\s]{6,})")


def redact(text: str) -> str:
    text = _JWT.sub("[jwt]", text)
    text = _BEARER.sub("Bearer [redacted]", text)
    text = _SECRETISH.sub(lambda m: f"{m.group(1)}=[redacted]", text)
    return _EMAIL.sub("[email]", text)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)) + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "msg": redact(record.getMessage()),
        }
        for k in ("request_id", "feature", "path", "status", "ms", "agent", "decision"):
            if hasattr(record, k):
                payload[k] = getattr(record, k)
        if record.exc_info:
            payload["exc"] = redact(self.formatException(record.exc_info))[:2000]
        return json.dumps(payload, default=str)


def setup_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    root.setLevel(level)
    for h in list(root.handlers):
        root.removeHandler(h)
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    logging.getLogger("uvicorn.access").disabled = True
    for noisy in (
        "azure",
        "azure.core.pipeline.policies.http_logging_policy",
        "azure.identity",
        "httpx",
        "httpcore",
        "urllib3",
    ):  # SDKs log every request at INFO
        logging.getLogger(noisy).setLevel(logging.WARNING)


class Metrics:
    """Per-feature request counters/latency, per-agent decision counters and latency - exposed by DF-24."""

    def __init__(self) -> None:
        self.started = time.time()
        self.req_count: dict[str, int] = defaultdict(int)
        self.req_err: dict[str, int] = defaultdict(int)
        self.req_lat: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=500))
        self.agent_events: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self.agent_lat: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=500))
        self._otel: dict[str, Any] = {}

    def _inst(self) -> dict[str, Any]:
        if not self._otel:
            from opentelemetry import metrics as otel_metrics

            meter = otel_metrics.get_meter("nightshift")
            self._otel = {
                "req": meter.create_counter("nightshift.requests", description="HTTP requests by feature"),
                "lat": meter.create_histogram("nightshift.request.duration_ms", unit="ms"),
                "agent": meter.create_counter("nightshift.agent.events", description="agent proposals/decisions"),
                "alat": meter.create_histogram("nightshift.agent.latency_ms", unit="ms"),
            }
        return self._otel

    def observe_request(self, feature: str, status: int, ms: float) -> None:
        self.req_count[feature] += 1
        if status >= 500:
            self.req_err[feature] += 1
        self.req_lat[feature].append(ms)
        o = self._inst()
        o["req"].add(1, {"feature": feature, "status_class": f"{status // 100}xx"})
        o["lat"].record(ms, {"feature": feature})

    def observe_agent(self, agent: str, event: str, ms: float | None = None) -> None:
        self.agent_events[agent][event] += 1
        o = self._inst()
        o["agent"].add(1, {"agent": agent, "event": event})
        if ms is not None:
            self.agent_lat[agent].append(ms)
            o["alat"].record(ms, {"agent": agent})

    @staticmethod
    def _pct(values: deque[float] | list[float], q: float) -> float:
        if not values:
            return 0.0
        s = sorted(values)
        return round(s[min(len(s) - 1, int(q * len(s)))], 2)

    def snapshot(self) -> dict[str, Any]:
        feats = {
            f: {
                "count": self.req_count[f],
                "errors_5xx": self.req_err[f],
                "p50_ms": self._pct(self.req_lat[f], 0.5),
                "p95_ms": self._pct(self.req_lat[f], 0.95),
                "mean_ms": round(statistics.fmean(self.req_lat[f]), 2) if self.req_lat[f] else 0.0,
            }
            for f in sorted(self.req_count)
        }
        agents = {
            a: {
                "events": dict(ev),
                "p50_ms": self._pct(self.agent_lat[a], 0.5),
                "p95_ms": self._pct(self.agent_lat[a], 0.95),
            }
            for a, ev in sorted(self.agent_events.items())
        }
        return {"uptime_s": round(time.time() - self.started, 1), "features": feats, "agents": agents}


def setup_azure_monitor(connection_string: str, client_id: str = "") -> bool:  # pragma: no cover - needs Azure
    """Wire OpenTelemetry to Application Insights using Entra auth (no instrumentation key auth)."""
    if not connection_string:
        return False
    try:
        from azure.identity import DefaultAzureCredential
        from azure.monitor.opentelemetry import configure_azure_monitor

        cred = DefaultAzureCredential(managed_identity_client_id=client_id) if client_id else DefaultAzureCredential()
        configure_azure_monitor(connection_string=connection_string, credential=cred, logger_name="nightshift")
        return True
    except Exception as exc:
        logging.getLogger("nightshift").warning("Azure Monitor OpenTelemetry not enabled: %s", exc)
        return False
