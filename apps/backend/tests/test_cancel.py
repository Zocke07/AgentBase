"""Cancelling a run: cooperative, at the deadline check before each model call,
and releasing an agent blocked on the approval gate.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from agentspace.events.types import EventType
from agentspace.main import create_app
from agentspace.orchestrator import execute_run
from agentspace.providers.base import Completion
from agentspace.secrets import SecretStore
from support import ScriptedProvider, call, reconstruct, says, tool_runtime

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable
    from pathlib import Path

    from agentspace.budget.ledger import BudgetLedger
    from agentspace.config import AppPaths
    from agentspace.events.store import EventStore
    from agentspace.orchestrator.run import Run
    from agentspace.providers.base import Message, StreamEvent, ToolSpec
    from agentspace.store.agents import AgentDefStore
    from agentspace.store.db import Database
    from agentspace.store.settings import SettingsStore

pytestmark = pytest.mark.anyio


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """The sandbox root, as `test_approval_gate.py` builds it."""
    root = tmp_path / "workspace"
    root.mkdir(exist_ok=True)
    return root


async def _until(condition: Callable[[], bool]) -> None:
    """Yield to the loop until a condition it will make true holds.

    The condition is another coroutine's internal state (the gate having a
    waiter registered), and the service offers no event to await for it; one
    would be test-only surface. Yielding is cheap, and `wait_for` bounds it.
    """
    while not condition():  # noqa: ASYNC110
        await asyncio.sleep(0)


class CancelsMidway(ScriptedProvider):
    """A scripted provider that cancels the run from inside its Nth call.

    The cancel lands while a model call is in flight, which is where a real
    one lands (from an HTTP handler, at an arbitrary moment), and the run
    must notice at its next check rather than tear the call apart.
    """

    def __init__(self, script: list[Completion], *, on_call: int, live: dict[str, Run]) -> None:
        super().__init__(script)
        self._on_call = on_call
        self._live = live
        self.calls = 0

    def _next(
        self, messages: list[Message], tools: list[ToolSpec] | None, system: str | None
    ) -> Completion:
        self.calls += 1
        if self.calls == self._on_call:
            for run in self._live.values():
                run.request_cancel("Cancelled by the user.")
        return super()._next(messages, tools, system)


async def test_a_cancelled_run_ends_with_run_cancelled_and_nothing_after_it(
    store: EventStore,
    settings: SettingsStore,
    agents: AgentDefStore,
    ledger: BudgetLedger,
    secrets: SecretStore,
) -> None:
    live: dict[str, Run] = {}
    provider = CancelsMidway(
        [
            says("Delegating.", call("spawn_agent", "c1", agent="researcher", task="Look")),
            says("Found it.", call("finish", "c2", result="figures")),
            says("Never reached.", call("finish", "c3", result="unreachable")),
        ],
        on_call=2,
        live=live,
    )
    run = await store.create_run(goal="Summarise", origin="ui")

    await execute_run(
        store,
        settings,
        agents,
        ledger,
        secrets,
        run.id,
        "Summarise",
        provider=provider,
        live=live,
    )

    events = await store.read(run.id)
    rebuilt = reconstruct(events)
    assert rebuilt.status == "cancelled"
    assert rebuilt.outcome == "Cancelled by the user."
    assert events[-1].type is EventType.RUN_CANCELLED
    # The call in flight finished; the one after it never went out.
    assert provider.calls == 2
    row = await store.get_run(run.id)
    assert row is not None
    assert row.status == "cancelled"
    assert row.finished_at is not None
    # The run is no longer live once it has ended.
    assert live == {}


async def test_cancelling_releases_an_agent_blocked_on_the_gate(
    store: EventStore,
    settings: SettingsStore,
    agents: AgentDefStore,
    ledger: BudgetLedger,
    secrets: SecretStore,
    db: Database,
    workspace: Path,
) -> None:
    """The gate borrows the run's wall clock, so without this a cancel would
    take effect only when the approval expired: ten minutes by default."""
    await settings.update({"max_run_seconds": 600})
    runtime, service = tool_runtime(store, db, workspace)
    await agents.create(
        {
            "name": "filewriter",
            "role": "Writes files",
            "system_prompt": "Write the file.",
            "allowed_tools": ["write_file"],
        }
    )
    live: dict[str, Run] = {}
    provider = ScriptedProvider(
        [
            says("Delegating.", call("spawn_agent", "s1", agent="filewriter", task="Save it")),
            says("Writing.", call("write_file", "w1", path="notes.txt", content="hi")),
            says("Never reached.", call("finish", "w2", result="unreachable")),
        ]
    )
    run = await store.create_run(goal="Save the report", origin="ui")

    driving = asyncio.create_task(
        execute_run(
            store,
            settings,
            agents,
            ledger,
            secrets,
            run.id,
            "Save the report",
            provider=provider,
            runtime=runtime,
            live=live,
        )
    )
    # Wait for the worker to be blocked on the gate.
    await asyncio.wait_for(_until(lambda: service.pending_count > 0), timeout=5)

    live[run.id].request_cancel("Cancelled by the user.")
    await service.release_run(run.id)
    await asyncio.wait_for(driving, timeout=5)

    events = await store.read(run.id)
    types = [event.type for event in events]
    assert types[-1] is EventType.RUN_CANCELLED
    assert EventType.TOOL_DENIED in types
    denial = next(event for event in events if event.type is EventType.TOOL_DENIED)
    assert "cancelled" in str(denial.payload["reason"]).lower()
    assert await service.store.list_pending(run.id) == []
    assert not (workspace / "notes.txt").exists()


# --- the endpoint -------------------------------------------------------------


def test_cancelling_an_unknown_run_is_404(app_paths: AppPaths) -> None:
    with TestClient(create_app(app_paths, secrets=SecretStore())) as client:
        assert client.post("/runs/nope/cancel").status_code == 404


def test_cancelling_a_finished_run_is_409(app_paths: AppPaths) -> None:
    with TestClient(create_app(app_paths, secrets=SecretStore())) as client:
        run = client.post("/debug/fake_run?step_ms=0").json()
        client.get(f"/runs/{run['id']}/events")  # drains to the terminal event

        response = client.post(f"/runs/{run['id']}/cancel")

    assert response.status_code == 409
    assert "completed" in response.json()["detail"]


class SlowScripted(ScriptedProvider):
    """Each call takes a moment, so a cancel from another thread lands mid-run."""

    async def stream(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        *,
        system: str | None = None,
        max_tokens: int = 4096,
    ) -> AsyncIterator[StreamEvent]:
        await asyncio.sleep(0.05)
        async for item in super().stream(messages, tools, system=system, max_tokens=max_tokens):
            yield item


def test_cancelling_a_live_run_is_accepted_and_ends_it(app_paths: AppPaths) -> None:
    """Through the API, against a run that would otherwise go on for twenty
    steps: 202 now, `run.cancelled` on the stream, the row cancelled after."""
    app = create_app(app_paths, secrets=SecretStore())
    with TestClient(app) as client:
        # A supervisor that thinks and never finishes; the step limit would end
        # it in about a second, and the cancel lands well before that.
        app.state.launcher.provider = SlowScripted([says("Still thinking.")] * 40)

        run = client.post("/runs", json={"goal": "cancel me"}).json()
        response = client.post(f"/runs/{run['id']}/cancel")
        assert response.status_code == 202, response.text
        assert response.json()["id"] == run["id"]

        frames = client.get(f"/runs/{run['id']}/events").text
        final = client.get(f"/runs/{run['id']}").json()

    assert '"type":"run.cancelled"' in frames
    assert final["status"] == "cancelled"
    # Idempotent from the user's side: a second cancel of a finished run is 409.
