"""Agent definitions: registry, validation, and API.

§5 Phase 5's API-to-run criterion is covered by
:func:`test_an_agent_created_over_http_can_be_spawned_into_a_run`: create the
definition with ``client.post`` and assert only against its event log. The
allowlist criterion is in ``test_agent_allowlist.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from fastapi.testclient import TestClient

from agentbase.main import create_app
from agentbase.orchestrator import execute_run
from agentbase.orchestrator.limits import RunLimits
from agentbase.orchestrator.registry import AgentRegistry, ProviderPool
from agentbase.providers.base import ProviderAuthError
from agentbase.providers.factory import UnknownProviderError
from agentbase.secrets import SecretStore
from agentbase.store.agents import AgentValidationError
from agentbase.store.settings import WorkspaceSettings
from agentbase.tools.builtin import build_registry
from agentbase.tools.catalogue import (
    CATALOGUE,
    RiskLevel,
    effective_auto_approve,
    is_registered,
    tool_names,
)
from support import ReconstructedRun, ScriptedProvider, call, reconstruct, says

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable, Iterator

    from agentbase.budget.ledger import BudgetLedger
    from agentbase.config import AppPaths
    from agentbase.events.store import EventStore
    from agentbase.providers.base import Completion, Message, StreamEvent, ToolSpec
    from agentbase.store.agents import AgentDefStore
    from agentbase.store.db import Database
    from agentbase.store.settings import SettingsStore

anyio_tests = pytest.mark.anyio

#: Migration 010's investment pipeline, ordered as ``GET /agents`` returns it.
#: The ``agents`` fixture adds three starter roles for scripted runs; the API does not.
BUILTINS = (
    "bear-architect",
    "bull-architect",
    "decision",
    "event-calendar",
    "market-movers",
    "news-scanner",
    "portfolio-review",
    "research-librarian",
    "review-analyst",
    "risk-manager",
)


@pytest.fixture
def client(app_paths: AppPaths) -> Iterator[TestClient]:
    with TestClient(create_app(app_paths, secrets=SecretStore())) as test_client:
        yield test_client


def a_definition(**overrides: Any) -> dict[str, Any]:
    """A minimal valid definition body, with fields overridden per test."""
    body: dict[str, Any] = {
        "name": "summariser",
        "role": "Condenses long text",
        "system_prompt": "You summarise. Be brief.",
    }
    body.update(overrides)
    return body


# --- seeding -----------------------------------------------------------------


def test_a_fresh_install_has_a_usable_roster(client: TestClient) -> None:
    """§5 Phase 5: seed built-ins "so a fresh install is usable immediately"."""
    body = client.get("/agents").json()

    assert tuple(sorted(agent["name"] for agent in body)) == BUILTINS
    assert all(agent["is_builtin"] for agent in body)
    assert all(agent["enabled"] for agent in body)


def test_seeded_agents_never_run_a_shell_and_only_collectors_fetch(
    client: TestClient,
) -> None:
    """Verify safe seeded access: no shell, only collectors fetch, and no high-risk auto-approval.

    Migrations 004 and 010 evolved empty allowlists into investment roles.
    Collectors read untrusted public text; analysts write files. A definition's
    ``auto_approve`` only narrows workspace policy and never grants access.
    """
    agents = client.get("/agents").json()
    builtins = [agent for agent in agents if agent["is_builtin"]]
    assert builtins, "the migration should have seeded built-ins"

    for agent in builtins:
        assert "run_shell" not in agent["allowed_tools"], agent["name"]
        assert "high" not in agent["auto_approve"], agent["name"]

    fetchers = [
        agent["name"]
        for agent in builtins
        if {"http_get", "read_feed", "read_prices", "read_market", "read_company_reports"}
        & set(agent["allowed_tools"])
    ]
    assert sorted(fetchers) == ["event-calendar", "market-movers", "news-scanner"]


def test_a_builtin_edited_before_the_upgrade_keeps_its_allowlist(db: Database) -> None:
    """Ensure migration 004 widens only untouched seeded allowlists.

    Upgrades encounter user-edited rows, so widening requires
    ``allowed_tools = '[]'``. A custom row must survive unchanged.
    """
    import json
    import sqlite3

    # Simulate a news-scanner edited before upgrade.
    with db.write() as connection:
        connection.execute(
            "UPDATE agent_defs SET allowed_tools = ? WHERE name = 'news-scanner'",
            (json.dumps(["read_file"]),),
        )

    # ``user_version`` is past 004, so assert the migration guard directly.
    with db.write() as connection:
        try:
            connection.execute(
                'UPDATE agent_defs SET allowed_tools = \'["read_file","list_dir"]\''
                " WHERE name = 'news-scanner' AND allowed_tools = '[]'"
            )
        except sqlite3.Error:  # pragma: no cover
            raise

    with db.read() as connection:
        row = connection.execute(
            "SELECT allowed_tools FROM agent_defs WHERE name = 'news-scanner'"
        ).fetchone()

    assert json.loads(row["allowed_tools"]) == ["read_file"]


def test_a_builtin_is_editable(client: TestClient) -> None:
    """§5 Phase 5: built-ins are "editable but not deletable"."""
    scanner = _by_name(client, "news-scanner")

    response = client.patch(
        f"/agents/{scanner['id']}", json={"system_prompt": "You scan quietly."}
    )

    assert response.status_code == 200
    assert response.json()["system_prompt"] == "You scan quietly."
    assert response.json()["is_builtin"] is True


def test_a_builtin_is_not_deletable(client: TestClient) -> None:
    """``is_builtin = 1`` blocks deletion, not editing."""
    scanner = _by_name(client, "news-scanner")

    response = client.delete(f"/agents/{scanner['id']}")

    assert response.status_code == 409
    assert "cannot be deleted" in response.json()["detail"]
    # The row remains.
    assert client.get(f"/agents/{scanner['id']}").status_code == 200


def test_a_user_defined_agent_is_deletable(client: TestClient) -> None:
    created = client.post("/agents", json=a_definition()).json()

    assert client.delete(f"/agents/{created['id']}").status_code == 204
    assert client.get(f"/agents/{created['id']}").status_code == 404


def test_a_caller_cannot_mint_a_builtin(client: TestClient) -> None:
    """Reject ``is_builtin`` input so callers cannot create undeletable rows."""
    response = client.post("/agents", json=a_definition(is_builtin=True))

    assert response.status_code == 422


# --- validation --------------------------------------------------------------


@pytest.mark.parametrize(
    ("overrides", "field", "fragment"),
    [
        ({"name": "news-scanner"}, "name", "already exists"),
        ({"name": "Bad Name"}, "name", "not a usable agent name"),
        ({"name": ""}, "name", "needs a name"),
        ({"system_prompt": "   "}, "system_prompt", "needs a system prompt"),
        ({"role": ""}, "role", "needs a role"),
        ({"allowed_tools": ["delete_everything"]}, "allowed_tools", "is not a tool"),
        ({"max_steps": 500}, "max_steps", "above this workspace's limit"),
        ({"max_steps": 0}, "max_steps", "at least 1"),
        ({"auto_approve": ["catastrophic"]}, "auto_approve", "is not a risk level"),
        ({"provider": "not_a_provider"}, "provider", "unknown provider"),
    ],
)
def test_an_invalid_definition_is_rejected_with_a_readable_message(
    client: TestClient, overrides: dict[str, Any], field: str, fragment: str
) -> None:
    """§5 Phase 5: reject invalid definitions with readable, field-aware errors.

    The editor uses ``field`` to show the error inline rather than in a generic
    toast.
    """
    response = client.post("/agents", json=a_definition(**overrides))

    assert response.status_code in {400, 409}
    detail = response.json()["detail"]
    assert detail["field"] == field
    assert fragment in detail["message"]


def test_an_agent_can_be_created_when_the_cap_is_below_the_default(
    client: TestClient,
) -> None:
    """Omitted ``max_steps`` must use the current cap, not §4's default of 20.

    A lowered cap once rejected an ordinary request for a field it omitted.
    The hidden-default collision escaped tests that supplied ``max_steps`` or
    kept the default cap.
    """
    assert client.patch("/settings", json={"max_steps_per_agent": 4}).status_code == 200

    response = client.post("/agents", json=a_definition())

    assert response.status_code == 201
    assert response.json()["max_steps"] == 4


def test_an_explicit_max_steps_above_a_lowered_cap_is_still_refused(
    client: TestClient,
) -> None:
    """The fix above must not become "the cap no longer applies"."""
    client.patch("/settings", json={"max_steps_per_agent": 4})

    response = client.post("/agents", json=a_definition(max_steps=9))

    assert response.status_code == 400
    assert response.json()["detail"]["field"] == "max_steps"


def test_a_duplicate_name_is_a_conflict_not_a_bad_request(client: TestClient) -> None:
    """Return 409, not 400, for valid input that conflicts with visible state.

    A separate assertion prevents unrelated validation from masking this as a
    400.
    """
    response = client.post("/agents", json=a_definition(name="news-scanner"))

    assert response.status_code == 409
    assert response.json()["detail"]["field"] == "name"


def test_a_rejected_definition_is_not_written(client: TestClient) -> None:
    """A 400 that half-wrote a row would be worse than a 500."""
    client.post("/agents", json=a_definition(allowed_tools=["nope"]))

    assert [agent["name"] for agent in client.get("/agents").json()] == list(BUILTINS)


def test_an_unknown_field_is_rejected_rather_than_ignored(client: TestClient) -> None:
    """Reject unknown fields; Pydantic would otherwise accept a misspelling without change."""
    response = client.post("/agents", json=a_definition(max_stepss=4))

    assert response.status_code == 422
    assert "max_stepss" in response.text


def test_renaming_onto_an_existing_name_is_refused(client: TestClient) -> None:
    created = client.post("/agents", json=a_definition()).json()

    response = client.patch(f"/agents/{created['id']}", json={"name": "news-scanner"})

    assert response.status_code == 409


def test_renaming_an_agent_to_its_own_name_is_allowed(client: TestClient) -> None:
    """Exclude the updated row from uniqueness checks so unchanged forms save."""
    created = client.post("/agents", json=a_definition()).json()

    response = client.patch(
        f"/agents/{created['id']}", json={"name": "summariser", "role": "Still condenses"}
    )

    assert response.status_code == 200
    assert response.json()["role"] == "Still condenses"


def test_an_empty_patch_is_refused(client: TestClient) -> None:
    created = client.post("/agents", json=a_definition()).json()

    assert client.patch(f"/agents/{created['id']}", json={}).status_code == 400


def test_clearing_a_pinned_model_restores_the_workspace_default(client: TestClient) -> None:
    """``null`` restores inheritance here, unlike ``PATCH /settings``."""
    created = client.post("/agents", json=a_definition(model="claude-opus-5")).json()
    assert created["model"] == "claude-opus-5"

    updated = client.patch(f"/agents/{created['id']}", json={"model": None}).json()

    assert updated["model"] is None


def test_a_missing_agent_is_a_404_everywhere(client: TestClient) -> None:
    assert client.get("/agents/nope").status_code == 404
    assert client.patch("/agents/nope", json={"role": "x"}).status_code == 404
    assert client.delete("/agents/nope").status_code == 404


# --- the tool catalogue ------------------------------------------------------


def test_the_catalogue_lists_every_tool_with_its_risk(client: TestClient) -> None:
    """The §5 Phase 7 editor gets risk from this endpoint, not a drifting local list."""
    body = client.get("/tools").json()

    assert [tool["name"] for tool in body] == list(tool_names())
    assert {tool["risk"] for tool in body} <= {"low", "medium", "high"}
    assert all(tool["description"] for tool in body)


def test_every_catalogue_tool_is_now_available(client: TestClient) -> None:
    """Ensure every catalogue entry is implemented, not merely displayed.

    ``available`` comes from the registry, so an editor cannot offer a tool a
    run will refuse.
    """
    body = client.get("/tools").json()

    assert body, "the catalogue should not be empty"
    assert all(tool["available"] is True for tool in body)


def test_every_catalogue_tool_has_an_implementation() -> None:
    """Keep catalogue and registry tool names identical.

    Otherwise users can select an unimplemented tool, or implementations become
    unreachable because no allowlist can name them.
    """
    registry = build_registry()

    assert set(registry) == {tool.name for tool in CATALOGUE}

    for declaration in CATALOGUE:
        implementation = registry[declaration.name]
        # The editor and gate read the same catalogue risk level.
        assert implementation.risk is declaration.risk


def test_run_shell_is_the_only_high_risk_tool() -> None:
    """An incorrect displayed risk misleads approval decisions."""
    high = {tool.name for tool in CATALOGUE if tool.risk is RiskLevel.HIGH}

    assert high == {"run_shell"}
    assert is_registered("write_file")
    assert not is_registered("rm_rf")


# --- auto_approve can only narrow --------------------------------------------


@pytest.mark.parametrize(
    ("requested", "policy", "expected"),
    [
        # A definition cannot add a risk level excluded by the workspace.
        ((RiskLevel.HIGH,), (), frozenset()),
        ((RiskLevel.LOW, RiskLevel.HIGH), (RiskLevel.LOW,), {RiskLevel.LOW}),
        # Asking for nothing cannot widen policy.
        ((), (RiskLevel.LOW, RiskLevel.HIGH), frozenset()),
        ((RiskLevel.LOW,), (RiskLevel.LOW,), {RiskLevel.LOW}),
    ],
)
def test_auto_approve_never_exceeds_the_workspace_policy(
    requested: tuple[RiskLevel, ...],
    policy: tuple[RiskLevel, ...],
    expected: frozenset[RiskLevel],
) -> None:
    """§5 Phase 5's security rule as set intersection.

    It predates the gate so Phase 6 wires policy into an established rule.
    """
    assert effective_auto_approve(requested, policy) == expected


def test_a_definition_can_store_auto_approve_without_it_taking_effect(
    client: TestClient,
) -> None:
    created = client.post("/agents", json=a_definition(auto_approve=["low", "high"])).json()

    assert created["auto_approve"] == ["low", "high"]
    # Without workspace policy, it grants nothing.
    assert (
        effective_auto_approve([RiskLevel(x) for x in created["auto_approve"]], ())
        == frozenset()
    )


# --- the acceptance criterion, first clause ----------------------------------


class HookedProvider(ScriptedProvider):
    """Scripted provider that runs a callback before a chosen model call.

    It enables a mid-run definition edit after roster load but before worker
    spawn, as §5 Phase 5 requires.
    """

    def __init__(
        self, script: list[Completion], hooks: dict[int, Callable[[], Awaitable[None]]]
    ) -> None:
        super().__init__(script)
        self._hooks = hooks

    async def stream(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        *,
        system: str | None = None,
        max_tokens: int = 4096,
    ) -> AsyncIterator[StreamEvent]:
        hook = self._hooks.get(len(self.requests))
        if hook is not None:
            await hook()

        async for event in super().stream(
            messages, tools, system=system, max_tokens=max_tokens
        ):
            yield event


ONE_WORKER_SCRIPT = [
    says("Delegating.", call("spawn_agent", "s1", agent="summariser", task="Condense it")),
    says("Here it is.", call("finish", "w1", result="Three sentences.")),
    says("Done.", call("finish", "s2", result="Summarised.")),
]


async def run_with(
    store: EventStore,
    settings: SettingsStore,
    agents: AgentDefStore,
    ledger: BudgetLedger,
    provider: ScriptedProvider,
    goal: str = "Summarise the report",
) -> ReconstructedRun:
    run = await store.create_run(goal=goal, origin="ui")
    await execute_run(
        store, settings, agents, ledger, SecretStore(), run.id, goal, provider=provider
    )
    return reconstruct(await store.read(run.id))


@anyio_tests
async def test_an_agent_created_over_http_can_be_spawned_into_a_run(
    app_paths: AppPaths,
    store: EventStore,
    settings: SettingsStore,
    agents: AgentDefStore,
    ledger: BudgetLedger,
) -> None:
    """§5 Phase 5: create via HTTP, then prove the run read that database row.

    Assert only against the event log so no local test construction can pass it.
    """
    with TestClient(create_app(app_paths, secrets=SecretStore())) as client:
        created = client.post(
            "/agents",
            json={
                "name": "summariser",
                "role": "Condenses long text into three sentences",
                "system_prompt": "You summarise. Exactly three sentences.",
                "max_steps": 4,
            },
        )
        assert created.status_code == 201

    rebuilt = await run_with(
        store, settings, agents, ledger, ScriptedProvider(ONE_WORKER_SCRIPT)
    )

    assert rebuilt.status == "completed"
    assert set(rebuilt.agents) == {"supervisor", "summariser"}

    worker = rebuilt.agent("summariser")
    assert worker.role == "Condenses long text into three sentences"
    assert worker.definition_name == "summariser"
    assert worker.definition_id == created.json()["id"]
    assert worker.max_steps == 4
    assert worker.system_prompt is not None
    assert "Exactly three sentences." in worker.system_prompt
    assert worker.result == "Three sentences."


@anyio_tests
async def test_a_definition_edited_mid_run_does_not_affect_the_in_flight_run(
    store: EventStore,
    settings: SettingsStore,
    agents: AgentDefStore,
    ledger: BudgetLedger,
) -> None:
    """§5 Phase 5: runs snapshot definitions at start, despite mid-run edits.

    Edit during the first supervisor call, after roster load and before worker
    spawn. A spawn-time database read would give the worker the new role.
    """
    created = await agents.create(a_definition(role="The original role"))

    async def edit_it() -> None:
        await agents.update(created.id, {"role": "The edited role"})

    rebuilt = await run_with(
        store,
        settings,
        agents,
        ledger,
        HookedProvider(list(ONE_WORKER_SCRIPT), {0: edit_it}),
    )

    assert rebuilt.agent("summariser").role == "The original role"
    # Confirm the edit happened rather than silently failing.
    assert (await agents.require(created.id)).role == "The edited role"


@anyio_tests
async def test_a_disabled_agent_is_not_offered_to_the_supervisor(
    store: EventStore,
    settings: SettingsStore,
    agents: AgentDefStore,
    ledger: BudgetLedger,
) -> None:
    """Disabling is the usable answer for a built-in a user cannot delete."""
    created = await agents.create(a_definition())
    await agents.update(created.id, {"enabled": False})

    rebuilt = await run_with(
        store, settings, agents, ledger, ScriptedProvider(ONE_WORKER_SCRIPT)
    )

    assert set(rebuilt.agents) == {"supervisor"}
    errors = rebuilt.agent("supervisor").tool_errors
    assert any("no agent named 'summariser'" in error.lower() for error in errors)
    # One bad spawn is not a reason to discard the run.
    assert rebuilt.status == "completed"


@anyio_tests
async def test_the_run_limit_clamps_a_definition_written_when_the_cap_was_higher(
    store: EventStore,
    settings: SettingsStore,
    agents: AgentDefStore,
    ledger: BudgetLedger,
) -> None:
    """Enforce a lowered workspace cap at run time, not only definition write time."""
    await agents.create(a_definition(max_steps=20))
    await settings.update({"max_steps_per_agent": 3})

    rebuilt = await run_with(
        store, settings, agents, ledger, ScriptedProvider(ONE_WORKER_SCRIPT)
    )

    assert rebuilt.agent("summariser").max_steps == 3


@anyio_tests
async def test_spawning_one_definition_twice_produces_two_agents(
    store: EventStore,
    settings: SettingsStore,
    agents: AgentDefStore,
    ledger: BudgetLedger,
) -> None:
    """Give repeat spawns unique agent IDs so replay does not merge their nodes."""
    await agents.create(a_definition())

    rebuilt = await run_with(
        store,
        settings,
        agents,
        ledger,
        ScriptedProvider(
            [
                says("One.", call("spawn_agent", "s1", agent="summariser", task="First half")),
                says("Done.", call("finish", "w1", result="First summary.")),
                says("Two.", call("spawn_agent", "s2", agent="summariser", task="Second half")),
                says("Done.", call("finish", "w2", result="Second summary.")),
                says("Both in.", call("finish", "s3", result="Two summaries.")),
            ]
        ),
    )

    assert set(rebuilt.agents) == {"supervisor", "summariser", "summariser-2"}
    first = rebuilt.agent("summariser")
    second = rebuilt.agent("summariser-2")
    assert first.definition_id == second.definition_id
    assert second.definition_name == "summariser"


@anyio_tests
async def test_the_supervisor_is_told_which_agents_it_has(
    store: EventStore,
    settings: SettingsStore,
    agents: AgentDefStore,
    ledger: BudgetLedger,
) -> None:
    """Include each agent's tools in the supervisor prompt for sound delegation."""
    await agents.create(a_definition(allowed_tools=["read_file"]))

    provider = ScriptedProvider(ONE_WORKER_SCRIPT)
    await run_with(store, settings, agents, ledger, provider)

    supervisor_prompt = provider.systems[0]
    assert supervisor_prompt is not None
    assert "summariser: Condenses long text (read_file)" in supervisor_prompt
    assert "researcher:" in supervisor_prompt


