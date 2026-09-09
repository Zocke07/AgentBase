"""Tests for the orchestration loop.

The §5 Phase 4 acceptance criterion has two clauses, and the second is the one
that is easy to fake:

1. "a two-worker run completes end to end"
2. "the full event log alone is sufficient to reconstruct exactly what happened
   without reading any other state"

A test that asserted only "some events were written" would pass against a log
that had lost half the run. So :func:`reconstruct` below reads **nothing but
the event rows** — no run row, no orchestrator object, no provider — and
rebuilds what happened. Every assertion about the run is then made against that
reconstruction rather than against live state, and `test_dropping_*` proves
each one actually depends on the events it claims to.

The reducer lives here rather than in `src/` on purpose: §5 Phase 7 owns the
real one, in TypeScript, in `RunGraph`. A Python reducer shipped now would be
building ahead, and a second implementation to keep in sync forever.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import pytest

from agentspace.budget.ledger import BudgetLedger
from agentspace.events.types import Event, EventType
from agentspace.orchestrator import execute_run
from agentspace.orchestrator.limits import RunLimits
from agentspace.orchestrator.run import Mailbox, Run, SpawnRefusedError
from agentspace.providers.base import (
    Completion,
    Message,
    TextDelta,
    TokenUsage,
    ToolCall,
    ToolSpec,
)
from agentspace.secrets import SecretStore
from agentspace.store.settings import SettingsStore

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

    from agentspace.events.store import EventStore
    from agentspace.providers.base import StreamEvent
    from agentspace.store.db import Database

pytestmark = pytest.mark.anyio


# --- the scripted provider ---------------------------------------------------


class ScriptedProvider:
    """A provider that returns a fixed sequence of completions.

    Deterministic and free, so the acceptance criterion can be asserted on
    every run of the suite. It implements the whole protocol — including
    `stream`, which is the path the orchestrator actually takes — because a
    double that implements half of one is a double that proves half of what it
    appears to.
    """

    name = "scripted"
    model = "claude-opus-5"

    def __init__(self, script: list[Completion]) -> None:
        self._script = list(script)
        self.requests: list[list[Message]] = []
        self.systems: list[str | None] = []
        self.offered_tools: list[list[str]] = []

    def _next(
        self, messages: list[Message], tools: list[ToolSpec] | None, system: str | None
    ) -> Completion:
        self.requests.append(list(messages))
        self.systems.append(system)
        self.offered_tools.append([tool.name for tool in tools or []])

        if not self._script:
            msg = "the orchestrator asked for more model calls than the script has"
            raise AssertionError(msg)
        return self._script.pop(0)

    async def complete(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        *,
        system: str | None = None,
        max_tokens: int = 4096,
    ) -> Completion:
        return self._next(messages, tools, system)

    async def stream(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        *,
        system: str | None = None,
        max_tokens: int = 4096,
    ) -> AsyncIterator[StreamEvent]:
        completion = self._next(messages, tools, system)
        for word in completion.text.split():
            yield TextDelta(word + " ")
        yield completion


def says(
    text: str = "",
    *calls: ToolCall,
    input_tokens: int = 100,
    output_tokens: int = 50,
) -> Completion:
    return Completion(
        provider="scripted",
        model="claude-opus-5",
        text=text,
        usage=TokenUsage(input_tokens=input_tokens, output_tokens=output_tokens),
        tool_calls=calls,
        stop_reason="tool_use" if calls else "end_turn",
    )


class FakeClock:
    """A monotonic clock that reads a scripted sequence, then holds.

    Holding on the last value rather than raising `StopIteration` matters: the
    number of clock reads is an implementation detail of the loop, and a test
    that broke when one was added would be testing the wrong thing.
    """

    def __init__(self, *values: float) -> None:
        self._values = list(values)
        self._last = values[-1]

    def __call__(self) -> float:
        return self._values.pop(0) if self._values else self._last


def call(tool: str, call_id: str = "call_1", /, **arguments: Any) -> ToolCall:
    """Build a tool call.

    Both parameters are positional-only: `spawn_agent` takes an argument
    literally called `name`, which would otherwise collide with this
    function's own parameter rather than landing in the call's arguments.
    """
    return ToolCall(id=call_id, name=tool, arguments=arguments)


# --- the reconstruction ------------------------------------------------------


@dataclass
class ReconstructedAgent:
    name: str
    role: str | None = None
    model: str | None = None
    steps: int = 0
    finished_reason: str | None = None
    result: str | None = None
    tool_calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    tool_errors: list[str] = field(default_factory=list)
    streamed_text: str = ""


@dataclass
class ReconstructedRun:
    goal: str | None = None
    limits: dict[str, Any] = field(default_factory=dict)
    status: str = "running"
    outcome: str | None = None
    agents: dict[str, ReconstructedAgent] = field(default_factory=dict)
    handoffs: list[tuple[str, str, str]] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    budget_events: list[str] = field(default_factory=list)

    def agent(self, name: str) -> ReconstructedAgent:
        return self.agents[name]


def reconstruct(events: list[Event]) -> ReconstructedRun:
    """Rebuild what happened from the event log and nothing else.

    Deliberately has no access to the `runs` table, the orchestrator, or the
    provider. If something a test wants to assert is not derivable here, the
    log does not contain it — which is precisely the failure the Phase 4
    acceptance criterion is about.
    """
    run = ReconstructedRun()

    for event in events:
        payload = event.payload
        agent_id = event.agent_id

        if agent_id is not None and agent_id not in run.agents:
            run.agents[agent_id] = ReconstructedAgent(name=agent_id)
        agent = run.agents[agent_id] if agent_id is not None else None

        match event.type:
            case EventType.RUN_STARTED:
                run.goal = payload.get("goal")
                run.limits = payload.get("limits", {})
            case EventType.RUN_COMPLETED:
                run.status = "completed"
                run.outcome = payload.get("summary")
            case EventType.RUN_FAILED:
                run.status = "failed"
                run.outcome = payload.get("reason")
            case EventType.AGENT_SPAWNED if agent is not None:
                agent.role = payload.get("role")
                agent.model = payload.get("model")
            case EventType.AGENT_THINKING if agent is not None:
                agent.steps = max(agent.steps, int(payload.get("step", 0)))
            case EventType.AGENT_COMPLETED if agent is not None:
                agent.finished_reason = payload.get("reason")
            case EventType.AGENT_MESSAGE if agent is not None:
                agent.result = payload.get("text")
            case EventType.AGENT_HANDOFF if agent is not None:
                run.handoffs.append(
                    (agent.name, str(payload.get("to")), str(payload.get("task")))
                )
            case EventType.LLM_TOKEN if agent is not None:
                agent.streamed_text += str(payload.get("text", ""))
            case EventType.LLM_RESPONSE:
                run.input_tokens += int(payload.get("input_tokens", 0))
                run.output_tokens += int(payload.get("output_tokens", 0))
            case EventType.TOOL_CALLED if agent is not None:
                agent.tool_calls.append(
                    (str(payload.get("tool")), dict(payload.get("args") or {}))
                )
            case EventType.TOOL_ERROR if agent is not None:
                agent.tool_errors.append(str(payload.get("error")))
            case EventType.BUDGET_EXCEEDED | EventType.BUDGET_WARNING:
                run.budget_events.append(str(event.type))
            case _:
                pass

    return run


# --- fixtures ----------------------------------------------------------------


@pytest.fixture
def settings(db: Database) -> SettingsStore:
    return SettingsStore(db)


@pytest.fixture
def ledger(db: Database, store: EventStore, settings: SettingsStore) -> BudgetLedger:
    return BudgetLedger(db, settings, store)


@pytest.fixture
def secrets() -> SecretStore:
    return SecretStore()


async def drive(
    store: EventStore,
    settings: SettingsStore,
    ledger: BudgetLedger,
    secrets: SecretStore,
    script: list[Completion],
    goal: str = "Summarise the quarterly report",
    clock: Callable[[], float] | None = None,
) -> tuple[str, ReconstructedRun]:
    """Run a scripted run to its terminal event and reconstruct it."""
    run = await store.create_run(goal=goal, origin="ui")
    await execute_run(
        store,
        settings,
        ledger,
        secrets,
        run.id,
        goal,
        provider=ScriptedProvider(script),
        clock=clock,
    )
    return run.id, reconstruct(await store.read(run.id))


TWO_WORKER_SCRIPT: list[Completion] = [
    says(
        "I will split this into research and writing.",
        call(
            "spawn_agent",
            "c1",
            name="researcher",
            role="Gathers figures",
            task="Find the Q3 revenue and churn figures",
        ),
    ),
    says(
        "Revenue up 12% QoQ; churn flat at 2.1%.",
        call("finish", "c2", result="Revenue up 12% QoQ; churn flat at 2.1%."),
    ),
    says(
        "Now the write-up.",
        call(
            "spawn_agent",
            "c3",
            name="writer",
            role="Writes the summary",
            task="Write a two-line summary from the researcher's figures",
        ),
    ),
    says(
        "Drafting.", call("finish", "c4", result="Q3 revenue rose 12% QoQ. Churn held at 2.1%.")
    ),
    says(
        "Done.",
        call("finish", "c5", result="Q3 revenue rose 12% QoQ. Churn held at 2.1%."),
    ),
]


# --- the acceptance criterion, first clause ----------------------------------


async def test_a_two_worker_run_completes_end_to_end(
    store: EventStore, settings: SettingsStore, ledger: BudgetLedger, secrets: SecretStore
) -> None:
    """§5 Phase 4, acceptance criterion, first clause."""
    run_id, rebuilt = await drive(store, settings, ledger, secrets, TWO_WORKER_SCRIPT)

    assert rebuilt.status == "completed"
    assert set(rebuilt.agents) == {"supervisor", "researcher", "writer"}
    assert rebuilt.outcome == "Q3 revenue rose 12% QoQ. Churn held at 2.1%."

    # And the run row agrees with what the log says. If these ever disagree,
    # the log is not a faithful projection and everything else here is theatre.
    row = await store.get_run(run_id)
    assert row is not None
    assert row.status == rebuilt.status


async def test_each_worker_ran_and_reported(
    store: EventStore, settings: SettingsStore, ledger: BudgetLedger, secrets: SecretStore
) -> None:
    _, rebuilt = await drive(store, settings, ledger, secrets, TWO_WORKER_SCRIPT)

    researcher = rebuilt.agent("researcher")
    assert researcher.role == "Gathers figures"
    assert researcher.finished_reason == "finished"
    assert researcher.result == "Revenue up 12% QoQ; churn flat at 2.1%."

    writer = rebuilt.agent("writer")
    assert writer.role == "Writes the summary"
    assert writer.finished_reason == "finished"
    assert writer.result == "Q3 revenue rose 12% QoQ. Churn held at 2.1%."


async def test_delegation_appears_as_handoff_events(
    store: EventStore, settings: SettingsStore, ledger: BudgetLedger, secrets: SecretStore
) -> None:
    """§5 Phase 4: "Handoffs are `agent.handoff` events"."""
    _, rebuilt = await drive(store, settings, ledger, secrets, TWO_WORKER_SCRIPT)

    assert [(sender, recipient) for sender, recipient, _ in rebuilt.handoffs] == [
        ("supervisor", "researcher"),
        ("supervisor", "writer"),
    ]
    assert rebuilt.handoffs[0][2] == "Find the Q3 revenue and churn figures"


async def test_token_usage_is_recoverable_from_the_log(
    store: EventStore, settings: SettingsStore, ledger: BudgetLedger, secrets: SecretStore
) -> None:
    """Five model calls at 100 in / 50 out each, all visible in the log."""
    _, rebuilt = await drive(store, settings, ledger, secrets, TWO_WORKER_SCRIPT)

    assert rebuilt.input_tokens == 5 * 100
    assert rebuilt.output_tokens == 5 * 50


async def test_streamed_tokens_reach_the_log(
    store: EventStore, settings: SettingsStore, ledger: BudgetLedger, secrets: SecretStore
) -> None:
    """`llm.token` is what makes the UI live rather than a progress bar."""
    _, rebuilt = await drive(store, settings, ledger, secrets, TWO_WORKER_SCRIPT)

    assert rebuilt.agent("researcher").streamed_text.strip() == (
        "Revenue up 12% QoQ; churn flat at 2.1%."
    )


async def test_the_run_starts_with_its_limits_recorded(
    store: EventStore, settings: SettingsStore, ledger: BudgetLedger, secrets: SecretStore
) -> None:
    """A replay has to be able to say what rules the run was held to."""
    await settings.update({"max_steps_per_agent": 7})
    _, rebuilt = await drive(store, settings, ledger, secrets, TWO_WORKER_SCRIPT)

    assert rebuilt.limits["max_steps_per_agent"] == 7
    assert rebuilt.goal == "Summarise the quarterly report"


# --- the acceptance criterion, second clause ---------------------------------
#
# Each of these drops one kind of event from the log and re-runs the same
# reconstruction. If the assertion above still passed, it was never reading
# that event, and the "sufficient to reconstruct" claim was resting on
# something other than the log.


async def test_dropping_agent_spawned_loses_who_the_agents_were(
    store: EventStore, settings: SettingsStore, ledger: BudgetLedger, secrets: SecretStore
) -> None:
    run_id, _ = await drive(store, settings, ledger, secrets, TWO_WORKER_SCRIPT)
    events = await store.read(run_id)

    without = reconstruct([e for e in events if e.type is not EventType.AGENT_SPAWNED])

    assert without.agent("researcher").role is None
    assert without.agent("researcher").model is None


async def test_dropping_agent_message_loses_what_the_workers_produced(
    store: EventStore, settings: SettingsStore, ledger: BudgetLedger, secrets: SecretStore
) -> None:
    run_id, _ = await drive(store, settings, ledger, secrets, TWO_WORKER_SCRIPT)
    events = await store.read(run_id)

    without = reconstruct([e for e in events if e.type is not EventType.AGENT_MESSAGE])

    assert without.agent("researcher").result is None
    assert without.agent("writer").result is None


async def test_dropping_handoffs_loses_the_shape_of_the_run(
    store: EventStore, settings: SettingsStore, ledger: BudgetLedger, secrets: SecretStore
) -> None:
    run_id, _ = await drive(store, settings, ledger, secrets, TWO_WORKER_SCRIPT)
    events = await store.read(run_id)

    without = reconstruct([e for e in events if e.type is not EventType.AGENT_HANDOFF])

    assert without.handoffs == []


async def test_dropping_llm_response_loses_the_cost(
    store: EventStore, settings: SettingsStore, ledger: BudgetLedger, secrets: SecretStore
) -> None:
    run_id, _ = await drive(store, settings, ledger, secrets, TWO_WORKER_SCRIPT)
    events = await store.read(run_id)

    without = reconstruct([e for e in events if e.type is not EventType.LLM_RESPONSE])

    assert without.input_tokens == 0
    assert without.output_tokens == 0


async def test_dropping_the_terminal_event_leaves_the_run_unfinished(
    store: EventStore, settings: SettingsStore, ledger: BudgetLedger, secrets: SecretStore
) -> None:
    """The one that matters most: without it a replay cannot say the run ended,
    and the SSE stream has nothing to close on."""
    run_id, _ = await drive(store, settings, ledger, secrets, TWO_WORKER_SCRIPT)
    events = await store.read(run_id)

    without = reconstruct([e for e in events if e.type is not EventType.RUN_COMPLETED])

    assert without.status == "running"
    assert without.outcome is None


async def test_the_mailbox_reads_the_log_not_a_variable(store: EventStore) -> None:
    """The supervisor learns a worker's result by reading SQLite.

    Asserted directly against `Mailbox`, because the property is what makes the
    log load-bearing rather than decorative: an `agent.message` that was never
    appended is a result that does not exist.
    """
    run_row = await store.create_run(goal="mailbox")
    run = Run(store=store, id=run_row.id, goal="mailbox", limits=RunLimits())
    mailbox = Mailbox(run)

    with pytest.raises(LookupError, match="never appended"):
        await mailbox.collect(sender="researcher", recipient="supervisor")

    await mailbox.deliver("researcher", "supervisor", "the figures")
    assert await mailbox.collect("researcher", "supervisor") == "the figures"


# --- limits ------------------------------------------------------------------


async def test_an_agent_that_never_finishes_stops_at_the_step_limit(
    store: EventStore, settings: SettingsStore, ledger: BudgetLedger, secrets: SecretStore
) -> None:
    """§4 has no `agent.failed`, so the step limit completes the agent with a
    reason rather than failing it."""
    await settings.update({"max_steps_per_agent": 3})
    script = [says("Thinking about it.") for _ in range(3)]

    _, rebuilt = await drive(store, settings, ledger, secrets, script)

    supervisor = rebuilt.agent("supervisor")
    assert supervisor.finished_reason == "max_steps"
    assert supervisor.steps == 3
    assert rebuilt.status == "completed"


async def test_a_run_that_outlives_its_deadline_fails(
    store: EventStore, settings: SettingsStore, ledger: BudgetLedger, secrets: SecretStore
) -> None:
    """The wall-clock limit, driven by an injected clock rather than by waiting.

    The clock reads 0 when the run starts and 999 at the supervisor's first
    deadline check, so the run is already over its 30s limit before a single
    model call goes out.
    """
    await settings.update({"max_run_seconds": 30})

    _, rebuilt = await drive(
        store, settings, ledger, secrets, TWO_WORKER_SCRIPT, clock=FakeClock(0.0, 999.0)
    )

    assert rebuilt.status == "failed"
    assert rebuilt.outcome is not None
    assert "time limit of 30s" in rebuilt.outcome
    # Stopped before doing any work: no worker, and no model call billed.
    assert set(rebuilt.agents) == {"supervisor"}
    assert rebuilt.input_tokens == 0


async def test_a_spawn_past_the_agent_limit_is_refused_without_killing_the_run(
    store: EventStore, settings: SettingsStore, ledger: BudgetLedger, secrets: SecretStore
) -> None:
    """The supervisor is told and carries on with the workers it has."""
    await settings.update({"max_agents_per_run": 2})  # supervisor + one worker
    script = [
        says("First.", call("spawn_agent", "c1", name="researcher", role="R", task="t1")),
        says("Done.", call("finish", "c2", result="figures")),
        says("Second.", call("spawn_agent", "c3", name="writer", role="W", task="t2")),
        says("Wrapping up.", call("finish", "c4", result="only the researcher ran")),
    ]

    _, rebuilt = await drive(store, settings, ledger, secrets, script)

    assert rebuilt.status == "completed"
    assert set(rebuilt.agents) == {"supervisor", "researcher"}
    errors = rebuilt.agent("supervisor").tool_errors
    assert any("maximum of 2 agents" in error for error in errors)


def test_registering_past_the_limit_refuses_rather_than_truncates(
    store: EventStore,
) -> None:
    """`register_agent` is the single place the agent cap is enforced."""
    run = Run(store=store, id="r", goal="g", limits=RunLimits(max_agents_per_run=2))

    assert run.register_agent("supervisor") == "supervisor"
    assert run.register_agent("researcher") == "researcher"

    with pytest.raises(SpawnRefusedError):
        run.register_agent("writer")


def test_a_duplicate_agent_name_is_made_unique(store: EventStore) -> None:
    """Two agents sharing an `agent_id` would merge into one node on replay."""
    run = Run(store=store, id="r", goal="g", limits=RunLimits())

    assert run.register_agent("researcher") == "researcher"
    assert run.register_agent("researcher") == "researcher-2"
    assert run.register_agent("researcher") == "researcher-3"


# --- the budget, now reachable through a run ---------------------------------


async def test_a_run_over_the_cap_fails_with_the_reason_in_the_log(
    store: EventStore, settings: SettingsStore, ledger: BudgetLedger, secrets: SecretStore
) -> None:
    """Phase 3 could only assert this at the wrapper. Now it is observable as a
    run outcome, which is how a user actually meets it."""
    await settings.update({"monthly_cap_micros": 1})

    _, rebuilt = await drive(store, settings, ledger, secrets, TWO_WORKER_SCRIPT)

    assert rebuilt.status == "failed"
    assert rebuilt.outcome is not None
    assert "monthly budget" in rebuilt.outcome
    assert "budget.exceeded" in rebuilt.budget_events
    # Nothing ran: the refusal happened before the first model call.
    assert rebuilt.input_tokens == 0


async def test_an_unknown_tool_name_is_reported_not_fatal(
    store: EventStore, settings: SettingsStore, ledger: BudgetLedger, secrets: SecretStore
) -> None:
    """A model naming a tool that does not exist gets told what it may use."""
    script = [
        says("Trying.", call("read_file", "c1", path="q3.md")),
        says("Fine.", call("finish", "c2", result="did it without tools")),
    ]

    _, rebuilt = await drive(store, settings, ledger, secrets, script)

    assert rebuilt.status == "completed"
    assert "read_file" in rebuilt.agent("supervisor").tool_errors[0]


async def test_a_worker_can_hand_off_and_the_event_is_recorded(
    store: EventStore, settings: SettingsStore, ledger: BudgetLedger, secrets: SecretStore
) -> None:
    script = [
        says("Delegating.", call("spawn_agent", "c1", name="researcher", role="R", task="t1")),
        says("Not my job.", call("handoff", "c2", to="writer", task="write it up")),
        says("Understood.", call("finish", "c3", result="the researcher passed it on")),
    ]

    _, rebuilt = await drive(store, settings, ledger, secrets, script)

    assert rebuilt.status == "completed"
    assert rebuilt.agent("researcher").finished_reason == "handoff"
    assert ("researcher", "writer", "write it up") in rebuilt.handoffs


# --- what the model is actually offered --------------------------------------


async def test_a_worker_is_not_offered_spawn_agent(
    store: EventStore, settings: SettingsStore, ledger: BudgetLedger, secrets: SecretStore
) -> None:
    """A worker that could spawn could widen the run's shape from inside its
    own turn, and the agent cap would stop describing what a run can do."""
    provider = ScriptedProvider(TWO_WORKER_SCRIPT)
    run = await store.create_run(goal="g")

    await execute_run(store, settings, ledger, secrets, run.id, "g", provider=provider)

    # Call 0 is the supervisor, call 1 the first worker.
    assert "spawn_agent" in provider.offered_tools[0]
    assert "spawn_agent" not in provider.offered_tools[1]
    assert "finish" in provider.offered_tools[1]
