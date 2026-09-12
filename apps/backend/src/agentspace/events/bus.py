"""In-process asyncio fan-out of appended events.

**The bus is a hint, not a channel.** SQLite is the source of truth; this only
tells subscribers that something new exists. That framing is what makes the
rest of the design safe, and it is load-bearing in three places:

*Ordering.* `EventStore.append` commits inside `asyncio.to_thread`, and two
concurrent appends can resume in either order, so events can reach `publish`
out of sequence even though they committed in sequence. The stream consumer
therefore tracks its own cursor and treats any jump as a signal to re-read
from the database, rather than trusting bus order.

*Backpressure.* Queues are bounded. A subscriber that stops reading (a
webview on a suspended tab, a `curl` piped into `less`) would otherwise grow
the queue until the process dies. On overflow the subscription is flagged
stale and its queue dropped; the consumer notices and re-syncs from the
database. Losing a buffered copy costs nothing because the row is durable.

*Cancellation.* Subscriptions are handed out through a context manager so an
SSE client that disconnects mid-stream is unregistered even though its task was
cancelled rather than returning.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import contextmanager
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Iterator

    from agentspace.events.types import Event

__all__ = ["DEFAULT_QUEUE_SIZE", "EventBus", "Subscription"]

logger = logging.getLogger("agentspace.events")

#: Buffered events per subscriber before the subscription is declared stale.
#: Large enough that an ordinary slow render never trips it, small enough that
#: a wedged client cannot consume meaningful memory.
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
        """Flag a resync and release the buffer.

        The buffered events are discarded on purpose: the consumer is about to
        re-read the whole range from SQLite, so holding them only wastes memory
        during exactly the episode where memory is under pressure.
        """
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
        """Wait for the next event, or return None once ``wait_seconds`` elapses.

        Returning a sentinel rather than raising is what lets the SSE loop emit
        a keepalive comment and carry on, instead of treating an idle run as an
        error. Not named ``timeout``: this does not cancel the caller, and the
        name would suggest the cancellation semantics of ``asyncio.timeout``.
        """
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

        Synchronous by design. `put_nowait` needs no await, and introducing one
        here would create a suspension point between an append committing and
        its event being offered, during which another append could publish and
        widen the reordering window the consumer has to repair.
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
        """Live subscriptions for ``run_id``. Exists so a test can assert that
        a disconnected client is actually unregistered rather than leaked."""
        return len(self._subscriptions.get(run_id, ()))