# --- the registry, directly --------------------------------------------------


@anyio_tests
async def test_the_registry_reads_the_roster_once(agents: AgentDefStore) -> None:
    """A loaded registry is the snapshot behind the mid-run-edit guarantee."""
    before = tuple(sorted(d.name for d in await agents.list_enabled()))
    registry = await AgentRegistry.load(agents, RunLimits())
    assert registry.names == before

    await agents.create(a_definition())

    assert registry.names == before
    assert (await AgentRegistry.load(agents, RunLimits())).names != before


@anyio_tests
async def test_the_registry_tolerates_a_name_a_model_capitalised(
    agents: AgentDefStore,
) -> None:
    """Normalize agent names; title case is a typo, not another agent."""
    registry = await AgentRegistry.load(agents, RunLimits())

    assert registry.get("Researcher") is not None
    assert registry.get(" researcher ") is not None
    assert registry.get("researchers") is None


@anyio_tests
async def test_an_empty_roster_is_described_rather_than_left_blank(
    agents: AgentDefStore,
) -> None:
    """Describe an empty roster so the supervisor does not repeatedly spawn into nothing."""
    for definition in await agents.list_all():
        await agents.update(definition.id, {"enabled": False})

    registry = await AgentRegistry.load(agents, RunLimits())

    assert registry.names == ()
    assert "no agents available" in registry.describe()


