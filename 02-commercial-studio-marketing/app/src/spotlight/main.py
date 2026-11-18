"""ASGI entry point:  uvicorn spotlight.main:app"""

from __future__ import annotations

from . import telemetry
from .app_factory import create_app
from .config import get_settings

settings = get_settings()
telemetry_enabled = telemetry.configure(settings)
app = create_app(settings)
app.state.telemetry_enabled = telemetry_enabled
