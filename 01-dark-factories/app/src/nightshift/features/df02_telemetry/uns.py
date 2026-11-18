"""Telemetry ingestion & Unified Namespace (DF-02): ISA-95 topics, validated messages, source adapters, external ring buffers."""

from __future__ import annotations

import json
import math
import re
import time
from abc import ABC, abstractmethod
from collections import deque
from collections.abc import AsyncIterator
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from nightshift.sim.config import AssetSpec, PlantConfig

TOPIC_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*(/[a-z0-9][a-z0-9_.-]*){6}$")
ENTERPRISE = "contoso"
UNITS = {
    "vibration_rms": "mm/s",
    "bearing_temp_c": "C",
    "melt_temp_c": "C",
    "temperature_c": "C",
    "supply_temp_c": "C",
    "spindle_load_pct": "%",
    "current_a": "A",
    "power_kw": "kW",
    "dim_mm": "mm",
    "part_weight_g": "g",
    "torque_nm": "Nm",
    "hydraulic_pressure_bar": "bar",
    "pressure_bar": "bar",
    "battery_pct": "%",
    "tariff_eur_kwh": "EUR/kWh",
    "carbon_g_kwh": "g/kWh",
}


class TelemetryMessage(BaseModel):
    """One UNS message: ISA-95 path ``enterprise/site/area/line/cell/asset/metric`` plus value, timestamp and quality."""

    topic: str
    ts: float = Field(
        default_factory=time.time, description="unix seconds (or simulated epoch); defaults to receive time"
    )
    value: float | str | bool
    unit: str = ""
    quality: Literal["good", "uncertain", "bad"] = "good"
    source: str = "sim"

    @field_validator("topic")
    @classmethod
    def _topic(cls, v: str) -> str:
        v = v.strip().lower()
        if not TOPIC_RE.match(v):
            raise ValueError("topic must be enterprise/site/area/line/cell/asset/metric (lower-case, 7 levels)")
        return v

    @field_validator("value")
    @classmethod
    def _finite(cls, v: Any) -> Any:
        if isinstance(v, float) and not math.isfinite(v):
            raise ValueError("value must be finite")
        return v

    @property
    def parts(self) -> dict[str, str]:
        e, s, a, l, c, asset, m = self.topic.split("/")  # noqa: E741
        return {"enterprise": e, "site": s, "area": a, "line": l, "cell": c, "asset": asset, "metric": m}


def topic_for(cfg: PlantConfig, spec: AssetSpec, metric: str) -> str:
    return f"{ENTERPRISE}/{cfg.site}/{spec.area}/{spec.line}/{spec.cell}/{spec.id.lower()}/{metric}"


def plant_topic(cfg: PlantConfig, metric: str) -> str:
    return f"{ENTERPRISE}/{cfg.site}/site/utility/meter/plant/{metric}"


def sim_messages(plant: Any) -> list[TelemetryMessage]:
    """Latest value of every simulated series as validated UNS messages."""
    cfg = plant.cfg
    now = time.time()
    out: list[TelemetryMessage] = []
    for spec in cfg.assets:
        a = plant.assets[spec.id]
        out.append(TelemetryMessage(topic=topic_for(cfg, spec, "state"), ts=now, value=a.state, source="sim"))
        for m in spec.sensors:
            v = plant.store.latest(spec.id, m)
            if v == v:
                out.append(
                    TelemetryMessage(
                        topic=topic_for(cfg, spec, m),
                        ts=now,
                        value=round(float(v), 4),
                        unit=UNITS.get(m, ""),
                        source="sim",
                    )
                )
    for m in ("power_kw", "tariff_eur_kwh", "carbon_g_kwh"):
        v = plant.store.latest("plant", m)
        if v == v:
            out.append(
                TelemetryMessage(
                    topic=plant_topic(cfg, m), ts=now, value=round(float(v), 4), unit=UNITS.get(m, ""), source="sim"
                )
            )
    return out


class TelemetrySource(ABC):
    """Adapter interface: anything that can yield batches of validated messages (SimSource, MQTT, Event Hubs, IoT Operations...)."""

    name = "abstract"

    @abstractmethod
    def stream(self) -> AsyncIterator[list[TelemetryMessage]]: ...


class SimSource(TelemetrySource):
    name = "sim"

    def __init__(self, plant: Any, interval_s: float = 1.0) -> None:
        self.plant, self.interval_s = plant, interval_s

    async def stream(self):  # type: ignore[override]
        import asyncio

        while True:
            yield sim_messages(self.plant)
            await asyncio.sleep(self.interval_s)


