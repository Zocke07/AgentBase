"""`GET /runs/{id}/events`: SSE projection of the event log.

Reconnects with `Last-Event-ID` receive later events exactly once and in
order, despite slow consumers and concurrent commits. Subscribe before reading
the backlog or an intervening append is lost. On gaps, repeats, or dropped
buffers, reread SQLite from the cursor; worker-thread commits can publish out
of order.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Final

from agentbase.events.types import TERMINAL_RUN_EVENTS, TERMINAL_RUN_STATUSES

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from agentbase.events.bus import EventBus
    from agentbase.events.store import EventStore
    from agentbase.events.types import Event

__all__ = [
    "KEEPALIVE_SECONDS",
    "SSE_HEADERS",
    "format_sse",
    "parse_last_event_id",
    "run_events",
    "run_stream",
]

logger = logging.getLogger("agentbase.api")

#: Wait this long before emitting a keepalive comment.
KEEPALIVE_SECONDS: Final[float] = 15.0

#: Prompt EventSource reconnect delay is viable on loopback.
RETRY_MILLISECONDS: Final[int] = 1000

SSE_HEADERS: Final[dict[str, str]] = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    # Disable buffering by proxies between the sidecar and webview.
    "X-Accel-Buffering": "no",
}


def format_sse(event: Event) -> str:
    """Render an event as an SSE frame.

    ``id`` is the per-run ``seq`` returned by ``Last-Event-ID``. Omit
    ``event:``: named events bypass ``EventSource.onmessage`` and silently
    drop unregistered types. Carry type in JSON so the reducer can log unknowns.
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
    """Parse ``Last-Event-ID`` as a cursor; malformed values replay from start."""
    if raw is None:
        return 0

    try:
        value = int(raw.strip())
    except ValueError:
        logger.warning("ignoring malformed Last-Event-ID %r", raw)
        return 0

    return max(value, 0)


class _RunStream:
    """Per-client cursor and anomaly handling."""

    def __init__(self, store: EventStore, bus: EventBus, run_id: str, after_seq: int) -> None:
        self._store = store
        self._bus = bus
        self._run_id = run_id
        self._last_seq = after_seq
        self._finished = False

    async def _catch_up(self) -> AsyncIterator[Event]:
        """Emit database events beyond the cursor; this is the authoritative path."""
        for event in await self._store.read(self._run_id, after_seq=self._last_seq):
            self._last_seq = event.seq
            if event.type in TERMINAL_RUN_EVENTS:
                self._finished = True
            yield event

    async def _run_is_over(self) -> bool:
        """Return whether the run ended or no longer exists.

        A client resuming past a finished run's head sees no terminal event and
        would wait forever. Status follows the final append, so one catch-up
        drains all events.
        """
        run = await self._store.get_run(self._run_id)
        return run is None or run.status in TERMINAL_RUN_STATUSES

    async def stream(self) -> AsyncIterator[Event | None]:
        """Yield ordered run events; ``None`` is an idle tick rendered as a keepalive."""
        # Subscribe before reading backlog or an intervening append is lost.
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

                # Reread from cursor on anomalies; emitted events cannot repeat.
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
    """Yield this run's gap-free ordered events until it ends; ``None`` is idle.

    This underlies `GET /runs/{id}/events`, giving channel adapters the same
    guarantee without another implementation.
    """
    return _RunStream(store, bus, run_id, after_seq).stream()


async def run_stream(
    store: EventStore, bus: EventBus, run_id: str, after_seq: int
) -> AsyncIterator[str]:
    """Build one client's SSE body; the only wire-format implementation."""
    yield f"retry: {RETRY_MILLISECONDS}\n\n"

    async for event in run_events(store, bus, run_id, after_seq):
        yield ": keepalive\n\n" if event is None else format_sse(event)
