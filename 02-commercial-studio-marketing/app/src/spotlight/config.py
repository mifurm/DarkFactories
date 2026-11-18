"""Runtime configuration (environment variables; no secrets — Azure auth is keyless via Entra)."""

from __future__ import annotations

import os
import socket
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from . import __version__


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", extra="ignore", case_sensitive=False)

    app_name: str = "SwarmAI Commercial Studio (Spotlight)"
    version: str = __version__
    build_id: str = Field(default_factory=lambda: os.getenv("CONTAINER_APP_REVISION", "dev"), alias="BUILD_ID")

    # azure | offline | auto (auto => azure when Cosmos + Blob + OpenAI endpoints are all configured)
    spotlight_mode: str = "auto"
    azure_region: str = "swedencentral"
    azure_client_id: str = ""
    cosmos_endpoint: str = ""
    cosmos_database: str = "studio"
    blob_account_url: str = ""
    blob_container: str = "assets"
    azure_openai_endpoint: str = ""
    ai_endpoint: str = ""

    model_chat: str = "gpt-5.4-mini"
    model_reasoning: str = "gpt-5.4"
    model_embed: str = "text-embedding-3-small"
    model_tts: str = "tts-hd"
    model_image: str = "gpt-image-1.5"
    model_image_draft: str = "gpt-image-1-mini"

    speech_provider: str = "auto"  # auto | openai | neural
    repo_backend: str = "auto"  # auto | cosmos | memory
    blob_backend: str = "auto"  # auto | azure | localdir | memory
    ai_backend: str = "auto"  # auto | azure | stub
    daily_ai_budget_usd: float = 5.0
    campaign_ai_budget_usd: float = 2.0

    # limits (per replica)
    rate_limit_enabled: bool = True
    rate_per_ip_mutate_per_min: int = 90
    rate_per_ip_spend_per_min: int = 24
    rate_global_spend_per_min: int = 90
    max_body_bytes: int = 12 * 1024 * 1024
    max_upload_bytes: int = 8 * 1024 * 1024
    max_concurrent_jobs: int = 2

    static_dir: str = ""
    data_dir: str = ""  # local file blob store when offline (optional)
    work_dir: str = ""  # scratch space for renders (defaults to the system temp dir)
    seed_on_start: bool = True
    log_level: str = "INFO"
    applicationinsights_connection_string: str = ""
    otel_service_name: str = "spotlight-studio"
    video_provider: str = "compositor"
    render_timeout_s: int = 420
    allow_internal_webhook_sink: bool = True

    @property
    def mode(self) -> str:
        m = self.spotlight_mode.lower()
        if m in {"azure", "offline"}:
            return m
        have = self.cosmos_endpoint and self.blob_account_url and self.azure_openai_endpoint
        return "azure" if have else "offline"

    @property
    def instance_id(self) -> str:
        return os.getenv("CONTAINER_APP_REPLICA_NAME") or socket.gethostname()

    @property
    def static_path(self) -> Path | None:
        candidates = [self.static_dir] if self.static_dir else []
        candidates += [
            str(Path(__file__).resolve().parents[2] / "static"),
            str(Path(__file__).resolve().parents[2] / "web" / "dist"),
            "/app/static",
        ]
        for c in candidates:
            if c and (Path(c) / "index.html").is_file():
                return Path(c)
        return None

    @property
    def models(self) -> dict[str, str]:
        return {
            "chat": self.model_chat,
            "reasoning": self.model_reasoning,
            "embed": self.model_embed,
            "tts": self.model_tts,
            "image": self.model_image,
            "image_draft": self.model_image_draft,
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
