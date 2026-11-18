"""Runtime configuration: one immutable Settings object built from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace


def _bool(value: str | None, default: bool) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _float(value: str | None, default: float) -> float:
    try:
        return float(value) if value not in (None, "") else default
    except ValueError:
        return default


def _int(value: str | None, default: int) -> int:
    try:
        return int(value) if value not in (None, "") else default
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    mode: str = (
        "offline"  # "azure" -> Azure OpenAI + Cosmos + Blob (managed identity); "offline" -> stub LLM + in-memory
    )
    build_id: str = "dev"
    region: str = "local"
    azure_client_id: str = ""
    subscription_id: str = ""
    resource_group: str = ""
    cosmos_endpoint: str = ""
    cosmos_database: str = "nightshift"
    storage_account_url: str = ""
    openai_endpoint: str = ""
    chat_deployment: str = "chat"
    reasoning_deployment: str = "reasoning"
    appinsights_connection_string: str = ""
    daily_ai_budget_usd: float = 5.0
    seed: int = 20261117
    sim_speed: float = 1.0  # simulated minutes per real second
    sim_autostart: bool = True
    approval_clock_factor: float = (
        6.0  # live demo: approval SLAs run this many times faster than real time (0 = simulated time)
    )
    plants: tuple[str, ...] = ("KAT-1", "GDN-2", "MTY-3")
    primary_plant: str = "KAT-1"
    teams_webhook_url: str = ""
    demo_role_switch: bool = True
    default_role: str = "plant_manager"
    entra_tenant_id: str = ""
    entra_audience: str = ""
    rate_limit_mutating_per_min: int = 120
    rate_limit_ai_per_min: int = 24
    rate_limit_global_mutating_per_min: int = 900
    rate_limit_global_ai_per_min: int = 120
    rate_limit_get_per_min: int = 2400
    rate_limit_compute_per_min: int = 900
    max_body_bytes: int = 2_000_000
    llm_narration: bool = True
    persist_enabled: bool = True
    extra: dict[str, str] = field(default_factory=dict)

    @property
    def is_azure(self) -> bool:
        return self.mode == "azure"

    def with_overrides(self, **kw) -> Settings:
        return replace(self, **kw)

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> Settings:
        e = env if env is not None else os.environ
        mode = "azure" if e.get("NIGHTSHIFT_MODE", "offline").lower() == "azure" else "offline"
        plants = tuple(p.strip() for p in e.get("PLANTS", "KAT-1,GDN-2,MTY-3").split(",") if p.strip())
        return cls(
            mode=mode,
            build_id=e.get("BUILD_ID") or e.get("CONTAINER_APP_REVISION") or "dev",
            region=e.get("AZURE_REGION", "local"),
            azure_client_id=e.get("AZURE_CLIENT_ID", ""),
            subscription_id=e.get("AZURE_SUBSCRIPTION_ID", ""),
            resource_group=e.get("AZURE_RESOURCE_GROUP", ""),
            cosmos_endpoint=e.get("COSMOS_ENDPOINT", ""),
            cosmos_database=e.get("COSMOS_DATABASE", "nightshift"),
            storage_account_url=e.get("STORAGE_ACCOUNT_URL", ""),
            openai_endpoint=e.get("AZURE_OPENAI_ENDPOINT", ""),
            chat_deployment=e.get("AZURE_OPENAI_CHAT_DEPLOYMENT", "chat"),
            reasoning_deployment=e.get("AZURE_OPENAI_REASONING_DEPLOYMENT", "reasoning"),
            appinsights_connection_string=e.get("APPLICATIONINSIGHTS_CONNECTION_STRING", ""),
            daily_ai_budget_usd=_float(e.get("AI_DAILY_BUDGET_USD"), 5.0),
            seed=_int(e.get("NIGHTSHIFT_SEED"), 20261117),
            sim_speed=_float(e.get("SIM_SPEED"), 1.0),
            sim_autostart=_bool(e.get("SIM_AUTOSTART"), True),
            approval_clock_factor=_float(e.get("APPROVAL_CLOCK_FACTOR"), 6.0),
            plants=plants or ("KAT-1",),
            primary_plant=(plants[0] if plants else "KAT-1"),
            teams_webhook_url=e.get("TEAMS_WEBHOOK_URL", ""),
            demo_role_switch=_bool(e.get("DEMO_ROLE_SWITCH"), True),
            default_role=e.get("DEFAULT_ROLE", "plant_manager"),
            entra_tenant_id=e.get("ENTRA_TENANT_ID", ""),
            entra_audience=e.get("ENTRA_AUDIENCE", ""),
            rate_limit_mutating_per_min=_int(e.get("RATE_LIMIT_MUTATING_PER_MIN"), 120),
            rate_limit_ai_per_min=_int(e.get("RATE_LIMIT_AI_PER_MIN"), 24),
            rate_limit_global_mutating_per_min=_int(e.get("RATE_LIMIT_GLOBAL_MUTATING_PER_MIN"), 900),
            rate_limit_global_ai_per_min=_int(e.get("RATE_LIMIT_GLOBAL_AI_PER_MIN"), 120),
            rate_limit_get_per_min=_int(e.get("RATE_LIMIT_GET_PER_MIN"), 2400),
            rate_limit_compute_per_min=_int(e.get("RATE_LIMIT_COMPUTE_PER_MIN"), 900),
            max_body_bytes=_int(e.get("MAX_BODY_BYTES"), 2_000_000),
            llm_narration=_bool(e.get("LLM_NARRATION"), True),
            persist_enabled=_bool(e.get("PERSIST_ENABLED"), True),
        )
