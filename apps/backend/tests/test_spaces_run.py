"""A run happens *in* a space: its roster, its folder, its rules.

§5 Phase 11's first two acceptance criteria, through the launcher (the one
object that knows how to start a run) with a scripted provider standing in
for the model, a real sandbox rooted at each space's folder, and the real
gate pre-answered. The live version of criteria 1 and 2 is in CLAUDE.md.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from agentbase.knowledge.store import KnowledgeStore
from agentbase.orchestrator.launcher import RunLauncher
from agentbase.store.spaces import DEFAULT_SPACE_ID, SpaceArchivedError, SpaceStore
from agentbase.tools.catalogue import RiskLevel
from support import ScriptedProvider, StandingAnswer, call, reconstruct, says, tool_runtime

if TYPE_CHECKING:
    from agentbase.budget.ledger import BudgetLedger
    from agentbase.config import AppPaths
    from agentbase.events.store import EventStore
    from agentbase.secrets import SecretStore
    from agentbase.store.agents import AgentDefStore
    from agentbase.store.db import Database
    from agentbase.store.settings import SettingsStore

pytestmark = pytest.mark.anyio


@pytest.fixture
def spaces(db: Database, app_paths: AppPaths) -> SpaceStore:
    return SpaceStore(db, app_paths.spaces_dir)


def _launcher(
    store: EventStore,
    settings: SettingsStore,
    agents: AgentDefStore,
    ledger: BudgetLedger,
    secrets: SecretStore,
    spaces: SpaceStore,
    provider: ScriptedProvider,
    runtime: object,
) -> RunLauncher:
    return RunLauncher(
        store=store,
        settings=settings,
        agents=agents,
        ledger=ledger,
        secrets=secrets,
        runtime=runtime,  # type: ignore[arg-type]
        spaces=spaces,
        provider=provider,
    )


async def test_a_run_in_space_a_never_spawns_an_agent_that_lives_in_space_b(
    store: EventStore,
    settings: SettingsStore,
    agents: AgentDefStore,
    ledger: BudgetLedger,
    secrets: SecretStore,
    spaces: SpaceStore,
) -> None:
    """Criterion 1: the supervisor's roster is A's, and B's agent is refused."""
    space_a = await spaces.create({"name": "A"})
    space_b = await spaces.create({"name": "B"})
    await agents.create(
        {"space_id": space_a.id, "name": "scout", "role": "r", "system_prompt": "p"}
    )
    await agents.create(
        {"space_id": space_b.id, "name": "sniper", "role": "r", "system_prompt": "p"}
    )

    provider = ScriptedProvider(
        [
            says("Using sniper.", call("spawn_agent", "s1", agent="sniper", task="go")),
            says("Fine.", call("finish", "s2", result="done without it")),
        ]
    )
    launcher = _launcher(store, settings, agents, ledger, secrets, spaces, provider, None)

    run = await launcher.launch("Use the sniper by name", space_id=space_a.id)
    assert run.space_id == space_a.id
    await asyncio.gather(*launcher.tasks)
    events = await store.read(run.id)
    rebuilt = reconstruct(events)

    started = next(e for e in events if e.type == "run.started")
    assert started.payload["space"] == {"id": space_a.id, "name": "A"}
    # The roster the supervisor was told about is A's alone. The goal names
    # the other agent, so look at the roster section rather than the whole
    # prompt.
    roster = (provider.systems[0] or "").split("These agents are available to you")[1]
    assert "scout" in roster
    assert "sniper" not in roster
    assert set(rebuilt.agents) == {"supervisor"}
    refusal = next(e for e in events if e.type == "tool.error")
    assert "no agent named 'sniper'" in str(refusal.payload["error"])
    assert rebuilt.status == "completed"


async def test_a_write_lands_in_the_run_spaces_folder_and_another_spaces_folder_is_out_of_bounds(
    store: EventStore,
    settings: SettingsStore,
    agents: AgentDefStore,
    ledger: BudgetLedger,
    secrets: SecretStore,
    spaces: SpaceStore,
    db: Database,
    app_paths: AppPaths,
) -> None:
    """Criterion 2: the sandbox is the space's folder, per run."""
    await settings.update({"auto_approve": [RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH]})
    space_a = await spaces.create({"name": "A"})
    space_b = await spaces.create({"name": "B"})
    await agents.create(
        {
            "space_id": space_a.id,
            "name": "filewriter",
            "role": "r",
            "system_prompt": "p",
            "allowed_tools": ["write_file"],
        }
    )
    into_b = spaces.folder_for(space_b.id) / "stolen.txt"
    provider = ScriptedProvider(
        [
            says("Delegating.", call("spawn_agent", "s1", agent="filewriter", task="write")),
            says("Writing.", call("write_file", "w1", path="mine.txt", content="hello")),
            says("And there.", call("write_file", "w2", path=str(into_b), content="hi")),
            says("Done.", call("finish", "w3", result="wrote")),
            says("Done.", call("finish", "s2", result="wrote")),
        ]
    )
    # The process-wide runtime is rooted at the default space; the launcher
    # must rebind it to A's folder for this run.
    runtime, service = tool_runtime(store, db, spaces.folder_for(DEFAULT_SPACE_ID))
    launcher = _launcher(store, settings, agents, ledger, secrets, spaces, provider, runtime)

    async with StandingAnswer(service, approve=True):
        run = await launcher.launch("Write a file", space_id=space_a.id)
        await asyncio.gather(*launcher.tasks)

    rebuilt = reconstruct(await store.read(run.id))
    writer = rebuilt.agent("filewriter")

    written = spaces.folder_for(space_a.id) / "mine.txt"
    assert await asyncio.to_thread(written.read_text, "utf-8") == "hello"
    assert not await asyncio.to_thread(into_b.exists)
    assert not await asyncio.to_thread(
        (app_paths.spaces_dir / DEFAULT_SPACE_ID / "mine.txt").exists
    )
    assert writer.denied_tools == ["write_file"]
    assert writer.denied_by == ["sandbox"]


