"""`GET /runs/{id}/events`: the SSE projection of the event log.

**The guarantee.** A client that reconnects with `Last-Event-ID` receives every
event after that id, exactly once, in sequence order. That has to hold across a
reconnect, a slow consumer, and two events committing concurrently.

**How it is achieved.** Not by making the bus reliable: by never trusting it.
The stream keeps its own cursor and treats the database as the only authority:

1. Subscribe to the bus *before* reading the backlog. Subscribing second would
   drop anything appended between the read and the subscribe, which is the
   classic form of this bug and is invisible until the log is under load.
2. Replay the backlog from the cursor.
3. Stream live, and on *any* anomaly (a sequence gap, a repeat, a dropped
   buffer) re-read the range from SQLite instead of reasoning about it.

Collapsing every anomaly into one authoritative re-read is what keeps this
correct. Out-of-order publication is possible (appends commit inside worker
threads and can resume in either order), so a design that assumed bus ordering
would be subtly wrong under exactly the concurrency the app is built to create.
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

#: How long to wait for an event before emitting a keepalive comment. Idle SSE
#: connections are dropped by intermediaries; a comment costs 15 bytes.
KEEPALIVE_SECONDS: Final[float] = 15.0

#: Told to the browser's EventSource, which otherwise waits 3 seconds before
#: reconnecting. The server is on loopback, so retry promptly.
RETRY_MILLISECONDS: Final[int] = 1000

SSE_HEADERS: Final[dict[str, str]] = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    # Belt and braces for any buffering proxy between here and the webview.
    "X-Accel-Buffering": "no",
}


def format_sse(event: Event) -> str:
    """Render one event as an SSE frame.

    ``id`` is the per-run ``seq``, never the global rowid: the client hands it
    back as ``Last-Event-ID`` scoped to this run, and a global id would make a
    resume skip every event another run happened to interleave.

    **There is deliberately no ``event:`` field.** Writing ``event: llm.token``
    would be the more idiomatic-looking SSE, and it is a trap here. A named SSE
    event does not fire ``EventSource.onmessage`` at all (the client must call
    ``addEventListener`` for that exact name), so any type the client has not
    registered is dropped silently, with no error anywhere. With 26 event types
    (§4) and more arriving each phase, that turns "someone forgot to update the
    client" into invisible data loss in a UI whose whole contract is being a
    faithful projection of the event log (§2).

    Unnamed frames all arrive on one ``onmessage``, and the type is already in
    the JSON body, so nothing is lost: an unrecognised type reaches the reducer
    and can be logged loudly instead of vanishing. This was not reasoned out in
    the abstract: a webview probe written against `onmessage` received zero of
    twenty events while `fetch` against the same endpoint received all of them.
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
    """Turn a ``Last-Event-ID`` header into a cursor, tolerating nonsense.

    A malformed value means replay from the beginning. Refusing the request
    would leave a reconnecting client permanently unable to attach, which is a
    far worse failure than re-sending events it may already have.
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
        """Emit everything the database holds beyond the cursor.

        The single authoritative path. Every anomaly routes here rather than
        being handled on its own terms.
        """
        for event in await self._store.read(self._run_id, after_seq=self._last_seq):
            self._last_seq = event.seq
            if event.type in TERMINAL_RUN_EVENTS:
                self._finished = True
            yield event

    async def _run_is_over(self) -> bool:
        """Whether the run reached a terminal status.

        Needed because a stream cannot always learn it is finished by *seeing*
        a terminal event. A client resuming a completed run with a cursor at or
        beyond the head receives no events at all, and would otherwise hold the
        connection open forever waiting for a run that ended some time ago.

        Safe against the obvious race: `_play_script` sets the status only
        after appending its last event, so a terminal status implies every
        event is already committed and one more catch-up drains them.

        A run that no longer exists is over. `DELETE /runs/{id}` refuses an
        unfinished run, so a stream should never be open on one that goes -
        but if it ever is, ending is right and waiting forever is not.
        """
        run = await self._store.get_run(self._run_id)
        return run is None or run.status in TERMINAL_RUN_STATUSES

    async def stream(self) -> AsyncIterator[Event | None]:
        """Yield this run's events in order; ``None`` is an idle tick.

        The idle tick is what lets a consumer act on a quiet connection without
        this class knowing what that action is. The SSE renderer turns it into a
        keepalive comment; the Phase 8 channel adapters ignore it. Neither
        concern belongs in the cursor logic, which is the part that must stay
        easy to reason about.
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

                # Anomalous, or simply the next event: in either case the
                # database is consulted rather than the delivered object
                # trusted. `_catch_up` re-reads from the cursor, so an event
                # already emitted yields nothing and no duplicate is possible.
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
    """This run's events, gap-free and in order, until it ends.

    The same cursor and anomaly handling `GET /runs/{id}/events` uses, one layer
    below the framing. Phase 8's channel adapters consume this: a chat message
    is another projection of the log (§2), and it needs exactly the guarantee
    the dashboard needs (every event, once, in sequence) while needing none of
    the SSE wire format.

    Growing a second stream implementation for the channels would have meant two
    answers to "did this consumer miss an event", and the three properties this
    one is careful about (subscribe before backlog, re-read on any anomaly,
    consult the run's status as well as its events) are exactly the three a
    second implementation would get subtly wrong. ``None`` is an idle tick.
    """
    return _RunStream(store, bus, run_id, after_seq).stream()


async def run_stream(
    store: EventStore, bus: EventBus, run_id: str, after_seq: int
) -> AsyncIterator[str]:
    """Build the SSE body for one client attaching to ``run_id``.

    One rendering of :func:`run_events`, and the only place the wire format
    lives.
    """
    yield f"retry: {RETRY_MILLISECONDS}\n\n"

    async for event in run_events(store, bus, run_id, after_seq):
        yield ": keepalive\n\n" if event is None else format_sse(event)
