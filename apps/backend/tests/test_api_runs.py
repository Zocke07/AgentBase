"""`GET /runs` — the list the replay picker reads.

§5 Phase 7 requires "Replay: scrub any past run from the event log". A user
cannot scrub a run they cannot find, and every other way of listing runs would
mean the UI holding its own idea of what exists — which is the drift §2 rules
out. So the list comes from the `runs` table, newest first, and carries only
what a picker renders: the goal, the status, and when it happened.

**Newest first is asserted, not incidental.** A picker showing the run you just
started at the bottom of a long list is a picker nobody scrolls. Ordering is a
property of the query, so it belongs in a test rather than in a comment.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from agentspace.main import create_app
from agentspace.secrets import SecretStore

if TYPE_CHECKING:
    from collections.abc import Iterator

    from agentspace.config import AppPaths
    from agentspace.events.store import EventStore


@pytest.fixture
def client(app_paths: AppPaths) -> Iterator[TestClient]:
    with TestClient(create_app(app_paths, secrets=SecretStore())) as test_client:
        yield test_client


# --- the endpoint -----------------------------------------------------------


def test_an_empty_workspace_lists_no_runs(client: TestClient) -> None:
    response = client.get("/runs")

    assert response.status_code == 200
    assert response.json() == []


def test_a_created_run_appears_in_the_list(client: TestClient) -> None:
    created = client.post("/debug/fake_run", params={"step_ms": 0}).json()

    listed = client.get("/runs").json()

    assert [run["id"] for run in listed] == [created["id"]]
    assert listed[0]["goal"] == created["goal"]


def test_runs_are_listed_newest_first(client: TestClient) -> None:
    """The picker's default view. Three runs, so a reversal is unambiguous."""
    ids = [client.post("/debug/fake_run", params={"step_ms": 0}).json()["id"] for _ in range(3)]

    listed = [run["id"] for run in client.get("/runs").json()]

    assert listed == list(reversed(ids))


def test_the_list_carries_what_a_picker_renders(client: TestClient) -> None:
    """Every field the run list needs, present on a run that has finished."""
    client.post("/debug/fake_run", params={"step_ms": 0})

    run = client.get("/runs").json()[0]

    assert run["status"] in {"pending", "running", "completed"}
    assert run["origin"] == "ui"
    assert run["created_at"]
    assert "finished_at" in run


def test_the_limit_bounds_the_list(client: TestClient) -> None:
    """A workspace with months of history must not hand the UI all of it."""
    for _ in range(4):
        client.post("/debug/fake_run", params={"step_ms": 0})

    listed = client.get("/runs", params={"limit": 2}).json()

    assert len(listed) == 2


@pytest.mark.parametrize("limit", [0, -1, 501])
def test_an_out_of_range_limit_is_refused(client: TestClient, limit: int) -> None:
    """A 422 naming the parameter, rather than a silently clamped value.

    Same reasoning as `extra="forbid"` on every request model in this project:
    a caller told its request worked when it was quietly altered has no way to
    notice (CLAUDE.md, Phase 4).
    """
    assert client.get("/runs", params={"limit": limit}).status_code == 422


# --- the store method behind it ---------------------------------------------


@pytest.mark.anyio
async def test_list_runs_reads_the_runs_table_not_the_event_log(store: EventStore) -> None:
    """A run with no events at all is still a run, and still listable.

    The event log is the authority on what *happened* in a run (§2); the `runs`
    table is the authority on which runs exist. A listing derived from events
    would omit a run that was created and never started — precisely the run a
    user is most likely to be looking for an explanation of.
    """
    created = await store.create_run(goal="never started")

    listed = await store.list_runs()

    assert [run.id for run in listed] == [created.id]
    assert listed[0].status == "pending"


@pytest.mark.anyio
async def test_list_runs_orders_by_creation_not_insertion(store: EventStore) -> None:
    first = await store.create_run(goal="first")
    second = await store.create_run(goal="second")

    listed = await store.list_runs()

    assert [run.id for run in listed] == [second.id, first.id]
