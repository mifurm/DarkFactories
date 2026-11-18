"""Append-only, hash-chained decision ledger (DF-14): observation -> proposal -> decision -> action -> outcome."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

GENESIS = "0" * 64
KINDS = (
    "observation",
    "proposal",
    "arbitration",
    "veto",
    "whatif",
    "decision",
    "action",
    "outcome",
    "narration",
    "system",
    "override",
)


def canonical(body: dict[str, Any]) -> str:
    return json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)


def entry_hash(body: dict[str, Any]) -> str:
    return hashlib.sha256(canonical(body).encode("utf-8")).hexdigest()


class Ledger:
    def __init__(self, plant_id: str, writer: Any = None, max_memory: int = 20000) -> None:
        self.plant_id = plant_id
        self.writer = writer
        self.max_memory = max_memory
        self._entries: list[dict[str, Any]] = []
        self._first_seq = 1
        self.anchor_hash = GENESIS  # hash of the entry before the first in-memory one (continues across restarts)
        self._head = GENESIS
        self._next_seq = 1
        self.listeners: list[Any] = []

    # ------------------------------------------------------------------ restart continuity
    async def load_head(self, repo: Any) -> None:
        rows = await repo.query("ledger", pk=self.plant_id, order_by="seq", desc=True, limit=1)
        if rows:
            last = rows[0]
            self._head = self.anchor_hash = last["hash"]
            self._next_seq = self._first_seq = int(last["seq"]) + 1

    # ------------------------------------------------------------------ append / read
    def append(
        self,
        kind: str,
        summary: str,
        *,
        agent: str = "system",
        assets: Iterable[str] = (),
        decision_class: str = "",
        outcome: str = "",
        rationale: str = "",
        counterfactual: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
        corr: str = "",
        ref: str = "",
        sim_t: int = 0,
        sim_time: str = "",
    ) -> dict[str, Any]:
        assets = list(assets)
        body = {
            "seq": self._next_seq,
            "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "sim_t": sim_t,
            "sim_time": sim_time,
            "plant": self.plant_id,
            "kind": kind,
            "agent": agent,
            "asset": assets[0] if assets else "",
            "assets": assets,
            "decision_class": decision_class,
            "outcome": outcome,
            "summary": summary,
            "rationale": rationale,
            "counterfactual": counterfactual or {},
            "payload": payload or {},
            "corr": corr,
            "ref": ref,
            "prev_hash": self._head,
        }
        body["hash"] = entry_hash(body)
        self._entries.append(body)
        self._head = str(body["hash"])
        self._next_seq += 1
        if len(self._entries) > self.max_memory:
            drop = self._entries.pop(0)
            self._first_seq = drop["seq"] + 1
            self.anchor_hash = drop["hash"]
        if self.writer is not None:
            self.writer.enqueue("ledger", {**body, "id": f"{body['seq']:09d}", "pk": self.plant_id})
        for fn in self.listeners:
            fn(body)
        return body

    @property
    def head(self) -> str:
        return self._head

    def __len__(self) -> int:
        return len(self._entries)

    @property
    def last_seq(self) -> int:
        return self._next_seq - 1

    def get(self, seq: int) -> dict[str, Any] | None:
        i = seq - self._first_seq
        return self._entries[i] if 0 <= i < len(self._entries) else None

    def query(
        self,
        *,
        asset: str | None = None,
        agent: str | None = None,
        kind: str | None = None,
        outcome: str | None = None,
        corr: str | None = None,
        since_t: int | None = None,
        until_t: int | None = None,
        q: str | None = None,
        decision_class: str | None = None,
        limit: int = 100,
        offset: int = 0,
        desc: bool = True,
    ) -> dict[str, Any]:
        ql = q.lower() if q else None
        rows = []
        for e in self._entries:
            if asset and asset not in e["assets"] and e["asset"] != asset:
                continue
            if agent and e["agent"] != agent:
                continue
            if kind and e["kind"] != kind:
                continue
            if outcome and e["outcome"] != outcome:
                continue
            if corr and e["corr"] != corr:
                continue
            if decision_class and e["decision_class"] != decision_class:
                continue
            if since_t is not None and e["sim_t"] < since_t:
                continue
            if until_t is not None and e["sim_t"] > until_t:
                continue
            if ql and ql not in (e["summary"] + " " + e["rationale"] + " " + e["agent"] + " " + e["outcome"]).lower():
                continue
            rows.append(e)
        total = len(rows)
        if desc:
            rows = rows[::-1]
        return {"total": total, "items": rows[offset : offset + max(1, min(limit, 1000))]}

    # ------------------------------------------------------------------ integrity
    def verify(self) -> dict[str, Any]:
        prev = self.anchor_hash
        for e in self._entries:
            body = {k: v for k, v in e.items() if k != "hash"}
            if e["prev_hash"] != prev:
                return {
                    "ok": False,
                    "length": len(self._entries),
                    "broken_at": e["seq"],
                    "reason": "prev_hash mismatch",
                    "head": self._head,
                }
            if entry_hash(body) != e["hash"]:
                return {
                    "ok": False,
                    "length": len(self._entries),
                    "broken_at": e["seq"],
                    "reason": "entry content altered",
                    "head": self._head,
                }
            prev = e["hash"]
        return {
            "ok": True,
            "length": len(self._entries),
            "broken_at": None,
            "reason": "",
            "head": self._head,
            "anchor": self.anchor_hash,
            "first_seq": self._entries[0]["seq"] if self._entries else None,
        }

    def export_jsonl(self, **filters: Any) -> str:
        items = self.query(limit=1000000, desc=False, **filters)["items"] if filters else self._entries
        return "\n".join(json.dumps(e, sort_keys=True, separators=(",", ":"), default=str) for e in items) + (
            "\n" if items else ""
        )

    def stats(self) -> dict[str, Any]:
        by_kind: dict[str, int] = {}
        for e in self._entries:
            by_kind[e["kind"]] = by_kind.get(e["kind"], 0) + 1
        return {"entries": len(self._entries), "last_seq": self.last_seq, "head": self._head, "by_kind": by_kind}
