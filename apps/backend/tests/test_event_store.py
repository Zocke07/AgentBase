"""Tests for the event store — written before the implementation (BUILD_SPEC §6).

The event log is the single source of truth for the whole application (§2), so
the properties worth testing are the ones that would silently corrupt it:
sequence numbers that skip, repeat, or interleave between runs.
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

import pytest

from agentspace.events.types import EventType

if TYPE_CHECKING:
    from agentspace.events.store import EventStore
    from agentspace.store.db import Database

pytestmark = pytest.mark.anyio


async def _new_run(store: EventStore, goal: str = "test goal") -> str:
    run = await store.create_run(goal=goal, origin="ui")
    return run.id


# --- seq assignment ---------------------------------------------------------


async def test_append_starts_seq_at_one(store: EventStore) -> None:
    run_id = await _new_run(store)

    event = await store.append(run_id, EventType.RUN_STARTED, {"goal": "test goal"})

    assert event.seq == 1
    assert event.run_id == run_id
    assert event.type is EventType.RUN_STARTED


async def test_append_increments_seq_per_run(store: EventStore) -> None:
    run_id = await _new_run(store)

    seqs = [
        (await store.append(run_id, EventType.AGENT_MESSAGE, {"i": i})).seq for i in range(5)
    ]

    assert seqs == [1, 2, 3, 4, 5]


async def test_seq_is_per_run_not_global(store: EventStore) -> None:
    """Two runs each start at 1.

    A global counter would make replay ids leak across runs and break
    ``Last-Event-ID`` resume for every run but the first.
    """
    first = await _new_run(store, "first")
    second = await _new_run(store, "second")

    await store.append(first, EventType.RUN_STARTED, {})
    await store.append(first, EventType.AGENT_SPAWNED, {})
    second_event = await store.append(second, EventType.RUN_STARTED, {})

    assert second_event.seq == 1


async def test_concurrent_appends_produce_a_gapless_sequence(store: EventStore) -> None:
    """The atomicity test.

    ``seq`` is assigned by ``SELECT MAX(seq) + 1`` inside the INSERT. Read and
    write must happen under one write transaction or two racing appends both
    read the same maximum and one is lost. Every append here runs in its own
    thread via ``asyncio.to_thread``, so this is genuine contention.
    """
    run_id = await _new_run(store)
    count = 60

    await asyncio.gather(
        *(store.append(run_id, EventType.LLM_TOKEN, {"i": i}) for i in range(count))
    )

    events = await store.read(run_id)
    assert [event.seq for event in events] == list(range(1, count + 1))


async def test_concurrent_appends_across_runs_do_not_interfere(store: EventStore) -> None:
    runs = [await _new_run(store, f"run {i}") for i in range(3)]

    await asyncio.gather(
        *(
            store.append(run_id, EventType.AGENT_MESSAGE, {"i": i})
            for run_id in runs
            for i in range(20)
        )
    )

    for run_id in runs:
        events = await store.read(run_id)
        assert [event.seq for event in events] == list(range(1, 21))


# --- reading ----------------------------------------------------------------


async def test_read_returns_events_in_seq_order(store: EventStore) -> None:
    run_id = await _new_run(store)
    for i in range(10):
        await store.append(run_id, EventType.AGENT_MESSAGE, {"i": i})

    events = await store.read(run_id)

    assert [event.seq for event in events] == sorted(event.seq for event in events)
    assert [event.payload["i"] for event in events] == list(range(10))


async def test_read_after_seq_excludes_the_cursor_itself(store: EventStore) -> None:
    """``Last-Event-ID`` names the last event the client *already has*.

    Resume must therefore be exclusive; off by one here is a duplicate on every
    single reconnect.
    """
    run_id = await _new_run(store)
    for i in range(5):
        await store.append(run_id, EventType.AGENT_MESSAGE, {"i": i})

    events = await store.read(run_id, after_seq=2)

    assert [event.seq for event in events] == [3, 4, 5]


async def test_read_respects_until_seq(store: EventStore) -> None:
    run_id = await _new_run(store)
    for i in range(6):
        await store.append(run_id, EventType.AGENT_MESSAGE, {"i": i})

    events = await store.read(run_id, after_seq=1, until_seq=4)

    assert [event.seq for event in events] == [2, 3, 4]


async def test_read_of_unknown_run_is_empty_not_an_error(store: EventStore) -> None:
    assert await store.read("no-such-run") == []


# --- payloads and integrity -------------------------------------------------


async def test_payload_survives_a_round_trip(store: EventStore) -> None:
    run_id = await _new_run(store)
    payload = {"text": "unicode OK and 'quotes'", "nested": {"n": [1, 2, 3]}, "none": None}

    await store.append(run_id, EventType.AGENT_MESSAGE, payload)
    (event,) = await store.read(run_id)

    assert event.payload == payload


async def test_payload_is_stored_as_json_text(db: Database, store: EventStore) -> None:
    """The column is TEXT holding JSON (§4).

    Storing a Python repr instead would still round-trip through Python and
    fail only once something else — the TS client, a replay tool — reads it.
    """
    run_id = await _new_run(store)
    await store.append(run_id, EventType.AGENT_MESSAGE, {"k": "v"})

    with db.read() as connection:
        raw = connection.execute("SELECT payload FROM events").fetchone()["payload"]

    assert json.loads(raw) == {"k": "v"}


async def test_timestamps_are_timezone_aware_utc(store: EventStore) -> None:
    run_id = await _new_run(store)
    event = await store.append(run_id, EventType.RUN_STARTED, {})

    offset = event.ts.utcoffset()
    assert offset is not None
    assert offset.total_seconds() == 0


async def test_append_to_unknown_run_is_rejected(store: EventStore) -> None:
    """A foreign key on ``events.run_id`` (§4).

    Without ``PRAGMA foreign_keys = ON`` SQLite accepts orphan rows silently,
    which is how an event log grows events belonging to no run.
    """
    with pytest.raises(Exception, match=r"(?i)foreign key"):
        await store.append("does-not-exist", EventType.RUN_STARTED, {})


async def test_agent_id_is_optional_and_preserved(store: EventStore) -> None:
    run_id = await _new_run(store)

    without = await store.append(run_id, EventType.RUN_STARTED, {})
    with_agent = await store.append(run_id, EventType.AGENT_MESSAGE, {}, agent_id="researcher")

    assert without.agent_id is None
    assert with_agent.agent_id == "researcher"


# --- runs -------------------------------------------------------------------


async def test_create_and_fetch_run(store: EventStore) -> None:
    run = await store.create_run(goal="ship phase 2", origin="ui")

    fetched = await store.get_run(run.id)

    assert fetched is not None
    assert fetched.goal == "ship phase 2"
    assert fetched.status == "pending"
    assert fetched.origin == "ui"
    assert fetched.finished_at is None


async def test_get_unknown_run_returns_none(store: EventStore) -> None:
    assert await store.get_run("nope") is None


async def test_set_run_status_records_finished_at_for_terminal_states(
    store: EventStore,
) -> None:
    run = await store.create_run(goal="g", origin="ui")

    await store.set_run_status(run.id, "running")
    running = await store.get_run(run.id)
    assert running is not None
    assert running.finished_at is None

    await store.set_run_status(run.id, "completed")
    done = await store.get_run(run.id)
    assert done is not None
    assert done.status == "completed"
    assert done.finished_at is not None


async def test_max_seq_reports_the_current_head(store: EventStore) -> None:
    run_id = await _new_run(store)
    assert await store.max_seq(run_id) == 0

    for _ in range(3):
        await store.append(run_id, EventType.AGENT_MESSAGE, {})

    assert await store.max_seq(run_id) == 3
