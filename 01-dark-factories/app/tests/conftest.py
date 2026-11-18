"""Shared fixtures. Tests never need the network: the app runs in offline mode with the deterministic LLM stub and in-memory repository."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from nightshift.config import Settings
from nightshift.main import create_app
from nightshift.plant.core import PlantCore


def offline_settings(**kw) -> Settings:
    return Settings(**{"mode": "offline", "sim_autostart": False, "approval_clock_factor": 0.0, **kw})


@pytest.fixture(scope="module")
def client():
    """A running app with three commissioned plants whose clocks only move when a test steps them."""
    app = create_app(offline_settings())
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def core() -> PlantCore:
    """Headless plant + swarm, commissioned for 3 simulated hours."""
    c = PlantCore("KAT-1", seed=5, swarm=True, sim_first="surrogate")
    c.run(180)
    return c


def step(client: TestClient, minutes: int, plant: str = "KAT-1") -> dict:
    r = client.post(f"/api/sim/control?plant={plant}", json={"command": "step", "value": minutes})
    assert r.status_code == 200, r.text
    return r.json()
