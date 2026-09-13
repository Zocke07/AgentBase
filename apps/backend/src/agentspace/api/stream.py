"""`GET /runs/{id}/events`: the SSE projection of the event log.

A client that reconnects with `Last-Event-ID` receives every event after that
id, exactly once, in order, across reconnects, slow consumers and concurrent
commits. The bus is never trusted for that: the stream subscribes *before*
reading the backlog (the reverse order drops anything appended in between),
keeps its own cursor, and on any anomaly (a gap, a repeat, a dropped buffer)
re-reads the range from SQLite rather than reasoning about it. Out-of-order
publication is real, since appends commit on worker threads.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Final

from agentspace.events.types import TERMINAL_RUN_EVENTS, TERMINAL_RUN_STATUSES

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from agentspace.events.bus import EventBus
    from agentspace.events.store import EventStore
    from agentspace.events.types import Event

__all__ = [
    "KEEPALIVE_SECONDS",
    "SSE_HEADERS",
    "format_sse",
    "parse_last_event_id",
    "run_events",
    "run_stream",
]

logger = logging.getLogger("agentspace.api")

#: How long to wait for an event before emitting a keepalive comment.
KEEPALIVE_SECONDS: Final[float] = 15.0

#: EventSource's reconnect delay; loopback can afford a prompt one.
RETRY_MILLISECONDS: Final[int] = 1000

SSE_HEADERS: Final[dict[str, str]] = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    # Belt and braces for any buffering proxy between here and the webview.
    "X-Accel-Buffering": "no",
}


def format_sse(event: Event) -> str:
    """Render one event as an SSE frame.

    ``id`` is the per-run ``seq``, which is what ``Last-Event-ID`` hands back.
    There is deliberately no ``event:`` field: a named SSE event never fires
    ``EventSource.onmessage``, so any type the client had not registered would
    be dropped silently. The type travels in the JSON body instead, and an
    unrecognised one reaches the reducer where it can be logged.
    """
    data = json.dumps(
        {
            "id": event.id,
            "run_id": event.run_id,
            "seq": event.seq,
            "agent_id": event.agent_id,
            "type": str(event.type),
            "payload": event.payload,
            "ts": event.ts.isoformat(),
        },
        separators=(",", ":"),
    )
    return f"id: {event.seq}\ndata: {data}\n\n"


def parse_last_event_id(raw: str | None) -> int:
    """Turn a ``Last-Event-ID`` header into a cursor.

    A malformed value replays from the start.
    """
    if raw is None:
        return 0

    try:
        value = int(raw.strip())
    except ValueError:
        logger.warning("ignoring malformed Last-Event-ID %r", raw)
        return 0

    return max(value, 0)


class _RunStream:
    """Cursor and anomaly handling for one connected client."""

    def __init__(self, store: EventStore, bus: EventBus, run_id: str, after_seq: int) -> None:
        self._store = store
        self._bus = bus
        self._run_id = run_id
        self._last_seq = after_seq
        self._finished = False

    async def _catch_up(self) -> AsyncIterator[Event]:
        """Emit everything the database holds beyond the cursor: the one authoritative path."""
        for event in await self._store.read(self._run_id, after_seq=self._last_seq):
            self._last_seq = event.seq
            if event.type in TERMINAL_RUN_EVENTS:
                self._finished = True
            yield event

    async def _run_is_over(self) -> bool:
        """Whether the run reached a terminal status, or no longer exists.

        A client resuming a finished run past its head sees no terminal event
        and would otherwise wait forever. The status is set after the last
        event is appended, so a terminal status means one more catch-up
        drains everything.
        """
        run = await self._store.get_run(self._run_id)
        return run is None or run.status in TERMINAL_RUN_STATUSES

    async def stream(self) -> AsyncIterator[Event | None]:
        """Yield this run's events in order; ``None`` is an idle tick.

        The SSE renderer turns the tick into a keepalive comment.
        """
        # Subscribe first, then read the backlog. The reverse order silently
        # drops anything appended in between.
        with self._bus.subscribe(self._run_id) as subscription:
            async for backlog in self._catch_up():
                yield backlog

            if self._finished or await self._run_is_over():
                return

            while True:
                event = await subscription.get(KEEPALIVE_SECONDS)

                if event is None and not subscription.stale:
                    yield None
                    continue

                # Any anomaly re-reads from the cursor; an event already
                # emitted yields nothing, so no duplicate is possible.
                if event is None or subscription.stale or event.seq != self._last_seq + 1:
                    async for caught in self._catch_up():
                        yield caught
                    subscription.clear_stale()
                    if not self._finished and await self._run_is_over():
                        return
                else:
                    self._last_seq = event.seq
                    if event.type in TERMINAL_RUN_EVENTS:
                        self._finished = True
                    yield event

                if self._finished:
                    return


def run_events(
    store: EventStore, bus: EventBus, run_id: str, after_seq: int = 0
) -> AsyncIterator[Event | None]:
    """This run's events, gap-free and in order, until it ends; ``None`` is an idle tick.

    The cursor `GET /runs/{id}/events` uses, one layer below the framing, so
    the channel adapters get the same guarantee without a second implementation.
    """
    return _RunStream(store, bus, run_id, after_seq).stream()


async def run_stream(
    store: EventStore, bus: EventBus, run_id: str, after_seq: int
) -> AsyncIterator[str]:
    """Build the SSE body for one client attaching to ``run_id``: the only place the wire format
    lives.
    """
    yield f"retry: {RETRY_MILLISECONDS}\n\n"

    async for event in run_events(store, bus, run_id, after_seq):
        yield ": keepalive\n\n" if event is None else format_sse(event)
