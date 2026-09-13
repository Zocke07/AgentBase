"""`GET /runs`: the list the run picker reads, from the `runs` table, newest
first. Ordering is asserted, since a picker showing the newest run at the
bottom is one nobody scrolls.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from agentspace.main import create_app
from agentspace.secrets import SecretStore
from support import ScriptedProvider, call, says

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


# --- DELETE /runs/{id} ------------------------------------------------------


def _finished_debug_run(client: TestClient) -> str:
    run = client.post("/debug/fake_run", params={"step_ms": 0}).json()
    client.get(f"/runs/{run['id']}/events")  # drains to the terminal event
    return str(run["id"])


def test_deleting_a_finished_run_removes_it_and_its_log(client: TestClient) -> None:
    run_id = _finished_debug_run(client)
    assert client.get(f"/runs/{run_id}/events/history").json() != []

    response = client.delete(f"/runs/{run_id}")

    assert response.status_code == 204
    assert client.get(f"/runs/{run_id}").status_code == 404
    assert client.get(f"/runs/{run_id}/events/history").status_code == 404
    assert client.get(f"/runs/{run_id}/events").status_code == 404
    assert client.get("/runs").json() == []


def test_deleting_one_run_leaves_the_others_listed(client: TestClient) -> None:
    keep = _finished_debug_run(client)
    drop = _finished_debug_run(client)

    assert client.delete(f"/runs/{drop}").status_code == 204

    assert [run["id"] for run in client.get("/runs").json()] == [keep]
    assert client.get(f"/runs/{keep}/events/history").json() != []


def test_deleting_an_unknown_run_is_404(client: TestClient) -> None:
    assert client.delete("/runs/nope").status_code == 404


def test_deleting_a_run_still_in_progress_is_409_and_says_to_cancel_it(
    client: TestClient,
) -> None:
    """A run that has not ended cannot be deleted from under its orchestrator.
    The debug run at a slow step is running for the length of this test."""
    run = client.post("/debug/fake_run", params={"step_ms": 5000}).json()

    response = client.delete(f"/runs/{run['id']}")

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert "cancel" in detail.lower()
    assert client.get(f"/runs/{run['id']}").status_code == 200


def test_deleting_a_run_keeps_the_months_spend(app_paths: AppPaths) -> None:
    """Through the API, against a run that actually charged the ledger: the
    app-wide figure `GET /budget` reports is the same before and after."""
    app = create_app(app_paths, secrets=SecretStore())
    with TestClient(app) as client:
        app.state.launcher.provider = ScriptedProvider(
            [says("Done.", call("finish", summary="nothing to do"))]
        )
        run = client.post("/runs", json={"goal": "spend a little"}).json()
        client.get(f"/runs/{run['id']}/events")  # drains to the terminal event
        before = client.get("/budget").json()
        assert before["spent_micros"] > 0

        assert client.delete(f"/runs/{run['id']}").status_code == 204

        after = client.get("/budget").json()

    assert after["spent_micros"] == before["spent_micros"]


# --- the store method behind it ---------------------------------------------


@pytest.mark.anyio
async def test_list_runs_reads_the_runs_table_not_the_event_log(store: EventStore) -> None:
    """A run with no events at all is still a run, and still listable.

    The event log is the authority on what *happened* in a run (§2); the `runs`
    table is the authority on which runs exist. A listing derived from events
    would omit a run that was created and never started: precisely the run a
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


# --- a restart -----------------------------------------------------------------


def test_a_restart_fails_the_runs_the_last_process_left_unfinished(app_paths: AppPaths) -> None:
    """The orchestrator is a task in the process that started it. When that
    process goes (a crash, or the window closing), the row stayed `running`
    forever and the dashboard said "live" about a run that would never end.
    """
    with TestClient(create_app(app_paths, secrets=SecretStore())) as first:
        # A run the previous process created and never finished. The debug run
        # is a background task in the app; a bare created row stands in for a
        # crash mid-flight, which is the case that cannot be scripted.
        created = first.post("/runs", json={"goal": "interrupted"}).json()

    with TestClient(create_app(app_paths, secrets=SecretStore())) as second:
        run = second.get(f"/runs/{created['id']}").json()
        events = second.get(f"/runs/{created['id']}/events/history").json()

    assert run["status"] == "failed"
    assert run["finished_at"] is not None
    assert events[-1]["type"] == "run.failed"
    assert "closed" in events[-1]["payload"]["reason"]
