"""In-process pub/sub hub used for Server-Sent Events (live plant, agent activity, inbox, ledger)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any


class Subscription:
    def __init__(self, hub: EventHub, topics: set[str] | None, maxsize: int) -> None:
        self.hub = hub
        self.topics = topics
        self.queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue(maxsize=maxsize)
        self.dropped = 0

    def offer(self, topic: str, data: Any) -> None:
        if self.topics is not None and topic not in self.topics:
            return
        if self.queue.full():
            try:
                self.queue.get_nowait()
                self.dropped += 1
            except asyncio.QueueEmpty:  # pragma: no cover
                pass
        self.queue.put_nowait((topic, data))

    def close(self) -> None:
        self.hub.unsubscribe(self)


class EventHub:
    def __init__(self) -> None:
        self._subs: set[Subscription] = set()
        self.published = 0

    def subscribe(self, topics: set[str] | None = None, maxsize: int = 1000) -> Subscription:
        sub = Subscription(self, topics, maxsize)
        self._subs.add(sub)
        return sub

    def unsubscribe(self, sub: Subscription) -> None:
        self._subs.discard(sub)

    def publish(self, topic: str, data: Any) -> None:
        self.published += 1
        for s in list(self._subs):
            s.offer(topic, data)

    @property
    def subscribers(self) -> int:
        return len(self._subs)


def sse_format(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, separators=(',', ':'), default=str)}\n\n"


async def sse_stream(
    sub: Subscription, *, keepalive_s: float = 15.0, first: list[tuple[str, Any]] | None = None, is_disconnected=None
) -> AsyncIterator[str]:
    """Yield SSE frames until the client goes away; sends a comment keepalive when idle."""
    try:
        for topic, data in first or []:
            yield sse_format(topic, data)
        while True:
            if is_disconnected is not None and await is_disconnected():
                break
            try:
                topic, data = await asyncio.wait_for(sub.queue.get(), timeout=keepalive_s)
            except TimeoutError:
                yield ": keepalive\n\n"
                continue
            yield sse_format(topic, data)
    finally:
        sub.close()
