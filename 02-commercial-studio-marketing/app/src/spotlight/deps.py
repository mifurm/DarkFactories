"""FastAPI dependencies shared by feature routers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import Request

from .core.ai.base import set_ctx
from .security import client_ip

if TYPE_CHECKING:
    from .services import Services


def svc(request: Request) -> Services:
    return request.app.state.services


def _ip(request: Request) -> str:
    return client_ip(request.headers, request.client.host if request.client else None)


async def mutate_limit(request: Request) -> None:
    s = svc(request)
    s.limiter.check("mutate", _ip(request), s.settings.rate_per_ip_mutate_per_min)


async def spend_limit(request: Request) -> None:
    """Endpoints that can spend AI money: per-IP and global rate limits (the daily budget guard sits behind).
    Also attributes any AI call made while serving this request to the campaign in the URL (per-campaign caps)."""
    s = svc(request)
    s.limiter.check("spend", _ip(request), s.settings.rate_per_ip_spend_per_min)
    s.limiter.check("spend-global", "all", s.settings.rate_global_spend_per_min)
    cid = request.path_params.get("campaign_id")
    if cid:
        set_ctx(campaign_id=cid, feature=request.url.path.split("/")[4] if request.url.path.count("/") >= 4 else None)
