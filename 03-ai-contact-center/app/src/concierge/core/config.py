"""Runtime configuration (environment driven; no secrets - identity is always a managed identity / az login)."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field

APP_NAME = "SwarmAI Contact Center (Concierge)"
APP_VERSION = "1.0.0"
STARTED_AT = time.time()

DEFAULT_DEPLOYMENTS = {
    "chat": "gpt-5.4-mini",
    "reasoning": "gpt-5.4",
    "nano": "gpt-5.4-nano",
    "realtime": "gpt-realtime-2.1-mini",
    "realtime_fallback": "gpt-realtime-mini",
    "embed": "text-embedding-3-small",
    "transcribe": "gpt-4o-mini-transcribe",
}


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


@dataclass(frozen=True)
class Settings:
    mode: str = "offline"  # azure | offline
    cosmos_endpoint: str = ""
    cosmos_database: str = "concierge"
    storage_account_url: str = ""
    openai_endpoint: str = ""
    ai_services_endpoint: str = ""
    client_id: str = ""
    deployments: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_DEPLOYMENTS))
    daily_budget_usd: float = 5.0
    build_id: str = "dev"
    region: str = "local"
    resource_group: str = ""
    app_insights_connection: str = ""
    auth_mode: str = "demo"  # demo | entra
    entra_tenant_id: str = ""
    entra_audience: str = ""
    seed_on_start: bool = True
    rate_limit_ip_per_min: int = 90
    rate_limit_ai_ip_per_min: int = 40
    rate_limit_global_per_min: int = 1500
    max_body_bytes: int = 262_144
    max_upload_bytes: int = 2_000_000
    static_dir: str = ""
    synthetic_seed: int = 20260317

    @property
    def is_azure(self) -> bool:
        return self.mode == "azure"

    def deployment(self, role: str) -> str:
        return self.deployments.get(role, "")


def load_settings(**overrides) -> Settings:
    cosmos = _env("COSMOS_ENDPOINT")
    openai_ep = _env("AZURE_OPENAI_ENDPOINT")
    mode = _env("CONCIERGE_MODE", "auto").lower()
    if mode == "auto":
        mode = "azure" if (cosmos and openai_ep) else "offline"
    deployments = dict(DEFAULT_DEPLOYMENTS)
    for role, env_name in {
        "chat": "AOAI_DEPLOYMENT_CHAT",
        "reasoning": "AOAI_DEPLOYMENT_REASONING",
        "nano": "AOAI_DEPLOYMENT_NANO",
        "realtime": "AOAI_DEPLOYMENT_REALTIME",
        "realtime_fallback": "AOAI_DEPLOYMENT_REALTIME_FALLBACK",
        "embed": "AOAI_DEPLOYMENT_EMBED",
        "transcribe": "AOAI_DEPLOYMENT_TRANSCRIBE",
    }.items():
        if env_name in os.environ:
            deployments[role] = _env(env_name)
    static_dir = _env("STATIC_DIR")
    if not static_dir:
        for candidate in ("/app/static", os.path.join(os.path.dirname(__file__), "..", "..", "..", "web", "dist")):
            if os.path.isdir(candidate):
                static_dir = os.path.abspath(candidate)
                break
    base = Settings(
        mode=mode,
        cosmos_endpoint=cosmos,
        cosmos_database=_env("COSMOS_DATABASE", "concierge"),
        storage_account_url=_env("STORAGE_ACCOUNT_URL"),
        openai_endpoint=openai_ep.rstrip("/"),
        ai_services_endpoint=_env("AI_SERVICES_ENDPOINT").rstrip("/"),
        client_id=_env("AZURE_CLIENT_ID"),
        deployments=deployments,
        daily_budget_usd=float(_env("AI_DAILY_BUDGET_USD", "5") or 5),
        build_id=_read_build_id(),
        region=_env("AZURE_LOCATION", "local"),
        resource_group=_env("AZURE_RESOURCE_GROUP"),
        app_insights_connection=_env("APPLICATIONINSIGHTS_CONNECTION_STRING"),
        auth_mode="entra" if _env("AUTH_MODE", "demo").lower() == "entra" else "demo",
        entra_tenant_id=_env("ENTRA_TENANT_ID"),
        entra_audience=_env("ENTRA_AUDIENCE"),
        seed_on_start=_env("SEED_ON_START", "1") not in ("0", "false", "no"),
        static_dir=static_dir,
    )
    if overrides:
        from dataclasses import replace

        return replace(base, **overrides)
    return base


def _read_build_id() -> str:
    explicit = _env("BUILD_ID")
    if explicit:
        return explicit
    for path in ("/app/BUILD_ID", os.path.join(os.path.dirname(__file__), "..", "BUILD_ID")):
        try:
            with open(path) as fh:
                return fh.read().strip() or "dev"
        except OSError:
            continue
    return "dev"
