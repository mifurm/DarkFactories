from nightshift.core.registry import FeatureSpec

FEATURE = FeatureSpec(
    id="DF-02",
    name="Telemetry ingestion & Unified Namespace",
    epic="A - Plant digital twin & telemetry",
    priority="P0",
    status="implemented",
    ui_route="/telemetry",
    api_prefix="/api/telemetry",
    summary="ISA-95 topic hierarchy (enterprise/site/area/line/cell/asset/metric), pydantic-validated messages, TelemetrySource adapters "
    "(simulator default, HTTP ingest, MQTT / Event Hubs / IoT Operations decoders), ring-buffer time-series store with downsampling, "
    "periodic aggregate persistence and live SSE subscription.",
    depth="SimSource and HTTP ingest run end-to-end; MQTT/Event Hubs/IoT Operations adapters implement the decoding contract (tested) but are not connected in this deployment.",
    tags=("uns", "isa-95"),
)
