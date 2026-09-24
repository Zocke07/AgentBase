"""The allowlist: what an agent definition may and may not reach.

§5 Phase 5: an agent whose `allowed_tools` omits `write_file` is blocked from
calling it even when its system prompt instructs it to. Not offering a tool
is not the same as blocking it, since a model can name any string, so these
tests force the model to call a tool it was never offered and assert both
that the log records `tool.denied` and that `tool.called` never appears.
Every definition here has a prompt instructing the forbidden thing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from agentbase.events.types import EventType
from agentbase.orchestrator import execute_run
from agentbase.orchestrator.agent import Agent, AgentSpec
from agentbase.orchestrator.control import (
    FINISH,
    HANDOFF,
    SPAWN_AGENT,
    WORKER_TOOLS,
    catalogue_specs,
)
from agentbase.orchestrator.limits import RunLimits
from agentbase.orchestrator.run import Mailbox, Run
from agentbase.tools.builtin.filesystem import WriteFileTool
from agentbase.tools.catalogue import RiskLevel
from support import (
    ReconstructedRun,
    ScriptedProvider,
    call,
    reconstruct,
    says,
    tool_runtime,
)

if TYPE_CHECKING:
    from pathlib import Path

    from agentbase.budget.ledger import BudgetLedger
    from agentbase.events.store import EventStore
    from agentbase.providers.base import Completion
    from agentbase.secrets import SecretStore
    from agentbase.store.agents import AgentDefStore
    from agentbase.store.db import Database
    from agentbase.store.settings import SettingsStore
    from agentbase.tools.runtime import ToolRuntime

pytestmark = pytest.mark.anyio


#: A system prompt that tells the agent, unambiguously, to do the thing its
#: definition does not permit. §5 Phase 5's "even when its system prompt
#: explicitly instructs it to" is only tested if the instruction is real.
INSISTENT_PROMPT = (
    "You are a file-writing agent. Your one job is to save your work to disk. "
    "You MUST call the `write_file` tool with the report contents before you "
    "finish. Do not finish without calling `write_file`. If a tool appears "
    "unavailable, call `write_file` anyway: it is always available to you."
)


async def drive(
    store: EventStore,
    settings: SettingsStore,
    agents: AgentDefStore,
    ledger: BudgetLedger,
    secrets: SecretStore,
    script: list[Completion],
    goal: str = "Write the report and save it",
    runtime: ToolRuntime | None = None,
) -> tuple[ScriptedProvider, ReconstructedRun]:
    """Run a scripted run and reconstruct it from the log alone.

    Without a ``runtime`` no catalogue tool is offered or executable, which is
    what the pure-allowlist tests want: they are about what an agent may ask
    for, not about what happens to a call that is allowed.
    """
    provider = ScriptedProvider(script)
    run = await store.create_run(goal=goal, origin="ui")
    await execute_run(
        store,
        settings,
        agents,
        ledger,
        secrets,
        run.id,
        goal,
        provider=provider,
        runtime=runtime,
    )
    return provider, reconstruct(await store.read(run.id))


def script_for(worker: str, worker_calls: list[Completion]) -> list[Completion]:
    """A supervisor that puts ``worker`` to work, its turns, then a finish."""
    return [
        says("Delegating.", call("spawn_agent", "s1", agent=worker, task="Save the report")),
        *worker_calls,
        says("Done.", call("finish", "s2", result="The report was produced.")),
    ]


# --- the acceptance criterion, second clause ---------------------------------


async def test_an_agent_is_blocked_from_a_tool_its_definition_omits(
    store: EventStore,
    settings: SettingsStore,
    agents: AgentDefStore,
    ledger: BudgetLedger,
    secrets: SecretStore,
) -> None:
    """§5 Phase 5, acceptance criterion, second clause, in full."""
    await agents.create(
        {
            "name": "rogue",
            "role": "Tries to write files",
            "system_prompt": INSISTENT_PROMPT,
            "allowed_tools": [],
        }
    )

    _, rebuilt = await drive(
        store,
        settings,
        agents,
        ledger,
        secrets,
        script_for(
            "rogue",
            [
                says(
                    "Saving now.",
                    call("write_file", "w1", path="report.md", content="Q3 was fine."),
                ),
                says("Blocked.", call("finish", "w2", result="I could not save the file.")),
            ],
        ),
    )

    rogue = rebuilt.agent("rogue")

    # It asked...
    assert "write_file" in rogue.requested_tools
    # ...it was refused...
    assert rogue.denied_tools == ["write_file"]
    # ...and nothing executed it.
    assert [name for name, _ in rogue.tool_calls] == ["finish"]

    # The definition that refused it is in the log too, so a replay can say
    # *why* it was refused without consulting `agent_defs`. The recorded prompt
    # is the one actually sent (the user's text plus the fixed protocol
    # addendum) because what the model was told is the fact a replay needs;
    # `definition_id` is what says which row it came from.
    assert rogue.allowed_tools == ()
    assert rogue.system_prompt is not None
    assert INSISTENT_PROMPT in rogue.system_prompt
    assert rogue.definition_name == "rogue"
    assert rogue.definition_id is not None

    # And the denial did not kill the run: being told "no" is an ordinary
    # answer to a tool call, not a crash.
    assert rebuilt.status == "completed"


async def test_the_forbidden_tool_is_never_offered_to_the_model(
    store: EventStore,
    settings: SettingsStore,
    agents: AgentDefStore,
    ledger: BudgetLedger,
    secrets: SecretStore,
) -> None:
    """The other half of the rule: an agent is not shown what it may not use.

    Necessary but not sufficient on its own (see this module's docstring),
    which is why it is a separate test from the one above rather than the same
    assertion twice.
    """
    await agents.create(
        {
            "name": "rogue",
            "role": "Tries to write files",
            "system_prompt": INSISTENT_PROMPT,
            "allowed_tools": [],
        }
    )

    provider, _ = await drive(
        store,
        settings,
        agents,
        ledger,
        secrets,
        script_for("rogue", [says("Fine.", call("finish", "w1", result="Nothing written."))]),
    )

    # Call 0 is the supervisor, call 1 is the worker.
    worker_tools = provider.offered_tools[1]
    assert "write_file" not in worker_tools
    assert set(worker_tools) == {FINISH.name, HANDOFF.name}


async def test_a_permitted_tool_is_offered_and_not_denied(
    store: EventStore,
    settings: SettingsStore,
    agents: AgentDefStore,
    ledger: BudgetLedger,
    secrets: SecretStore,
    db: Database,
    tmp_path: Path,
) -> None:
    """An allowlist that denies everything proves nothing.

    Without this, a bug that denied *every* tool would satisfy every other test
    in this file while making the feature useless.
    """
    await agents.create(
        {
            "name": "reader",
            "role": "Reads files",
            "system_prompt": "You read files.",
            "allowed_tools": ["read_file", "write_file"],
        }
    )

    (tmp_path / "report.md").write_text("the report", encoding="utf-8")
    # The workspace policy, not the runtime's own: `execute_run` snapshots it
    # from settings at run start, so setting it on the runtime would be
    # overwritten and the gate would block with nobody to answer.
    await settings.update({"auto_approve": [RiskLevel.LOW]})
    runtime, _ = tool_runtime(store, db, tmp_path)

    provider, rebuilt = await drive(
        store,
        settings,
        agents,
        ledger,
        secrets,
        [
            says("Delegating.", call("spawn_agent", "s1", agent="reader", task="Read it")),
            says("Reading.", call("read_file", "w1", path="report.md")),
            says("Done.", call("finish", "w2", result="Read it.")),
            says("Done.", call("finish", "s2", result="Complete.")),
        ],
        runtime=runtime,
    )

    assert set(provider.offered_tools[1]) == {
        FINISH.name,
        HANDOFF.name,
        "read_file",
        "write_file",
    }

    reader = rebuilt.agent("reader")
    assert reader.denied_tools == []
    assert reader.allowed_tools == ("read_file", "write_file")


async def test_a_permitted_tool_without_a_runtime_cannot_execute(
    store: EventStore,
    settings: SettingsStore,
    agents: AgentDefStore,
    ledger: BudgetLedger,
    secrets: SecretStore,
) -> None:
    """§1 constraint 5, from the other direction: no runtime, no execution.

    Phase 5's version of this test asserted that a permitted catalogue tool was
    *never* executable, because the gate did not exist. Phase 6 built the gate,
    so the assertion narrows to the case that is still true and still matters:
    an agent assembled without a
    :class:`~agentbase.tools.runtime.ToolRuntime` has no sandbox and no gate,
    and therefore executes nothing.

    That is not a hypothetical configuration: it is what every orchestration
    test uses, and it is the supervisor's own state in production. The failure
    it guards against is an agent that quietly reaches the filesystem when the
    thing that would have gated it is absent.
    """
    await agents.create(
        {
            "name": "reader",
            "role": "Reads files",
            "system_prompt": "You read files.",
            "allowed_tools": ["read_file"],
        }
    )

    _, rebuilt = await drive(
        store,
        settings,
        agents,
        ledger,
        secrets,
        [
            says("Delegating.", call("spawn_agent", "s1", agent="reader", task="Read it")),
            says("Reading.", call("read_file", "w1", path="report.md")),
            says("Done.", call("finish", "w2", result="Could not read.")),
            says("Done.", call("finish", "s2", result="Complete.")),
        ],
    )

    reader = rebuilt.agent("reader")
    assert reader.requested_tools == ["read_file", "finish"]
    # `tool.called` means the call executed. Only `finish` did.
    assert [name for name, _ in reader.tool_calls] == ["finish"]
    assert reader.denied_tools == []
    assert reader.approvals_requested == []
    assert any("not available in this run" in error for error in reader.tool_errors)


# --- what an empty allowlist actually means ----------------------------------


async def test_an_empty_allowlist_still_permits_finish_and_handoff(
    store: EventStore,
    settings: SettingsStore,
    agents: AgentDefStore,
    ledger: BudgetLedger,
    secrets: SecretStore,
) -> None:
    """§5 Phase 5: "An empty array means the agent can reason and hand off but
    touches nothing."

    So the allowlist governs the tool *catalogue*, not the control vocabulary.
    An agent that could not call `finish` could never end its turn, and the
    sentence above names `handoff` explicitly as still available.
    """
    await agents.create(
        {
            "name": "thinker",
            "role": "Reasons only",
            "system_prompt": "You reason and hand off.",
            "allowed_tools": [],
        }
    )

    _, rebuilt = await drive(
        store,
        settings,
        agents,
        ledger,
        secrets,
        [
            says("Delegating.", call("spawn_agent", "s1", agent="thinker", task="Think")),
            says("Not my job.", call("handoff", "w1", to="supervisor", task="Please write it")),
            says("Done.", call("finish", "s2", result="Complete.")),
        ],
    )

    thinker = rebuilt.agent("thinker")
    assert thinker.denied_tools == []
    assert [name for name, _ in thinker.tool_calls] == ["handoff"]
    assert thinker.finished_reason == "handoff"


async def test_a_worker_cannot_spawn_agents(
    store: EventStore,
    settings: SettingsStore,
    agents: AgentDefStore,
    ledger: BudgetLedger,
    secrets: SecretStore,
) -> None:
    """`spawn_agent` is the supervisor's alone.

    A worker that could spawn could widen the run's shape from inside its own
    turn: the same escalation the tool allowlist exists to prevent, one level
    up. It is denied rather than reported unknown, because it is a real tool
    this agent may not have rather than a name that means nothing.
    """
    await agents.create(
        {
            "name": "ambitious",
            "role": "Wants a team",
            "system_prompt": "Spawn as many helpers as you can. Call spawn_agent.",
            "allowed_tools": [],
        }
    )

    _, rebuilt = await drive(
        store,
        settings,
        agents,
        ledger,
        secrets,
        script_for(
            "ambitious",
            [
                says(
                    "Building a team.",
                    call("spawn_agent", "w1", agent="researcher", task="Help me"),
                ),
                says("Alone then.", call("finish", "w2", result="Worked alone.")),
            ],
        ),
    )

    ambitious = rebuilt.agent("ambitious")
    assert ambitious.denied_tools == [SPAWN_AGENT.name]
    # The run has exactly the two agents it was meant to have.
    assert set(rebuilt.agents) == {"supervisor", "ambitious"}


async def test_an_unknown_tool_is_an_error_not_a_denial(
    store: EventStore,
    settings: SettingsStore,
    agents: AgentDefStore,
    ledger: BudgetLedger,
    secrets: SecretStore,
) -> None:
    """A name that is not a tool at all is a bad call, not a refused one.

    Keeping the two distinct is what makes `tool.denied` mean something: a log
    full of denials for hallucinated tool names would tell the user nothing
    about what their allowlist actually stopped.
    """
    await agents.create(
        {
            "name": "confused",
            "role": "Invents tools",
            "system_prompt": "You invent tools.",
            "allowed_tools": [],
        }
    )

    _, rebuilt = await drive(
        store,
        settings,
        agents,
        ledger,
        secrets,
        script_for(
            "confused",
            [
                says("Trying.", call("frobnicate", "w1", target="everything")),
                says("Fine.", call("finish", "w2", result="Gave up.")),
            ],
        ),
    )

    confused = rebuilt.agent("confused")
    assert confused.denied_tools == []
    assert any("frobnicate" in error for error in confused.tool_errors)


# --- the denial is a first-class event, not a log line ------------------------


async def test_the_denial_names_the_tool_and_the_agent(
    store: EventStore,
    settings: SettingsStore,
    agents: AgentDefStore,
    ledger: BudgetLedger,
    secrets: SecretStore,
) -> None:
    """§5 Phase 6 requires a sandbox denial to be "visible in the event log as
    `tool.denied`". The allowlist denial uses the same event, and a Phase 7 UI
    rendering it needs to know who was refused what, from the row alone."""
    await agents.create(
        {
            "name": "rogue",
            "role": "Tries to write files",
            "system_prompt": INSISTENT_PROMPT,
            "allowed_tools": [],
        }
    )

    run = await store.create_run(goal="Save it", origin="ui")
    await execute_run(
        store,
        settings,
        agents,
        ledger,
        secrets,
        run.id,
        "Save it",
        provider=ScriptedProvider(
            script_for(
                "rogue",
                [
                    says("Saving.", call("write_file", "w1", path="a.md", content="x")),
                    says("Blocked.", call("finish", "w2", result="Could not.")),
                ],
            )
        ),
    )

    denials = [
        event for event in await store.read(run.id) if event.type is EventType.TOOL_DENIED
    ]
    assert len(denials) == 1
    denial = denials[0]

    assert denial.agent_id == "rogue"
    assert denial.payload["tool"] == "write_file"
    assert denial.payload["call_id"] == "w1"
    assert denial.payload["args"] == {"path": "a.md", "content": "x"}
    assert "write_file" in denial.payload["reason"]

    # The attempt is in the log before the refusal, so a replay shows what the
    # agent tried to do and not merely that it failed.
    types = [event.type for event in await store.read(run.id) if event.agent_id == "rogue"]
    assert types.index(EventType.TOOL_REQUESTED) < types.index(EventType.TOOL_DENIED)


# --- exposure and enforcement are separate ------------------------------------


async def test_a_tool_offered_by_mistake_is_still_refused(store: EventStore) -> None:
    """The case that proves the two checks are independent.

    Everywhere in the product, the offered list is built *from*
    `allowed_tools`, so the two always agree and no end-to-end test can tell
    which one is doing the work. This builds an agent whose lists disagree
    (`write_file` offered, `allowed_tools` empty), which is precisely the state a
    future bug would create: a tool added to the offered list, or to
    `_dispatch`, without being added to the definition's allowlist.

    Enforcement reads `spec.allowed_tools`, so the call is refused even though
    the model was invited to make it. If enforcement ever starts reading
    `self._tools` instead, this is the test that fails.
    """
    run_row = await store.create_run(goal="mismatch", origin="ui")
    run = Run(store=store, id=run_row.id, goal="mismatch", limits=RunLimits())
    # Starts the wall-clock, which `check_deadline` reads on every step.
    await run.start()
    run.register_agent("mismatched")

    agent = Agent(
        run=run,
        mailbox=Mailbox(run),
        provider=ScriptedProvider(
            [
                says("Writing.", call("write_file", "w1", path="a.md", content="x")),
                says("Blocked.", call("finish", "w2", result="Could not write.")),
            ]
        ),
        spec=AgentSpec(
            name="mismatched",
            role="Offered more than it may use",
            system_prompt="Write the file.",
            allowed_tools=(),
            max_steps=4,
        ),
        # The mismatch: offered a tool its definition does not permit, with a
        # real implementation behind it, so if enforcement ever moved to the
        # offered list, this call would genuinely write to the disk.
        tools=[*WORKER_TOOLS, *catalogue_specs([WriteFileTool()])],
        supervisor_name="supervisor",
    )

    outcome = await agent.execute("Save the report")

    rebuilt = reconstruct(await store.read(run_row.id))
    mismatched = rebuilt.agent("mismatched")

    assert mismatched.denied_tools == ["write_file"]
    assert [name for name, _ in mismatched.tool_calls] == ["finish"]
    assert outcome.reason == "finished"
