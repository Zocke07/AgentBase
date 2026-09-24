"""In-process asyncio fan-out of appended events.

The bus is a hint, not a channel: SQLite is the source of truth. Events can
reach `publish` out of sequence (appends commit on worker threads), so the
consumer keeps its own cursor and re-reads on any jump. Queues are bounded:
on overflow the subscription is flagged stale and its buffer dropped, which
costs nothing because the rows are durable. Subscriptions are context
managers so a cancelled SSE task is still unregistered.
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

#: Buffered events per subscriber before the subscription is declared stale.
DEFAULT_QUEUE_SIZE: Final[int] = 512


class Subscription:
    """One subscriber's view of a single run's event flow."""

    def __init__(self, run_id: str, maxsize: int = DEFAULT_QUEUE_SIZE) -> None:
        self.run_id = run_id
        self._queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=maxsize)
        self._stale = False

    @property
    def stale(self) -> bool:
        """True when events were dropped and the consumer must re-read the DB."""
        return self._stale

    def offer(self, event: Event) -> None:
        """Non-blocking hand-off. Drops rather than waits when full."""
        if self._stale:
            return

        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            self.mark_stale()

    def mark_stale(self) -> None:
        """Flag a resync and release the buffer; the consumer will re-read from SQLite."""
        self._stale = True
        while True:
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        logger.warning("subscriber for run %s fell behind; will resync", self.run_id)

    def clear_stale(self) -> None:
        """Called by the consumer once it has caught up from the database."""
        self._stale = False

    async def get(self, wait_seconds: float | None = None) -> Event | None:
        """Wait for the next event, or return None once ``wait_seconds`` elapses."""
        if wait_seconds is None:
            return await self._queue.get()

        try:
            return await asyncio.wait_for(self._queue.get(), wait_seconds)
        except TimeoutError:
            return None


class EventBus:
    """Fan-out to every subscription registered for a run."""

    def __init__(self, queue_size: int = DEFAULT_QUEUE_SIZE) -> None:
        self._queue_size = queue_size
        self._subscriptions: dict[str, set[Subscription]] = {}

    def publish(self, event: Event) -> None:
        """Offer ``event`` to every subscriber of its run.

        Synchronous: an await here would widen the window between a commit and
        its event being offered.
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
        """Live subscriptions for ``run_id``, so a test can assert a disconnected client is
        unregistered.
        """
        return len(self._subscriptions.get(run_id, ()))