async def test_a_spaces_rules_are_laid_over_the_app_wide_settings(
    store: EventStore,
    settings: SettingsStore,
    agents: AgentDefStore,
    ledger: BudgetLedger,
    secrets: SecretStore,
    spaces: SpaceStore,
) -> None:
    """The limits a run is held to are the effective ones, and the log says so."""
    await settings.update({"max_run_seconds": 300, "max_agents_per_run": 5})
    lab = await spaces.create({"name": "Lab", "max_run_seconds": 1200, "max_agents_per_run": 2})
    provider = ScriptedProvider([says("Quick.", call("finish", "s1", result="ok"))])
    launcher = _launcher(store, settings, agents, ledger, secrets, spaces, provider, None)

    run = await launcher.launch("Quick", space_id=lab.id)
    await asyncio.gather(*launcher.tasks)

    started = next(e for e in await store.read(run.id) if e.type == "run.started")
    assert started.payload["limits"]["max_run_seconds"] == 1200
    assert started.payload["limits"]["max_agents_per_run"] == 2
    # Inherited where the space said nothing.
    assert started.payload["limits"]["max_steps_per_agent"] == 20


async def test_an_archived_space_starts_no_run(
    store: EventStore,
    settings: SettingsStore,
    agents: AgentDefStore,
    ledger: BudgetLedger,
    secrets: SecretStore,
    spaces: SpaceStore,
) -> None:
    lab = await spaces.create({"name": "Lab"})
    await spaces.update(lab.id, {"archived": True})
    launcher = _launcher(
        store, settings, agents, ledger, secrets, spaces, ScriptedProvider([]), None
    )

    with pytest.raises(SpaceArchivedError):
        await launcher.launch("Nope", space_id=lab.id)
    assert await store.list_runs() == []


async def test_a_run_with_no_space_named_lands_in_the_default_space(
    store: EventStore,
    settings: SettingsStore,
    agents: AgentDefStore,
    ledger: BudgetLedger,
    secrets: SecretStore,
    spaces: SpaceStore,
) -> None:
    """What keeps the debug script and an unconfigured chat command working."""
    provider = ScriptedProvider([says("Quick.", call("finish", "s1", result="ok"))])
    launcher = _launcher(store, settings, agents, ledger, secrets, spaces, provider, None)

    run = await launcher.launch("Quick")
    await asyncio.gather(*launcher.tasks)

    assert run.space_id == DEFAULT_SPACE_ID
    started = next(e for e in await store.read(run.id) if e.type == "run.started")
    assert started.payload["space"]["id"] == DEFAULT_SPACE_ID
    # And the default roster (the three built-ins) was what it was offered.
    assert "researcher" in (provider.systems[0] or "")


async def test_a_run_retrieves_vault_context_and_saves_its_summary_as_memory(
    store: EventStore,
    settings: SettingsStore,
    agents: AgentDefStore,
    ledger: BudgetLedger,
    secrets: SecretStore,
    spaces: SpaceStore,
) -> None:
    await spaces.require(DEFAULT_SPACE_ID)
    knowledge = KnowledgeStore(spaces)
    await knowledge.write_note(
        DEFAULT_SPACE_ID,
        "decisions/database.md",
        "# Database choice\n\nUse SQLite WAL for the event log.\n",
    )
    provider = ScriptedProvider(
        [says("Done.", call("finish", "s1", result="SQLite remains the choice."))]
    )
    launcher = RunLauncher(
        store=store,
        settings=settings,
        agents=agents,
        ledger=ledger,
        secrets=secrets,
        spaces=spaces,
        provider=provider,
        knowledge=knowledge,
    )

    run = await launcher.launch("Which database should this event log use?")
    await asyncio.gather(*launcher.tasks)

    assert "[[decisions/database#Database choice]]" in (provider.systems[0] or "")
    assert "Use SQLite WAL" in (provider.systems[0] or "")
    events = await store.read(run.id)
    started = next(event for event in events if event.type == "run.started")
    assert started.payload["knowledge"][0]["path"] == "decisions/database.md"
    completed = next(event for event in events if event.type == "run.completed")
    assert completed.payload["memory_path"] == f"memory/runs/{run.id}.md"
    memory = await knowledge.get_note(DEFAULT_SPACE_ID, completed.payload["memory_path"])
    assert "SQLite remains the choice" in memory.content