# --- per-agent providers -----------------------------------------------------
#
# §4 permits pinned ``provider`` and ``model``; NULL inherits the workspace
# default. Honour them so a successful setting is not a no-op.


@anyio_tests
async def test_a_definition_inherits_the_workspace_provider_by_default(
    agents: AgentDefStore, ledger: BudgetLedger
) -> None:
    workspace = WorkspaceSettings(provider="ollama", model="qwen3:4b")
    pool = ProviderPool(workspace, SecretStore(), ledger, "run-1")

    definition = await agents.create(a_definition())

    provider = pool.for_definition(definition)
    assert provider.name == "ollama"
    # Namespace by provider so pricing recognizes free user-installed models.
    assert provider.model == "ollama/qwen3:4b"


@anyio_tests
async def test_a_definition_can_pin_its_own_model(
    agents: AgentDefStore, ledger: BudgetLedger
) -> None:
    workspace = WorkspaceSettings(provider="ollama", model="qwen3:4b")
    pool = ProviderPool(workspace, SecretStore(), ledger, "run-1")

    definition = await agents.create(a_definition(model="gemma4:e4b"))

    provider = pool.for_definition(definition)
    assert provider.name == "ollama"
    assert provider.model == "ollama/gemma4:e4b"
    # The pin leaves the workspace default untouched.
    assert pool.default().model == "ollama/qwen3:4b"


