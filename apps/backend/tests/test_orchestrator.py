"""Tests for the orchestration loop.

§5 Phase 4's second clause, "the full event log alone is sufficient to
reconstruct exactly what happened", is the one that is easy to fake, so every
assertion goes through `reconstruct` in `tests/support.py`, which reads only
event rows, and `test_dropping_*` proves each assertion depends on the events
it claims to. Workers are rows of `agent_defs` selected by name; the scripts
spawn the seeded `researcher` and `writer`.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from agentbase.api.stream import run_stream
from agentbase.events.bus import DEFAULT_QUEUE_SIZE, EventBus
from agentbase.events.types import EventType
from agentbase.orchestrator import execute_run
from agentbase.orchestrator.limits import RunLimits
from agentbase.orchestrator.run import Mailbox, Run, SpawnRefusedError
from agentbase.providers.base import Completion
from support import FakeClock, ReconstructedRun, ScriptedProvider, call, reconstruct, says

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

    from agentbase.budget.ledger import BudgetLedger
    from agentbase.events.store import EventStore
    from agentbase.secrets import SecretStore
    from agentbase.store.agents import AgentDefStore
    from agentbase.store.db import Database
    from agentbase.store.settings import SettingsStore

pytestmark = pytest.mark.anyio

#: The roles migration 003 seeds. Asserted rather than inlined so that a change
#: to a built-in's wording fails here loudly instead of silently weakening the
#: claim that a worker's role comes from its definition.
RESEARCHER_ROLE = "Gathers facts and figures, and reports them without embellishment"
WRITER_ROLE = "Turns findings into clear prose for the reader"


# --- driving a run -----------------------------------------------------------
#
# The `store`, `settings`, `agents`, `ledger` and `secrets` fixtures live in
# `conftest.py`: Phase 5 added two more modules that drive runs, and three
# copies of the same fixture is three places to forget when a store grows a
# dependency.


async def drive(
    store: EventStore,
    settings: SettingsStore,
    agents: AgentDefStore,
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
        agents,
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
            agent="researcher",
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
            agent="writer",
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
    store: EventStore,
    settings: SettingsStore,
    agents: AgentDefStore,
    ledger: BudgetLedger,
    secrets: SecretStore,
) -> None:
    """§5 Phase 4, acceptance criterion, first clause."""
    run_id, rebuilt = await drive(store, settings, agents, ledger, secrets, TWO_WORKER_SCRIPT)

    assert rebuilt.status == "completed"
    assert set(rebuilt.agents) == {"supervisor", "researcher", "writer"}
    assert rebuilt.outcome == "Q3 revenue rose 12% QoQ. Churn held at 2.1%."

    # And the run row agrees with what the log says. If these ever disagree,
    # the log is not a faithful projection and everything else here is theatre.
    row = await store.get_run(run_id)
    assert row is not None
    assert row.status == rebuilt.status


async def test_each_worker_ran_and_reported(
    store: EventStore,
    settings: SettingsStore,
    agents: AgentDefStore,
    ledger: BudgetLedger,
    secrets: SecretStore,
) -> None:
    _, rebuilt = await drive(store, settings, agents, ledger, secrets, TWO_WORKER_SCRIPT)

    researcher = rebuilt.agent("researcher")
    # The role came from the `agent_defs` row, not from anything the model
    # said: §5 Phase 5's whole point.
    assert researcher.role == RESEARCHER_ROLE
    assert researcher.definition_name == "researcher"
    assert researcher.finished_reason == "finished"
    assert researcher.result == "Revenue up 12% QoQ; churn flat at 2.1%."

    writer = rebuilt.agent("writer")
    assert writer.role == WRITER_ROLE
    assert writer.definition_name == "writer"
    assert writer.finished_reason == "finished"
    assert writer.result == "Q3 revenue rose 12% QoQ. Churn held at 2.1%."


async def test_delegation_appears_as_handoff_events(
    store: EventStore,
    settings: SettingsStore,
    agents: AgentDefStore,
    ledger: BudgetLedger,
    secrets: SecretStore,
) -> None:
    """§5 Phase 4: "Handoffs are `agent.handoff` events"."""
    _, rebuilt = await drive(store, settings, agents, ledger, secrets, TWO_WORKER_SCRIPT)

    assert [(sender, recipient) for sender, recipient, _ in rebuilt.handoffs] == [
        ("supervisor", "researcher"),
        ("supervisor", "writer"),
    ]
    assert rebuilt.handoffs[0][2] == "Find the Q3 revenue and churn figures"


async def test_token_usage_is_recoverable_from_the_log(
    store: EventStore,
    settings: SettingsStore,
    agents: AgentDefStore,
    ledger: BudgetLedger,
    secrets: SecretStore,
) -> None:
    """Five model calls at 100 in / 50 out each, all visible in the log."""
    _, rebuilt = await drive(store, settings, agents, ledger, secrets, TWO_WORKER_SCRIPT)

    assert rebuilt.input_tokens == 5 * 100
    assert rebuilt.output_tokens == 5 * 50


async def test_the_cost_of_each_model_call_is_in_the_log(
    store: EventStore,
    settings: SettingsStore,
    agents: AgentDefStore,
    ledger: BudgetLedger,
    secrets: SecretStore,
    db: Database,
) -> None:
    """What a run cost was in the `spend` table and nowhere a person could see
    it: `llm.response` carried tokens and not money. The budget wrapper knows
    the figure the moment it records it, so the event carries it too, and the
    log's total is the ledger's total for the run."""
    run_id, rebuilt = await drive(store, settings, agents, ledger, secrets, TWO_WORKER_SCRIPT)

    costs = [
        event.payload["cost_micros"]
        for event in await store.read(run_id)
        if event.type is EventType.LLM_RESPONSE
    ]
    assert len(costs) == 5
    assert all(isinstance(cost, int) and cost > 0 for cost in costs)

    with db.read() as connection:
        row = connection.execute(
            "SELECT SUM(cost_micros) AS total FROM spend WHERE run_id = ?", (run_id,)
        ).fetchone()
    assert sum(costs) == row["total"]
    assert rebuilt.cost_micros == sum(costs)


async def test_streamed_tokens_reach_the_log(
    store: EventStore,
    settings: SettingsStore,
    agents: AgentDefStore,
    ledger: BudgetLedger,
    secrets: SecretStore,
) -> None:
    """`llm.token` is what makes the UI live rather than a progress bar."""
    _, rebuilt = await drive(store, settings, agents, ledger, secrets, TWO_WORKER_SCRIPT)

    assert rebuilt.agent("researcher").streamed_text.strip() == (
        "Revenue up 12% QoQ; churn flat at 2.1%."
    )


async def test_the_models_reasoning_reaches_the_log_beside_its_answer(
    store: EventStore,
    settings: SettingsStore,
    agents: AgentDefStore,
    ledger: BudgetLedger,
    secrets: SecretStore,
) -> None:
    """A model that reasons at length and answers with nothing used to leave
    a log that said it produced nothing: Phase 5 watched `qwen3:4b` do it
    five times running. `llm.response` carries `thinking` now: `None` when
    the provider exposed no reasoning, the text when it did, so a replay can
    tell "said nothing" from "thought, then said nothing"."""
    script = [
        says("", thinking="The goal is done already; I should finish."),
        says("Done.", call("finish", summary="nothing to do")),
    ]
    run_id, _ = await drive(store, settings, agents, ledger, secrets, script)

    responses = [
        event.payload
        for event in await store.read(run_id)
        if event.type is EventType.LLM_RESPONSE
    ]

    assert [r["thinking"] for r in responses] == [
        "The goal is done already; I should finish.",
        None,
    ]
    assert responses[0]["text"] == ""


async def test_the_run_starts_with_its_limits_recorded(
    store: EventStore,
    settings: SettingsStore,
    agents: AgentDefStore,
    ledger: BudgetLedger,
    secrets: SecretStore,
) -> None:
    """A replay has to be able to say what rules the run was held to."""
    await settings.update({"max_steps_per_agent": 7})
    _, rebuilt = await drive(store, settings, agents, ledger, secrets, TWO_WORKER_SCRIPT)

    assert rebuilt.limits["max_steps_per_agent"] == 7
    assert rebuilt.goal == "Summarise the quarterly report"


# --- the acceptance criterion, second clause ---------------------------------
#
# Each of these drops one kind of event from the log and re-runs the same
# reconstruction. If the assertion above still passed, it was never reading
# that event, and the "sufficient to reconstruct" claim was resting on
# something other than the log.


async def test_dropping_agent_spawned_loses_who_the_agents_were(
    store: EventStore,
    settings: SettingsStore,
    agents: AgentDefStore,
    ledger: BudgetLedger,
    secrets: SecretStore,
) -> None:
    run_id, _ = await drive(store, settings, agents, ledger, secrets, TWO_WORKER_SCRIPT)
    events = await store.read(run_id)

    without = reconstruct([e for e in events if e.type is not EventType.AGENT_SPAWNED])

    assert without.agent("researcher").role is None
    assert without.agent("researcher").model is None


async def test_dropping_agent_message_loses_what_the_workers_produced(
    store: EventStore,
    settings: SettingsStore,
    agents: AgentDefStore,
    ledger: BudgetLedger,
    secrets: SecretStore,
) -> None:
    run_id, _ = await drive(store, settings, agents, ledger, secrets, TWO_WORKER_SCRIPT)
    events = await store.read(run_id)

    without = reconstruct([e for e in events if e.type is not EventType.AGENT_MESSAGE])

    assert without.agent("researcher").result is None
    assert without.agent("writer").result is None


async def test_dropping_handoffs_loses_the_shape_of_the_run(
    store: EventStore,
    settings: SettingsStore,
    agents: AgentDefStore,
    ledger: BudgetLedger,
    secrets: SecretStore,
) -> None:
    run_id, _ = await drive(store, settings, agents, ledger, secrets, TWO_WORKER_SCRIPT)
    events = await store.read(run_id)

    without = reconstruct([e for e in events if e.type is not EventType.AGENT_HANDOFF])

    assert without.handoffs == []


async def test_dropping_llm_response_loses_the_cost(
    store: EventStore,
    settings: SettingsStore,
    agents: AgentDefStore,
    ledger: BudgetLedger,
    secrets: SecretStore,
) -> None:
    run_id, _ = await drive(store, settings, agents, ledger, secrets, TWO_WORKER_SCRIPT)
    events = await store.read(run_id)

    without = reconstruct([e for e in events if e.type is not EventType.LLM_RESPONSE])

    assert without.input_tokens == 0
    assert without.output_tokens == 0


async def test_dropping_the_terminal_event_leaves_the_run_unfinished(
    store: EventStore,
    settings: SettingsStore,
    agents: AgentDefStore,
    ledger: BudgetLedger,
    secrets: SecretStore,
) -> None:
    """The one that matters most: without it a replay cannot say the run ended,
    and the SSE stream has nothing to close on."""
    run_id, _ = await drive(store, settings, agents, ledger, secrets, TWO_WORKER_SCRIPT)
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
    store: EventStore,
    settings: SettingsStore,
    agents: AgentDefStore,
    ledger: BudgetLedger,
    secrets: SecretStore,
) -> None:
    """§4 has no `agent.failed`, so the step limit completes the *agent* with a
    reason rather than failing it."""
    await settings.update({"max_steps_per_agent": 3})
    script = [says("Thinking about it.") for _ in range(3)]

    _, rebuilt = await drive(store, settings, agents, ledger, secrets, script)

    supervisor = rebuilt.agent("supervisor")
    assert supervisor.finished_reason == "max_steps"
    assert supervisor.steps == 3


async def test_a_supervisor_that_runs_out_of_steps_fails_the_run(
    store: EventStore,
    settings: SettingsStore,
    agents: AgentDefStore,
    ledger: BudgetLedger,
    secrets: SecretStore,
) -> None:
    """The agent completing is not the run succeeding.

    Found by running a local model, which hit the agent cap twice and then ran
    out of steps. The run was reported `completed` with the summary
    "supervisor stopped after 4 steps with no result": a terminal event that
    says the run worked when it did not, which is exactly the drift between the
    log and reality that §2 exists to prevent. A supervisor that never called
    `finish` did not answer the goal, whatever its workers managed.
    """
    await settings.update({"max_steps_per_agent": 3})
    script = [says("Thinking about it.") for _ in range(3)]

    _, rebuilt = await drive(store, settings, agents, ledger, secrets, script)

    assert rebuilt.status == "failed"
    assert rebuilt.outcome is not None
    assert "without finishing" in rebuilt.outcome
    assert "3 steps" in rebuilt.outcome


async def test_a_worker_hitting_the_step_limit_does_not_fail_the_run(
    store: EventStore,
    settings: SettingsStore,
    agents: AgentDefStore,
    ledger: BudgetLedger,
    secrets: SecretStore,
) -> None:
    """The distinction the previous test turns on.

    A worker running out of steps is a subtask that went badly; the supervisor
    still sees its partial result and can finish. Only the supervisor giving up
    means the run gave up.
    """
    await settings.update({"max_steps_per_agent": 3})
    script = [
        says("Delegating.", call("spawn_agent", "c1", agent="researcher", task="t")),
        says("Working."),
        says("Still working."),
        says("Nearly."),
        says("I have enough.", call("finish", "c2", result="finished despite a stuck worker")),
    ]

    _, rebuilt = await drive(store, settings, agents, ledger, secrets, script)

    assert rebuilt.agent("researcher").finished_reason == "max_steps"
    assert rebuilt.status == "completed"
    assert rebuilt.outcome == "finished despite a stuck worker"


async def test_a_cut_off_answer_is_not_run_as_a_broken_call(
    store: EventStore,
    settings: SettingsStore,
    agents: AgentDefStore,
    ledger: BudgetLedger,
    secrets: SecretStore,
) -> None:
    """A model that hit the output limit mid call sent half a call. Seen on
    2026-09-19: the arguments parsed to nothing, the tool said "needs a
    'path'", and the model retried the same oversized write at 68k tokens of
    context, eight times. Now the call is not run, the log says why, and the
    model is told to write less at a time."""
    script = [
        says("Delegating.", call("spawn_agent", "c1", agent="researcher", task="t")),
        says("Writing everything.", call("write_file", "w1"), stop_reason="max_tokens"),
        says("Smaller.", call("finish", "w2", result="wrote it in parts")),
        says("Done.", call("finish", "c2", result="ok")),
    ]

    _, rebuilt = await drive(store, settings, agents, ledger, secrets, script)

    researcher = rebuilt.agent("researcher")
    assert researcher.finished_reason == "finished"
    assert researcher.tool_errors == [
        "write_file was not run: the answer was cut off at the output limit of 16384 "
        "tokens before the call was complete."
    ]
    assert [name for name, _ in researcher.tool_calls] == ["finish"]


async def test_an_agent_that_fails_the_same_way_three_times_is_stopped(
    store: EventStore,
    settings: SettingsStore,
    agents: AgentDefStore,
    ledger: BudgetLedger,
    secrets: SecretStore,
) -> None:
    """The same failure again is a model that has stopped learning from the
    reply; each retry costs a full context window. Three in a row ends the
    agent with a reason the supervisor can act on, well short of the step
    limit, and a different failure in between starts the count over."""
    await settings.update({"max_steps_per_agent": 12})
    script = [
        says("Delegating.", call("spawn_agent", "c1", agent="researcher", task="t")),
        says("Trying.", call("write_file", "w1", content="no path")),
        says("Trying.", call("read_file", "w2")),
        says("Trying.", call("write_file", "w3", content="no path")),
        says("Trying.", call("write_file", "w4", content="no path")),
        says("Trying.", call("write_file", "w5", content="no path")),
        says("Would go on.", call("write_file", "w6", content="no path")),
        says("Done.", call("finish", "c2", result="gave up on the researcher")),
    ]

    _, rebuilt = await drive(store, settings, agents, ledger, secrets, script)

    researcher = rebuilt.agent("researcher")
    assert researcher.finished_reason == "stuck"
    # The researcher may not write, so each write is a refusal, the same one
    # every time. Four were refused, but the read between the first and the
    # second started the count over; the third consecutive refusal stopped
    # the agent, so the fifth write never happened.
    assert researcher.denied_tools == ["write_file"] * 4
    assert len(researcher.tool_errors) == 1
    assert rebuilt.status == "completed"
    assert rebuilt.outcome == "gave up on the researcher"


async def test_an_agent_that_repeats_the_identical_call_is_stopped(
    store: EventStore,
    settings: SettingsStore,
    agents: AgentDefStore,
    ledger: BudgetLedger,
    secrets: SecretStore,
) -> None:
    """A call that succeeds and is made again with the same arguments is a
    loop as surely as one that fails: the third identical one stops the agent."""
    await settings.update({"max_steps_per_agent": 12})
    script = [
        says("Delegating.", call("spawn_agent", "c1", agent="researcher", task="t")),
        says("Looking.", call("finish", "w1", result="first look")),
        says("Delegating again.", call("spawn_agent", "c2", agent="researcher", task="t")),
        says("Looking.", call("finish", "w2", result="second look")),
        says("And again.", call("spawn_agent", "c3", agent="researcher", task="t")),
        says("Looking.", call("finish", "w3", result="third look")),
        says("Would go on.", call("spawn_agent", "c4", agent="researcher", task="t")),
    ]

    _, rebuilt = await drive(store, settings, agents, ledger, secrets, script)

    assert rebuilt.agent("supervisor").finished_reason == "stuck"
    # The supervisor giving up is the run giving up, as with its step limit.
    assert rebuilt.status == "failed"
    assert "the same call with the same arguments" in (rebuilt.outcome or "")


async def test_a_run_that_spends_its_cost_limit_fails(
    store: EventStore,
    settings: SettingsStore,
    agents: AgentDefStore,
    ledger: BudgetLedger,
    secrets: SecretStore,
) -> None:
    """The per-run ceiling, checked from the ledger before each model call
    like the deadline: a run that has spent it stops where it stands, and the
    reason names the figures. The monthly cap is untouched by this."""
    await settings.update({"max_run_cost_micros": 4_000_000})
    script = [
        says("Delegating.", call("spawn_agent", "c1", agent="researcher", task="t")),
        # A million input tokens of claude-opus-5: $5.00, past the $4.00 ceiling.
        says(
            "Reading everything.", call("read_file", "w1", path="a.md"), input_tokens=1_000_000
        ),
        says("Would go on.", call("finish", "w2", result="never reached")),
        says("Would finish.", call("finish", "c2", result="never reached")),
    ]

    _, rebuilt = await drive(store, settings, agents, ledger, secrets, script)

    assert rebuilt.status == "failed"
    assert "cost limit of $4.00" in (rebuilt.outcome or "")
    assert "spent $5.00" in (rebuilt.outcome or "")


async def test_a_cost_limit_of_zero_is_no_ceiling(
    store: EventStore,
    settings: SettingsStore,
    agents: AgentDefStore,
    ledger: BudgetLedger,
    secrets: SecretStore,
) -> None:
    await settings.update({"max_run_cost_micros": 0})
    script = [
        says("Delegating.", call("spawn_agent", "c1", agent="researcher", task="t")),
        says("Reading.", call("finish", "w1", result="read"), input_tokens=1_000_000),
        says("Done.", call("finish", "c2", result="ok"), input_tokens=1_000_000),
    ]

    _, rebuilt = await drive(store, settings, agents, ledger, secrets, script)

    assert rebuilt.status == "completed"


async def test_a_run_that_outlives_its_deadline_fails(
    store: EventStore,
    settings: SettingsStore,
    agents: AgentDefStore,
    ledger: BudgetLedger,
    secrets: SecretStore,
) -> None:
    """The wall-clock limit, driven by an injected clock rather than by waiting.

    The clock reads 0 when the run starts and 999 at the supervisor's first
    deadline check, so the run is already over its 30s limit before a single
    model call goes out.
    """
    await settings.update({"max_run_seconds": 30})

    _, rebuilt = await drive(
        store, settings, agents, ledger, secrets, TWO_WORKER_SCRIPT, clock=FakeClock(0.0, 999.0)
    )

    assert rebuilt.status == "failed"
    assert rebuilt.outcome is not None
    assert "time limit of 30s" in rebuilt.outcome
    # Stopped before doing any work: no worker, and no model call billed.
    assert set(rebuilt.agents) == {"supervisor"}
    assert rebuilt.input_tokens == 0


async def test_a_spawn_past_the_agent_limit_is_refused_without_killing_the_run(
    store: EventStore,
    settings: SettingsStore,
    agents: AgentDefStore,
    ledger: BudgetLedger,
    secrets: SecretStore,
) -> None:
    """The supervisor is told and carries on with the workers it has."""
    await settings.update({"max_agents_per_run": 2})  # supervisor + one worker
    script = [
        says("First.", call("spawn_agent", "c1", agent="researcher", task="t1")),
        says("Done.", call("finish", "c2", result="figures")),
        says("Second.", call("spawn_agent", "c3", agent="writer", task="t2")),
        says("Wrapping up.", call("finish", "c4", result="only the researcher ran")),
    ]

    _, rebuilt = await drive(store, settings, agents, ledger, secrets, script)

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
    store: EventStore,
    settings: SettingsStore,
    agents: AgentDefStore,
    ledger: BudgetLedger,
    secrets: SecretStore,
) -> None:
    """Phase 3 could only assert this at the wrapper. Now it is observable as a
    run outcome, which is how a user actually meets it."""
    await settings.update({"monthly_cap_micros": 1})

    _, rebuilt = await drive(store, settings, agents, ledger, secrets, TWO_WORKER_SCRIPT)

    assert rebuilt.status == "failed"
    assert rebuilt.outcome is not None
    assert "monthly budget" in rebuilt.outcome
    assert "budget.exceeded" in rebuilt.budget_events
    # Nothing ran: the refusal happened before the first model call.
    assert rebuilt.input_tokens == 0


async def test_an_unknown_tool_name_is_reported_not_fatal(
    store: EventStore,
    settings: SettingsStore,
    agents: AgentDefStore,
    ledger: BudgetLedger,
    secrets: SecretStore,
) -> None:
    """A model naming a tool that does not exist gets told what it may use.

    The name here has to be one the tool catalogue does not know. `read_file`
    used to serve (it was unknown to Phase 4), but Phase 5 registers it, so it
    is now a real tool the supervisor is *denied* rather than a name that means
    nothing. The next test covers that case; this one keeps covering this one.
    """
    script = [
        says("Trying.", call("consult_the_oracle", "c1", question="what is Q3?")),
        says("Fine.", call("finish", "c2", result="did it without tools")),
    ]

    _, rebuilt = await drive(store, settings, agents, ledger, secrets, script)

    assert rebuilt.status == "completed"
    assert "consult_the_oracle" in rebuilt.agent("supervisor").tool_errors[0]
    assert rebuilt.agent("supervisor").denied_tools == []


async def test_the_supervisor_cannot_reach_the_tool_catalogue(
    store: EventStore,
    settings: SettingsStore,
    agents: AgentDefStore,
    ledger: BudgetLedger,
    secrets: SecretStore,
) -> None:
    """The supervisor has no `allowed_tools`, and that is a boundary.

    It is the one agent present in every run and the one a user cannot edit, so
    it is also the one that must never be able to touch anything. It delegates;
    the agents it delegates to are the ones whose permissions a user controls.
    """
    script = [
        says("I will just do it myself.", call("write_file", "c1", path="out.md", content="x")),
        says("Fine.", call("finish", "c2", result="delegated after all")),
    ]

    _, rebuilt = await drive(store, settings, agents, ledger, secrets, script)

    supervisor = rebuilt.agent("supervisor")
    assert supervisor.denied_tools == ["write_file"]
    assert [name for name, _ in supervisor.tool_calls] == ["finish"]
    assert rebuilt.status == "completed"


async def test_a_worker_can_hand_off_and_the_event_is_recorded(
    store: EventStore,
    settings: SettingsStore,
    agents: AgentDefStore,
    ledger: BudgetLedger,
    secrets: SecretStore,
) -> None:
    script = [
        says("Delegating.", call("spawn_agent", "c1", agent="researcher", task="t1")),
        says("Not my job.", call("handoff", "c2", to="writer", task="write it up")),
        says("Understood.", call("finish", "c3", result="the researcher passed it on")),
    ]

    _, rebuilt = await drive(store, settings, agents, ledger, secrets, script)

    assert rebuilt.status == "completed"
    assert rebuilt.agent("researcher").finished_reason == "handoff"
    assert ("researcher", "writer", "write it up") in rebuilt.handoffs


async def test_a_worker_handoff_tells_the_supervisor_how_to_continue_it(
    store: EventStore,
    settings: SettingsStore,
    agents: AgentDefStore,
    ledger: BudgetLedger,
    secrets: SecretStore,
) -> None:
    """A worker cannot spawn (that would let any agent widen the run from
    inside its own turn), so a handoff goes back to the supervisor as text.
    Phase 4 through Phase 6 recorded that nothing asserted the supervisor
    then did anything sensible with it. What it is handed now is explicit:
    who asked for whom, and that `spawn_agent` with that name continues it.
    """
    script = [
        says("Delegating.", call("spawn_agent", "c1", agent="researcher", task="find it")),
        says("Not my job.", call("handoff", "c2", to="writer", task="write it up")),
        says("Passing it on.", call("spawn_agent", "c3", agent="writer", task="write it up")),
        says("Written.", call("finish", "c4", result="the report")),
        says("Done.", call("finish", "c5", result="the report is written")),
    ]

    run_id, rebuilt = await drive(store, settings, agents, ledger, secrets, script)

    assert rebuilt.status == "completed"
    assert ("researcher", "writer", "write it up") in rebuilt.handoffs
    assert ("supervisor", "writer", "write it up") in rebuilt.handoffs
    assert rebuilt.agent("writer").finished_reason == "finished"

    # The supervisor's spawn result says what the worker asked for, and the
    # transcript it was handed next names the call that continues it.
    events = await store.read(run_id)
    spawn_results = [
        e.payload
        for e in events
        if e.type is EventType.TOOL_RESULT
        and e.agent_id == "supervisor"
        and e.payload["tool"] == "spawn_agent"
    ]
    assert spawn_results[0]["handoff"] == {"to": "writer", "known": True}
    requests = [
        e.payload
        for e in events
        if e.type is EventType.LLM_REQUEST and e.agent_id == "supervisor"
    ]
    handed = requests[1]["messages"][-1]["content"]
    assert "handed this off to 'writer'" in handed
    assert "spawn_agent" in handed


async def test_a_handoff_to_an_agent_not_on_the_roster_says_so(
    store: EventStore,
    settings: SettingsStore,
    agents: AgentDefStore,
    ledger: BudgetLedger,
    secrets: SecretStore,
) -> None:
    """Phase 6 watched a denied worker hand off to a nonexistent
    `another_agent` and the supervisor do nothing with it. The supervisor
    is told the name is not on the roster and what is, so its next call can
    be a sensible one rather than a spawn that fails."""
    script = [
        says("Delegating.", call("spawn_agent", "c1", agent="researcher", task="find it")),
        says("Someone else.", call("handoff", "c2", to="another_agent", task="do it")),
        says("No such agent.", call("finish", "c3", result="could not continue")),
    ]

    run_id, rebuilt = await drive(store, settings, agents, ledger, secrets, script)

    assert rebuilt.status == "completed"
    events = await store.read(run_id)
    spawn_result = next(
        e.payload
        for e in events
        if e.type is EventType.TOOL_RESULT
        and e.agent_id == "supervisor"
        and e.payload["tool"] == "spawn_agent"
    )
    assert spawn_result["handoff"] == {"to": "another_agent", "known": False}
    requests = [
        e.payload
        for e in events
        if e.type is EventType.LLM_REQUEST and e.agent_id == "supervisor"
    ]
    handed = requests[1]["messages"][-1]["content"]
    assert "'another_agent'" in handed
    assert "not on this roster" in handed
    assert "researcher" in handed and "writer" in handed


# --- what the model is actually offered --------------------------------------


async def test_a_worker_is_not_offered_spawn_agent(
    store: EventStore,
    settings: SettingsStore,
    agents: AgentDefStore,
    ledger: BudgetLedger,
    secrets: SecretStore,
) -> None:
    """A worker that could spawn could widen the run's shape from inside its
    own turn, and the agent cap would stop describing what a run can do."""
    provider = ScriptedProvider(TWO_WORKER_SCRIPT)
    run = await store.create_run(goal="g")

    await execute_run(store, settings, agents, ledger, secrets, run.id, "g", provider=provider)

    # Call 0 is the supervisor, call 1 the first worker.
    assert "spawn_agent" in provider.offered_tools[0]
    assert "spawn_agent" not in provider.offered_tools[1]
    assert "finish" in provider.offered_tools[1]


# --- backpressure ------------------------------------------------------------
#
# CLAUDE.md recorded this as unverified after Phase 2: "no HTTP client has ever
# overflowed a 512-event queue, because nothing yet emits events fast enough.
# Revisit when Phase 4 streams `llm.token` at model speed; that is the first
# thing that plausibly outruns a subscriber."
#
# This is that revisit. A subscriber queue holds 512 events; one streamed model
# response here produces well over that, and the consumer deliberately stops
# reading while they are produced. The bus drops the buffer of a subscriber it
# cannot keep up with, which is safe *only* because the durable row makes the
# buffered copy worthless and the stream re-reads the range from SQLite. If that
# resync were wrong, this is the test that shows it, as a gap or a duplicate in
# what the client receives.


FLOOD_WORDS = 900


def flood_script() -> list[Completion]:
    """One long streamed answer, then a `finish`.

    Long enough that the `llm.token` events alone exceed the queue by a wide
    margin, so the overflow is not a near-miss that passes by luck.
    """
    return [
        says(" ".join(f"word{i}" for i in range(FLOOD_WORDS))),
        says("Done.", call("finish", "c1", result="flood complete")),
    ]


async def test_a_token_flood_reaches_a_slow_subscriber_without_gaps(
    store: EventStore,
    bus: EventBus,
    settings: SettingsStore,
    agents: AgentDefStore,
    ledger: BudgetLedger,
    secrets: SecretStore,
) -> None:
    """A subscriber that stops reading must still receive every event, once.

    The stream is consumed directly rather than over HTTP because httpx's ASGI
    transport buffers a response body to completion before handing it back -
    so an in-process HTTP client cannot read a stream while the run producing
    it is still going. That is a limitation of the test transport, not of the
    server; the HTTP framing above this generator is covered by the Phase 2
    tests. What was never covered, and is covered here, is the resync path
    running because a queue actually overflowed.
    """
    run = await store.create_run(goal="flood", origin="ui")

    stream = run_stream(store, bus, run.id, 0)

    # The first item is the retry hint, and pulling it is what subscribes this
    # client to the bus. Subscribing has to happen before the flood, or the
    # test measures a backlog replay instead of an overflow.
    assert (await anext(stream)).startswith("retry:")

    # A second subscriber that never reads, held only to prove the queue really
    # did overflow. Without it this test could pass having measured nothing:
    # "more than 512 events arrived" is not the same claim as "a subscriber was
    # dropped and the stream recovered by re-reading SQLite".
    with bus.subscribe(run.id) as idle:
        await execute_run(
            store,
            settings,
            agents,
            ledger,
            secrets,
            run.id,
            "flood",
            provider=ScriptedProvider(flood_script()),
        )
        assert idle.stale, (
            "no subscriber was overwhelmed, so the resync path never ran and "
            "this test proved nothing"
        )

    frames = [json.loads(line[len("data:") :]) for line in await _drain(stream)]

    sequences = [frame["seq"] for frame in frames]
    assert sequences == sorted(set(sequences)), "a gap or a duplicate reached the client"
    assert sequences == list(range(1, len(sequences) + 1))
    assert len(sequences) > DEFAULT_QUEUE_SIZE, (
        f"only {len(sequences)} events: the {DEFAULT_QUEUE_SIZE}-event queue "
        f"bound was never crossed, so this test proved nothing"
    )
    assert frames[-1]["type"] == "run.completed"
    assert sum(1 for f in frames if f["type"] == "llm.token") >= FLOOD_WORDS


async def _drain(stream: AsyncIterator[str]) -> list[str]:
    """Collect the data frames the stream has left, ignoring keepalives."""
    lines: list[str] = []
    async for chunk in stream:
        lines.extend(line for line in chunk.splitlines() if line.startswith("data:"))
    return lines
