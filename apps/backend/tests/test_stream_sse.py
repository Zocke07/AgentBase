"""Tests for the SSE stream and the Phase 2 acceptance criterion.

§5 Phase 2 accepts when "the debug run streams to a curl client, and
killing/reconnecting mid-stream resumes with zero gaps and zero duplicates".
`test_reconnect_mid_stream_has_no_gaps_and_no_duplicates` is that criterion
expressed as a test; the rest cover the ways it can be satisfied by accident.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest
from fastapi.testclient import TestClient

from agentspace import main
from agentspace.api.stream import format_sse, parse_last_event_id, run_events
from agentspace.events.types import Event, EventType

if TYPE_CHECKING:
    from collections.abc import Iterator

    from agentspace.config import AppPaths
    from agentspace.events.bus import EventBus
    from agentspace.events.store import EventStore
    from agentspace.store.db import Database


@pytest.fixture
def client(app_paths: AppPaths) -> Iterator[TestClient]:
    """A client over an app wired to an isolated data directory."""
    with TestClient(main.create_app(app_paths)) as test_client:
        yield test_client


def _parse_frames(text: str) -> list[dict[str, Any]]:
    """Pull the `data:` payloads out of an SSE body, ignoring comments."""
    events: list[dict[str, Any]] = []

    for block in text.split("\n\n"):
        for line in block.splitlines():
            if line.startswith("data: "):
                events.append(json.loads(line.removeprefix("data: ")))

    return events


def _read_until(response: Any, wanted: int, cap: int = 400) -> list[dict[str, Any]]:
    """Consume SSE lines until `wanted` events have arrived, then stop reading.

    Abandoning the iterator mid-body is what makes this a genuine mid-stream
    disconnect rather than a tidy close.
    """
    events: list[dict[str, Any]] = []

    for count, line in enumerate(response.iter_lines()):
        if line.startswith("data: "):
            events.append(json.loads(line.removeprefix("data: ")))
            if len(events) >= wanted:
                break
        if count > cap:
            break

    return events


# --- frame formatting -------------------------------------------------------


def test_format_sse_uses_seq_as_the_event_id() -> None:
    """`Last-Event-ID` is per-run, so the id must be `seq`, not the rowid.

    Using the global rowid would make a resume on one run skip every event
    another run interleaved — a bug that only appears with concurrent runs.
    """
    from datetime import UTC, datetime

    event = Event(
        id=9999,
        run_id="run-1",
        seq=7,
        type=EventType.AGENT_MESSAGE,
        payload={"text": "hi"},
        ts=datetime.now(UTC),
    )

    frame = format_sse(event)

    assert frame.startswith("id: 7\n")
    assert frame.endswith("\n\n")
    assert json.loads(frame.split("data: ")[1].strip())["payload"] == {"text": "hi"}


def test_frames_are_unnamed_so_onmessage_receives_every_type() -> None:
    """A named SSE event never fires `EventSource.onmessage`.

    With an `event:` field the client must `addEventListener` for each of the
    26 types in §4, and any type it has not registered is dropped silently —
    invisible data loss in a UI whose contract is to be a faithful projection
    of the event log. Verified the hard way rather than reasoned about: a
    webview probe using `onmessage` received 0 of 20 events from a named-event
    stream while `fetch` on the same endpoint received all 20.
    """
    from datetime import UTC, datetime

    event = Event(
        id=1,
        run_id="run-1",
        seq=1,
        type=EventType.RUN_STARTED,
        payload={},
        ts=datetime.now(UTC),
    )

    frame = format_sse(event)

    assert "event: " not in frame
    # The type is not lost; it travels inside the JSON body instead.
    assert json.loads(frame.split("data: ")[1].strip())["type"] == "run.started"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(None, 0), ("0", 0), ("12", 12), ("  12  ", 12), ("garbage", 0), ("", 0), ("-5", 0)],
)
def test_parse_last_event_id(raw: str | None, expected: int) -> None:
    """A malformed header replays from the start rather than failing.

    Refusing would leave a reconnecting client permanently unable to attach.
    """
    assert parse_last_event_id(raw) == expected


# --- the stream endpoint ----------------------------------------------------


def test_stream_of_unknown_run_is_404(client: TestClient) -> None:
    response = client.get("/runs/nope/events")

    assert response.status_code == 404


def test_stream_declares_the_sse_content_type(client: TestClient) -> None:
    """Streamed against a run that terminates, on purpose.

    A stream attached to an idle run stays open forever — which is what SSE is
    for, and which makes `TestClient`'s synchronous close block indefinitely,
    because it waits for the response body to end. Real clients are cancelled
    by uvicorn when their socket closes; the sync test client has no such
    signal. Any test that opens a stream here must pick a run that finishes.
    """
    run = client.post("/debug/fake_run?step_ms=0").json()

    with client.stream("GET", f"/runs/{run['id']}/events") as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers["cache-control"].startswith("no-cache")
        response.read()


def test_completed_run_replays_its_backlog_and_closes(client: TestClient) -> None:
    """Replay is the same code path as live (§5 Phase 7 depends on this)."""
    run = client.post("/debug/fake_run?step_ms=0").json()

    body = client.get(f"/runs/{run['id']}/events").text
    events = _parse_frames(body)

    assert [event["seq"] for event in events] == list(range(1, 21))
    assert events[0]["type"] == "run.started"
    assert events[-1]["type"] == "run.completed"


def test_stream_closes_on_a_terminal_event_rather_than_hanging(client: TestClient) -> None:
    """Without this the request never completes and the test suite hangs."""
    run = client.post("/debug/fake_run?step_ms=0").json()

    response = client.get(f"/runs/{run['id']}/events")

    assert response.status_code == 200
    assert _parse_frames(response.text)[-1]["type"] == "run.completed"


def test_last_event_id_resumes_after_the_cursor(client: TestClient) -> None:
    run = client.post("/debug/fake_run?step_ms=0").json()

    body = client.get(f"/runs/{run['id']}/events", headers={"Last-Event-ID": "12"}).text
    events = _parse_frames(body)

    assert [event["seq"] for event in events] == list(range(13, 21))


def test_after_seq_in_the_query_resumes_like_the_header(client: TestClient) -> None:
    """`EventSource` cannot send `Last-Event-ID` on its first connection, so a
    client that has already loaded the history had no way to say so and
    received the whole log a second time. The query parameter is the same
    cursor by another route."""
    run = client.post("/debug/fake_run?step_ms=0").json()

    body = client.get(f"/runs/{run['id']}/events?after_seq=12").text

    assert [event["seq"] for event in _parse_frames(body)] == list(range(13, 21))


def test_the_header_wins_over_the_query_when_it_is_further_along(client: TestClient) -> None:
    """A browser reconnecting keeps the original URL, `after_seq` included,
    and adds `Last-Event-ID` for the last frame it saw — which is later. Taking
    the query would replay everything since the history loaded."""
    run = client.post("/debug/fake_run?step_ms=0").json()

    body = client.get(
        f"/runs/{run['id']}/events?after_seq=12", headers={"Last-Event-ID": "15"}
    ).text

    assert [event["seq"] for event in _parse_frames(body)] == list(range(16, 21))


def test_last_event_id_beyond_the_head_yields_nothing_and_closes(client: TestClient) -> None:
    run = client.post("/debug/fake_run?step_ms=0").json()

    body = client.get(f"/runs/{run['id']}/events", headers={"Last-Event-ID": "999"}).text

    assert _parse_frames(body) == []


@pytest.mark.anyio
async def test_a_stream_on_a_run_that_no_longer_exists_ends(
    store: EventStore, bus: EventBus, db: Database
) -> None:
    """A run that is gone is over. `DELETE /runs/{id}` refuses an unfinished
    run, so the product never opens this path — which is exactly why it has
    to be pinned here: the alternative is a keepalive loop that never ends,
    and nothing else would ever exercise it."""
    run = await store.create_run(goal="vanishes")
    # The row disappears from under the cursor. The store will not do this to
    # an unfinished run, so the test does.
    with db.write() as connection:
        connection.execute("DELETE FROM runs WHERE id = ?", (run.id,))

    seen = [event async for event in run_events(store, bus, run.id)]

    assert seen == []


def test_stream_emits_a_retry_hint(client: TestClient) -> None:
    run = client.post("/debug/fake_run?step_ms=0").json()

    body = client.get(f"/runs/{run['id']}/events").text

    assert body.startswith("retry: ")


# --- the acceptance criterion ----------------------------------------------


def test_reconnect_mid_stream_has_no_gaps_and_no_duplicates(client: TestClient) -> None:
    """BUILD_SPEC §5 Phase 2's acceptance criterion.

    Start the debug run, consume part of it, drop the connection without
    draining, then reconnect with `Last-Event-ID`. The two halves concatenated
    must be exactly 1..20 — every event once, in order.
    """
    run = client.post("/debug/fake_run?step_ms=25").json()

    with client.stream("GET", f"/runs/{run['id']}/events") as response:
        first_half = _read_until(response, wanted=6)

    assert len(first_half) == 6
    cursor = first_half[-1]["seq"]

    second_half = _parse_frames(
        client.get(f"/runs/{run['id']}/events", headers={"Last-Event-ID": str(cursor)}).text
    )

    seqs = [event["seq"] for event in first_half + second_half]

    assert seqs == list(range(1, 21)), "expected a gapless, duplicate-free 1..20"
    assert len(seqs) == len(set(seqs)), "an event was delivered twice"


def test_reconnecting_repeatedly_still_yields_each_event_once(client: TestClient) -> None:
    """One reconnect could pass by luck; four in a row could not."""
    run = client.post("/debug/fake_run?step_ms=25").json()

    collected: list[int] = []
    cursor = 0

    for _ in range(4):
        with client.stream(
            "GET",
            f"/runs/{run['id']}/events",
            headers={"Last-Event-ID": str(cursor)},
        ) as response:
            chunk = _read_until(response, wanted=3)

        if not chunk:
            break

        collected.extend(event["seq"] for event in chunk)
        cursor = chunk[-1]["seq"]

    remainder = _parse_frames(
        client.get(f"/runs/{run['id']}/events", headers={"Last-Event-ID": str(cursor)}).text
    )
    collected.extend(event["seq"] for event in remainder)

    assert collected == list(range(1, 21))


def test_a_client_that_disconnects_is_unregistered_from_the_bus(client: TestClient) -> None:
    """A leaked subscription would slowly consume memory across reconnects."""
    run = client.post("/debug/fake_run?step_ms=25").json()

    with client.stream("GET", f"/runs/{run['id']}/events") as response:
        _read_until(response, wanted=3)

    # Drain to completion so the run finishes and its stream closes.
    client.get(f"/runs/{run['id']}/events", headers={"Last-Event-ID": "0"})

    assert client.app.state.bus.subscriber_count(run["id"]) == 0  # type: ignore[attr-defined]


# --- runs API ---------------------------------------------------------------


def test_create_run_returns_a_pending_run(client: TestClient) -> None:
    response = client.post("/runs", json={"goal": "summarise the report"})

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "pending"
    assert body["goal"] == "summarise the report"


def test_create_run_rejects_an_empty_goal(client: TestClient) -> None:
    assert client.post("/runs", json={"goal": ""}).status_code == 422


def test_create_run_rejects_an_unknown_origin(client: TestClient) -> None:
    assert client.post("/runs", json={"goal": "g", "origin": "irc"}).status_code == 422


def test_get_unknown_run_is_404(client: TestClient) -> None:
    assert client.get("/runs/nope").status_code == 404


def test_history_endpoint_returns_the_whole_log(client: TestClient) -> None:
    run = client.post("/debug/fake_run?step_ms=0").json()
    # The debug run is a background task, so the POST returns before the script
    # has played. Consuming the stream blocks until the terminal event.
    client.get(f"/runs/{run['id']}/events")

    events = client.get(f"/runs/{run['id']}/events/history").json()

    assert [event["seq"] for event in events] == list(range(1, 21))


def test_fake_run_emits_twenty_events_and_completes(client: TestClient) -> None:
    """§5 Phase 2 asks for "~20 events over 10 seconds"; the default step is
    500 ms, so the count is what the test pins and the pace is the default."""
    run = client.post("/debug/fake_run?step_ms=0").json()
    client.get(f"/runs/{run['id']}/events")

    events = client.get(f"/runs/{run['id']}/events/history").json()
    finished = client.get(f"/runs/{run['id']}").json()

    assert len(events) == 20
    assert finished["status"] == "completed"
    assert finished["finished_at"] is not None


#: The payload keys the dashboard's reducer reads for each event type it folds
#: (`apps/desktop/src/state/reducer.ts`). Payloads are conventions, not schemas
#: (`events/types.py`), so this is the one place the convention is written down
#: from the reader's side. The script must speak it or the demo run renders
#: wrongly — it showed an *expired* approval and an empty tool result, because
#: it said ``decision`` where the reducer reads ``status`` and ``bytes`` where
#: it reads ``result``.
_KEYS_THE_REDUCER_READS: dict[EventType, set[str]] = {
    EventType.RUN_STARTED: {"goal"},
    EventType.RUN_COMPLETED: {"summary"},
    EventType.AGENT_SPAWNED: {"role"},
    EventType.AGENT_THINKING: {"step"},
    EventType.AGENT_HANDOFF: {"to", "task"},
    EventType.AGENT_COMPLETED: {"reason", "steps"},
    EventType.LLM_REQUEST: {"provider", "model"},
    EventType.LLM_TOKEN: {"text"},
    EventType.LLM_RESPONSE: {"input_tokens", "output_tokens", "stop_reason"},
    EventType.TOOL_REQUESTED: {"tool", "args", "call_id"},
    EventType.TOOL_CALLED: {"tool", "args", "call_id"},
    EventType.TOOL_RESULT: {"tool", "call_id", "result"},
    EventType.TOOL_APPROVED: {"tool", "approval_id", "automatic"},
    EventType.APPROVAL_REQUESTED: {"approval_id", "tool", "risk", "prompt"},
    EventType.APPROVAL_RESOLVED: {"approval_id", "status"},
    EventType.AGENT_MESSAGE: {"text"},
}


def test_the_fake_run_speaks_the_reducers_dialect(client: TestClient) -> None:
    """The scripted run is what the dashboard renders before any key exists,
    and the reducer folds it like a real one: every scripted event must carry
    the keys the reducer reads for its type, with the values the reducer
    expects (`status` is an approval status, `result` is a string)."""
    run = client.post("/debug/fake_run?step_ms=0").json()
    # The stream, not the history: it waits for the terminal event, so the
    # whole script has landed by the time it returns.
    events = _parse_frames(client.get(f"/runs/{run['id']}/events").text)

    for event in events:
        event_type = EventType(event["type"])
        expected = _KEYS_THE_REDUCER_READS[event_type]
        missing = expected - set(event["payload"])
        assert not missing, f"{event['type']} (seq {event['seq']}) lacks {sorted(missing)}"

    resolved = next(e for e in events if e["type"] == "approval.resolved")
    assert resolved["payload"]["status"] == "approved"
    result = next(e for e in events if e["type"] == "tool.result")
    assert isinstance(result["payload"]["result"], str)


def test_fake_run_default_pace_matches_the_spec() -> None:
    """20 events at the default step is the 10 seconds §5 Phase 2 describes."""
    from agentspace.api.runs import _FAKE_RUN_SCRIPT, DEFAULT_STEP_MS

    assert len(_FAKE_RUN_SCRIPT) == 20
    assert len(_FAKE_RUN_SCRIPT) * DEFAULT_STEP_MS / 1000 == 10.0


def test_two_runs_stream_independently(client: TestClient) -> None:
    """Both start their sequence at 1; a global counter would break resume."""
    first = client.post("/debug/fake_run?step_ms=0").json()
    second = client.post("/debug/fake_run?step_ms=0").json()

    first_events = _parse_frames(client.get(f"/runs/{first['id']}/events").text)
    second_events = _parse_frames(client.get(f"/runs/{second['id']}/events").text)

    assert first_events[0]["seq"] == 1
    assert second_events[0]["seq"] == 1
    assert {event["run_id"] for event in first_events} == {first["id"]}