class AdapterUnavailable(RuntimeError):
    pass


class MqttDecoder:
    """Decode MQTT payloads (JSON ``{"v":..,"t":..,"q":..}`` or a bare number) published on a UNS-shaped topic. The broker connection
    itself (Azure IoT Operations MQTT broker) is not part of this deployment; the decoding contract is tested."""

    name = "mqtt"

    @staticmethod
    def decode(topic: str, payload: bytes, source: str = "mqtt") -> TelemetryMessage:
        text = payload.decode("utf-8", "replace").strip()
        try:
            obj = json.loads(text)
        except json.JSONDecodeError:
            obj = text
        if isinstance(obj, dict):
            v, t, q = obj.get("v", obj.get("value")), obj.get("t", obj.get("ts", time.time())), obj.get("q", "good")
        else:
            v, t, q = obj, time.time(), "good"
        return TelemetryMessage(
            topic=topic,
            ts=float(t),
            value=v,
            quality=q if q in ("good", "uncertain", "bad") else "uncertain",
            source=source,
        )

    @staticmethod
    def connect(*_: Any, **__: Any) -> None:
        raise AdapterUnavailable("MQTT broker not configured in this deployment (needs aiomqtt + AIO broker endpoint)")


class EventHubDecoder:
    """Decode an Event Hubs / IoT Operations data-flow event: ``{"asset": "...", "datapoints": [{"metric","value","ts"}]}``."""

    name = "eventhubs"

    @staticmethod
    def decode(body: bytes, base_topic_prefix: str, source: str = "eventhubs") -> list[TelemetryMessage]:
        obj = json.loads(body)
        asset = str(obj["asset"]).lower()
        msgs = []
        for dp in obj.get("datapoints", []):
            msgs.append(
                TelemetryMessage(
                    topic=f"{base_topic_prefix}/{asset}/{dp['metric']}".lower(),
                    ts=float(dp.get("ts", time.time())),
                    value=dp["value"],
                    quality=dp.get("quality", "good"),
                    source=source,
                )
            )
        return msgs


class ExternalStore:
    """Ring buffers for messages pushed over HTTP/MQTT/Event Hubs; keyed by topic, bounded in memory."""

    def __init__(self, per_topic: int = 2000, max_topics: int = 5000) -> None:
        self.per_topic, self.max_topics = per_topic, max_topics
        self.buf: dict[str, deque[tuple[float, Any, str]]] = {}
        self.accepted = self.rejected = 0

    def ingest(self, batch: list[dict[str, Any]], source: str = "http", max_batch: int = 500) -> dict[str, Any]:
        if len(batch) > max_batch:
            raise ValueError(f"batch too large (max {max_batch})")
        errors: list[str] = []
        ok = 0
        for i, raw in enumerate(batch):
            try:
                m = TelemetryMessage(**{**raw, "source": source})
                if m.topic not in self.buf and len(self.buf) >= self.max_topics:
                    raise ValueError("topic limit reached")
                q = self.buf.setdefault(m.topic, deque(maxlen=self.per_topic))
                q.append((m.ts, m.value, m.quality))
                ok += 1
            except Exception as exc:
                self.rejected += 1
                if len(errors) < 5:
                    errors.append(f"#{i}: {str(exc)[:120]}")
        self.accepted += ok
        return {"accepted": ok, "rejected": len(batch) - ok, "errors": errors}

    def series(self, topic: str, n: int = 200) -> list[dict[str, Any]]:
        return [{"ts": t, "value": v, "quality": q} for t, v, q in list(self.buf.get(topic, []))[-n:]]

    def latest(self) -> dict[str, Any]:
        return {t: {"ts": q[-1][0], "value": q[-1][1], "quality": q[-1][2]} for t, q in self.buf.items() if q}


def build_tree(cfg: PlantConfig, latest: dict[str, Any]) -> dict[str, Any]:
    """Hierarchical view enterprise > site > area > line > cell > asset > metric with the latest value per leaf."""
    root: dict[str, Any] = {}
    for topic, val in latest.items():
        node = root
        for part in topic.split("/")[:-1]:
            node = node.setdefault(part, {})
        node.setdefault("_metrics", {})[topic.rsplit("/", 1)[1]] = val
    return root
