"""Live regression: the library's semantic search came back empty after campaigns had been deleted (the smoke test cleans up after itself).

Deleting an asset or a campaign left its vectors in the ``library`` namespace, and the search took the top-k vectors *before* dropping those whose asset no
longer exists, so a handful of stale vectors with similar text pushed every live asset out of the result list."""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from spotlight.app_factory import create_app
from spotlight.config import Settings
from test_pipeline_api import H

TEXT = "sunrise kitchen coffee pour"


def _png(color: tuple[int, int, int]) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), color).save(buf, "PNG")
    return buf.getvalue()


@pytest.fixture(scope="module")
def api():
    app = create_app(Settings(spotlight_mode="offline", rate_limit_enabled=False, seed_on_start=True))
    with TestClient(app) as c:
        yield c


def _upload(api: TestClient, name: str, color: tuple[int, int, int], campaign_id: str | None = None) -> str:
    data = {"tags": "kitchen", "description": TEXT, **({"campaign_id": campaign_id} if campaign_id else {})}
    r = api.post("/api/library/assets", files={"file": (name, _png(color), "image/png")}, data=data, headers=H("creative"))
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _library_vectors(api: TestClient) -> set[str]:
    import asyncio

    rows = asyncio.run(api.app.state.services.repo.query("brand_chunks", pk="library"))
    return {r["meta"]["asset_id"] for r in rows if r.get("meta", {}).get("asset_id")}


def test_deleted_assets_do_not_mask_live_ones_and_leave_no_vectors_behind(api: TestClient):
    stale = [_upload(api, f"old-{i}.png", (10 * i, 20, 30)) for i in range(4)]
    live = _upload(api, "live.png", (200, 100, 50))
    for aid in stale:
        assert api.delete(f"/api/library/assets/{aid}", headers=H("admin")).status_code == 200
    found = api.get("/api/library/search", params={"q": TEXT, "k": 1}).json()["results"]
    assert [x["id"] for x in found] == [live]
    vectors = _library_vectors(api)
    assert live in vectors and not vectors & set(stale)


def test_deleting_a_campaign_removes_the_vectors_of_its_assets(api: TestClient):
    cid = api.post("/api/campaigns", json={"name": "Vector cleanup", "brand_id": "northwind", "markets": ["US"], "language": "en"}, headers=H("creative")).json()["id"]
    owned = _upload(api, "owned.png", (1, 2, 3), campaign_id=cid)
    assert owned in _library_vectors(api)
    assert api.delete(f"/api/campaigns/{cid}", headers=H("admin")).status_code == 200
    assert owned not in _library_vectors(api)


def test_search_heals_vectors_that_were_already_stale(api: TestClient):
    import asyncio

    services = api.app.state.services
    ghost = "ast_ghost000000"
    asyncio.run(services.vectors.add("library", f"asset-{ghost}", [{"id": f"lib-{ghost}", "text": TEXT, "title": "ghost", "source": ghost, "meta": {"asset_id": ghost, "kind": "image"}}], kind="asset"))
    live = _upload(api, "live2.png", (9, 9, 9))
    assert ghost in _library_vectors(api)
    found = api.get("/api/library/search", params={"q": TEXT, "k": 30}).json()["results"]
    assert live in [x["id"] for x in found]
    assert ghost not in _library_vectors(api), "the search drops the vectors of assets that no longer exist"
