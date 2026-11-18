"""Entra (keyless) credentials: user-assigned managed identity in Azure Container Apps, `az login` locally."""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Awaitable, Callable
from typing import Any

COGNITIVE_SCOPE = "https://cognitiveservices.azure.com/.default"
COSMOS_SCOPE = "https://cosmos.azure.com/.default"
STORAGE_SCOPE = "https://storage.azure.com/.default"
MONITOR_SCOPE = "https://monitor.azure.com//.default"

_credential: Any = None
_cache: dict[str, tuple[str, float]] = {}
_lock = asyncio.Lock()


def get_credential(client_id: str = "") -> Any:
    global _credential
    if _credential is None:
        from azure.identity.aio import AzureCliCredential, ChainedTokenCredential, ManagedIdentityCredential

        if os.environ.get("IDENTITY_ENDPOINT") or os.environ.get("MSI_ENDPOINT"):
            _credential = ManagedIdentityCredential(client_id=client_id or None)
        else:
            chain = [AzureCliCredential()]
            _credential = ChainedTokenCredential(*chain)
    return _credential


async def get_token(client_id: str = "", scope: str = COGNITIVE_SCOPE) -> str:
    """Cached bearer token (refreshed 5 minutes before expiry)."""
    cached = _cache.get(scope)
    if cached and cached[1] - time.time() > 300:
        return cached[0]
    async with _lock:
        cached = _cache.get(scope)
        if cached and cached[1] - time.time() > 300:
            return cached[0]
        tok = await get_credential(client_id).get_token(scope)
        _cache[scope] = (tok.token, float(tok.expires_on))
        return tok.token


def token_provider(client_id: str = "", scope: str = COGNITIVE_SCOPE) -> Callable[[], Awaitable[str]]:
    async def _provider() -> str:
        return await get_token(client_id, scope)

    return _provider


async def close_credential() -> None:
    global _credential
    if _credential is not None:
        try:
            await _credential.close()
        finally:
            _credential = None
            _cache.clear()