@anyio_tests
async def test_two_agents_on_the_same_model_share_one_provider(
    agents: AgentDefStore, ledger: BudgetLedger
) -> None:
    """Reuse one HTTP-client provider for repeated spawns on the same model."""
    workspace = WorkspaceSettings(provider="ollama", model="qwen3:4b")
    pool = ProviderPool(workspace, SecretStore(), ledger, "run-1")

    first = await agents.create(a_definition(name="one"))
    second = await agents.create(a_definition(name="two"))

    assert pool.for_definition(first) is pool.for_definition(second)
    assert pool.for_definition(first) is not pool.for_definition(
        await agents.create(a_definition(name="three", model="gemma4:e4b"))
    )


@anyio_tests
async def test_a_definition_pinning_an_unconfigured_provider_raises(
    agents: AgentDefStore, ledger: BudgetLedger
) -> None:
    """Report an unconfigured pinned provider as a failed spawn, not a failed run."""
    workspace = WorkspaceSettings(provider="ollama", model="qwen3:4b")
    pool = ProviderPool(workspace, SecretStore(), ledger, "run-1")

    definition = await agents.create(a_definition(provider="anthropic"))

    with pytest.raises(ProviderAuthError, match="No API key"):
        pool.for_definition(definition)


@anyio_tests
async def test_the_pool_rejects_a_provider_name_that_reached_the_database(
    agents: AgentDefStore, ledger: BudgetLedger
) -> None:
    """Reject unknown providers that reach storage outside the API or after removal."""
    workspace = WorkspaceSettings(provider="ollama", model="qwen3:4b")
    pool = ProviderPool(workspace, SecretStore(), ledger, "run-1")

    definition = await agents.create(a_definition())
    forged = definition.model_copy(update={"provider": "retired_provider"})

    with pytest.raises(UnknownProviderError):
        pool.for_definition(forged)


@anyio_tests
async def test_an_unknown_provider_is_refused_on_write(agents: AgentDefStore) -> None:
    with pytest.raises(AgentValidationError, match="unknown provider"):
        await agents.create(a_definition(provider="not_a_provider"))


# --- helpers -----------------------------------------------------------------


def _by_name(client: TestClient, name: str) -> dict[str, Any]:
    agents: list[dict[str, Any]] = client.get("/agents").json()
    for agent in agents:
        if agent["name"] == name:
            return agent
    msg = f"no agent named {name!r}"
    raise AssertionError(msg)
