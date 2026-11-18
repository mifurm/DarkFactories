"""Live regression: the audit chain of an English campaign broke at the "Keyframes generated" entry after a cached image run.

The entry carried ``cost_usd: 0.0`` (cache hit). Cosmos DB hands ``0.0`` back as ``0``, so the hash recomputed on read no longer matched the one
written. The in-memory repository keeps the float, which is why unit tests never saw it."""

from __future__ import annotations

from typing import Any

from spotlight.core.audit import AuditLog
from spotlight.core.repo import MemoryRepository


def _like_cosmos(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, dict):
        return {k: _like_cosmos(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_like_cosmos(v) for v in value]
    return value


class CosmosNumbersRepo(MemoryRepository):
    """Returns every document the way Cosmos DB does: integral floats come back as ints."""

    async def query(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return [_like_cosmos(r) for r in await super().query(*args, **kwargs)]


DATA = {"frames": 4, "cost_usd": 0.0, "duration_s": 15.0, "lufs": -16.0, "ratio": 2.5, "nested": {"xs": [1.0, 2.5], "ok": True}}


async def test_audit_chain_verifies_when_the_store_turns_integral_floats_into_ints():
    log = AuditLog(CosmosNumbersRepo())
    for _ in range(4):
        await log.append("c", {"name": "t"}, "storyboard.frames_generated", {"artifact_id": "a"}, dict(DATA))
    verdict = await log.verify("c")
    assert verdict["ok"] and verdict["entries"] == 4, verdict


async def test_audit_chain_still_detects_edits_to_numbers_and_flags():
    repo = CosmosNumbersRepo()
    log = AuditLog(repo)
    for _ in range(3):
        await log.append("c", {"name": "t"}, "x", None, dict(DATA))
    row = await repo.get("audit", "c:00000002", pk="c")
    for field, new in [("cost_usd", 1), ("frames", 5), ("ratio", 2.6), ("lufs", -15)]:
        edited = {**row, "data": {**row["data"], field: new}}
        await repo.upsert("audit", edited)
        bad = await log.verify("c")
        assert not bad["ok"] and bad["broken_at"] == 2, (field, bad)
    flipped = {**row, "data": {**row["data"], "nested": {"xs": [1.0, 2.5], "ok": False}}}
    await repo.upsert("audit", flipped)
    assert not (await log.verify("c"))["ok"], "a boolean must not be confused with 1 / 0"
    await repo.upsert("audit", row)
    assert (await log.verify("c"))["ok"]
