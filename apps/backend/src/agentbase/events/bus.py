"""In-process asyncio fan-out for appended events.

The bus is a hint; SQLite is authoritative. Worker-thread commits can publish
out of order, so consumers keep a cursor and reread jumps. Overflow marks a
bounded queue stale and drops its buffer because rows are durable. Context
managed subscriptions unregister cancelled SSE tasks.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import contextmanager
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Iterator

    from agentbase.events.types import Event

__all__ = ["DEFAULT_QUEUE_SIZE", "EventBus", "Subscription"]

logger = logging.getLogger("agentbase.events")

#: Events buffered per subscriber before marking it stale.
DEFAULT_QUEUE_SIZE: Final[int] = 512


class Subscription:
    """One subscriber's view of one run's event flow."""

    def __init__(self, run_id: str, maxsize: int = DEFAULT_QUEUE_SIZE) -> None:
        self.run_id = run_id
        self._queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=maxsize)
        self._stale = False

    @property
    def stale(self) -> bool:
        """Whether dropped events require the consumer to reread the database."""
        return self._stale

    def offer(self, event: Event) -> None:
        """Hand off without blocking; drop rather than wait when full."""
        if self._stale:
            return

        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            self.mark_stale()

    def mark_stale(self) -> None:
        """Flag resync and clear the buffer; the consumer rereads SQLite."""
        self._stale = True
        while True:
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        logger.warning("subscriber for run %s fell behind; will resync", self.run_id)

    def clear_stale(self) -> None:
        """Clear stale after the consumer catches up from the database."""
        self._stale = False

    async def get(self, wait_seconds: float | None = None) -> Event | None:
        """Wait for the next event, or return ``None`` after ``wait_seconds``."""
        if wait_seconds is None:
            return await self._queue.get()

        try:
            return await asyncio.wait_for(self._queue.get(), wait_seconds)
        except TimeoutError:
            return None


class EventBus:
    """Fan out events to a run's subscriptions."""

    def __init__(self, queue_size: int = DEFAULT_QUEUE_SIZE) -> None:
        self._queue_size = queue_size
        self._subscriptions: dict[str, set[Subscription]] = {}

    def publish(self, event: Event) -> None:
        """Offer ``event`` to its run's subscribers.

        Stay synchronous to avoid widening the commit-to-offer window.
        """
        for subscription in tuple(self._subscriptions.get(event.run_id, ())):
            subscription.offer(event)

    @contextmanager
    def subscribe(self, run_id: str) -> Iterator[Subscription]:
        """Register a subscription for the duration of the block."""
        subscription = Subscription(run_id, maxsize=self._queue_size)
        self._subscriptions.setdefault(run_id, set()).add(subscription)

        try:
            yield subscription
        finally:
            subscribers = self._subscriptions.get(run_id)
            if subscribers is not None:
                subscribers.discard(subscription)
                if not subscribers:
                    del self._subscriptions[run_id]

    def subscriber_count(self, run_id: str) -> int:
        """Return live ``run_id`` subscriptions; tests verify disconnected clients unregister."""
        return len(self._subscriptions.get(run_id, ()))
