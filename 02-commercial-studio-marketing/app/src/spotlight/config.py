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

    # Cinematic motion (generative image-to-video, see spotlight/motion): an open model (Wan 2.2 TI2V-5B, Apache-2.0) self-hosted on a serverless GPU
    # worker that Studio reaches through a storage queue + blobs (keyless). auto => azure when SPOTLIGHT_MODE=azure and MOTION_QUEUE_URL is set,
    # the procedural stub animator offline, off otherwise; azure | local | stub | off force a mode.
    motion_mode: str = "auto"
    motion_queue_url: str = ""
    motion_queue_name: str = "motion-jobs"
    motion_blob_account_url: str = ""
    motion_in_container: str = "motion-in"
    motion_out_container: str = "motion-out"
    motion_local_dir: str = ""
    motion_model: str = "wan2.2-ti2v-5b"
    motion_model_revision: str = ""  # empty = the revision pinned in spotlight.motion.wire
    motion_steps: int = 20
    motion_guidance: float = 4.0
    motion_high: bool = False  # 1280x704 clips for 16:9 (more detail, ~1.6x GPU time)
    motion_price_per_gpu_second: float = 0.00108
    motion_timeout_s: int = 1500  # the whole motion phase of one render (cold start included)
    motion_cold_start_s: int = 240

    @property
    def mode(self) -> str:
        m = self.spotlight_mode.lower()
        if m in {"azure", "offline"}:
            return m
        have = self.cosmos_endpoint and self.blob_account_url and self.azure_openai_endpoint
        return "azure" if have else "offline"

    @property
    def motion_effective_mode(self) -> str:
        """azure | local | stub | off — the cinematic-motion backend actually used."""
        m = self.motion_mode.strip().lower()
        if m == "azure":
            return "azure" if self.motion_queue_url and self.motion_blob_account_url_or_default else "off"
        if m == "local":
            return "local" if self.motion_local_dir else "off"
        if m in {"stub", "off"}:
            return m
        if self.mode == "azure":
            return "azure" if self.motion_queue_url and self.motion_blob_account_url_or_default else "off"
        return "stub"

    @property
    def motion_blob_account_url_or_default(self) -> str:
        """The blob account of the motion containers (defaults to the app's own storage account)."""
        return self.motion_blob_account_url or self.blob_account_url

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
