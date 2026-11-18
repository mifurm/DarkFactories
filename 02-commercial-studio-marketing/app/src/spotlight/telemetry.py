"""OpenTelemetry -> Azure Monitor / Application Insights (Entra-authenticated ingestion; no keys)."""

from __future__ import annotations

import logging

from .config import Settings

log = logging.getLogger("spotlight.telemetry")


def configure(settings: Settings) -> bool:
    """Must run BEFORE the FastAPI app is created so the distro can instrument it. Returns True when enabled."""
    if settings.mode != "azure" or not settings.applicationinsights_connection_string:
        return False
    try:
        from azure.identity import DefaultAzureCredential
        from azure.monitor.opentelemetry import configure_azure_monitor

        configure_azure_monitor(
            connection_string=settings.applicationinsights_connection_string,
            credential=DefaultAzureCredential(managed_identity_client_id=settings.azure_client_id or None),
            logger_name="spotlight",
        )
        log.info("Azure Monitor OpenTelemetry enabled")
        return True
    except Exception:
        log.exception("telemetry configuration failed; continuing without it")
        return False
