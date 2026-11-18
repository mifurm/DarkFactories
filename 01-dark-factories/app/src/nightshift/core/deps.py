"""FastAPI dependencies shared by feature routers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import HTTPException, Request

if TYPE_CHECKING:  # pragma: no cover
    from nightshift.core.runtime import Runtime
    from nightshift.plant.runtime import PlantRuntime


def get_rt(request: Request) -> Runtime:
    return request.app.state.rt


def get_plant(request: Request, plant: str | None = None) -> PlantRuntime:
    rt = request.app.state.rt
    if rt.fleet is None:
        raise HTTPException(503, "plants are not started")
    try:
        return rt.fleet.get(plant)
    except KeyError:
        raise HTTPException(404, f"unknown plant {plant!r}") from None
