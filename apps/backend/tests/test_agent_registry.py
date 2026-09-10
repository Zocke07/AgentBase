"""Agent definitions as data: the registry, its validation, and its API.

The §5 Phase 5 acceptance criterion's first clause is "an agent created
entirely through the API — never touching Python — can be spawned into a run".
:func:`test_an_agent_created_over_http_can_be_spawned_into_a_run` is that
sentence, and it is written to be un-fakeable: the definition is created with
`client.post`, and the only thing the test asserts against is the event log the
run produced. No Python object describing the agent is ever constructed by the
test.

The second clause — the allowlist — lives in `test_agent_allowlist.py`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from fastapi.testclient import TestClient

from agentspace.main import create_app
from agentspace.orchestrator import execute_run
from agentspace.orchestrator.limits import RunLimits
from agentspace.orchestrator.registry import AgentRegistry, ProviderPool
from agentspace.providers.base import ProviderAuthError
from agentspace.providers.factory import UnknownProviderError
from agentspace.secrets import SecretStore
from agentspace.store.agents import AgentValidationError
from agentspace.store.settings import WorkspaceSettings
from agentspace.tools.catalogue import (
    CATALOGUE,
    RiskLevel,
    effective_auto_approve,
    is_registered,
    tool_names,
)
from support import ReconstructedRun, ScriptedProvider, call, reconstruct, says

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable, Iterator

    from agentspace.budget.ledger import BudgetLedger
    from agentspace.config import AppPaths
    from agentspace.events.store import EventStore
    from agentspace.providers.base import Completion, Message, StreamEvent, ToolSpec
    from agentspace.store.agents import AgentDefStore
    from agentspace.store.settings import SettingsStore

anyio_tests = pytest.mark.anyio

#: The definitions migration 003 seeds.
BUILTINS = ("researcher", "reviewer", "writer")


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


def test_seeded_agents_touch_nothing(client: TestClient) -> None:
    """Every built-in ships with an empty allowlist.

    Not a placeholder: §5 Phase 5 says an empty array "means the agent can
    reason and hand off but touches nothing", which is exactly true in Phase 5
    because no tool is implemented. A built-in seeded with `write_file` would
    spend one of its steps discovering it cannot use it.
    """
    for agent in client.get("/agents").json():
        assert agent["allowed_tools"] == []
        assert agent["auto_approve"] == []


def test_a_builtin_is_editable(client: TestClient) -> None:
    """§5 Phase 5: built-ins are "editable but not deletable"."""
    researcher = _by_name(client, "researcher")

    response = client.patch(
        f"/agents/{researcher['id']}", json={"system_prompt": "You research quietly."}
    )

    assert response.status_code == 200
    assert response.json()["system_prompt"] == "You research quietly."
    assert response.json()["is_builtin"] is True


def test_a_builtin_is_not_deletable(client: TestClient) -> None:
    """`is_builtin = 1` guards the delete path *only*."""
    researcher = _by_name(client, "researcher")

    response = client.delete(f"/agents/{researcher['id']}")

    assert response.status_code == 409
    assert "cannot be deleted" in response.json()["detail"]
    # And it is still there.
    assert client.get(f"/agents/{researcher['id']}").status_code == 200


def test_a_user_defined_agent_is_deletable(client: TestClient) -> None:
    created = client.post("/agents", json=a_definition()).json()

    assert client.delete(f"/agents/{created['id']}").status_code == 204
    assert client.get(f"/agents/{created['id']}").status_code == 404


def test_a_caller_cannot_mint_a_builtin(client: TestClient) -> None:
    """`is_builtin` is not an input.

    If it were, a caller could create a definition that the delete path then
    refuses to remove — an undeletable row a user never asked to be permanent.
    """
    response = client.post("/agents", json=a_definition(is_builtin=True))

    assert response.status_code == 422


# --- validation --------------------------------------------------------------


@pytest.mark.parametrize(
    ("overrides", "field", "fragment"),
    [
        ({"name": "researcher"}, "name", "already exists"),
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
    """§5 Phase 5: "Reject at the API layer with a readable message, not a 500."

    The `field` in each body is what lets §5 Phase 7's editor put the message
    inline on the input that caused it rather than in a toast that loses which
    one was wrong.
    """
    response = client.post("/agents", json=a_definition(**overrides))

    assert response.status_code in {400, 409}
    detail = response.json()["detail"]
    assert detail["field"] == field
    assert fragment in detail["message"]


def test_an_agent_can_be_created_when_the_cap_is_below_the_default(
    client: TestClient,
) -> None:
    """Omitting `max_steps` must never be rejected *for* `max_steps`.

    §4 gives the column a default of 20. Asserting that literal in the request
    model made it impossible to create any agent at all once
    `max_steps_per_agent` was lowered below 20: the request was refused with a
    message naming a field the caller had not supplied, and the only way out
    was to guess that a hidden default had collided with the cap.

    Found by lowering the cap on a running sidecar and creating an ordinary
    agent — the whole suite was green, because every test until now either sent
    an explicit `max_steps` or left the cap at its default.
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
    """409 rather than 400: the input is well-formed, it collides with state
    the caller can see and resolve by choosing another name.

    Asserted on its own because the parametrized case above accepts either
    code, which is what let a duplicate quietly return 400 when an unrelated
    default tripped an earlier rule first.
    """
    response = client.post("/agents", json=a_definition(name="researcher"))

    assert response.status_code == 409
    assert response.json()["detail"]["field"] == "name"


def test_a_rejected_definition_is_not_written(client: TestClient) -> None:
    """A 400 that half-wrote a row would be worse than a 500."""
    client.post("/agents", json=a_definition(allowed_tools=["nope"]))

    assert [agent["name"] for agent in client.get("/agents").json()] == list(BUILTINS)


def test_an_unknown_field_is_rejected_rather_than_ignored(client: TestClient) -> None:
    """Pydantic's default is to drop it, which turns a misspelled field into a
    success that changed nothing. That exact bug shipped once already."""
    response = client.post("/agents", json=a_definition(max_stepss=4))

    assert response.status_code == 422
    assert "max_stepss" in response.text


def test_renaming_onto_an_existing_name_is_refused(client: TestClient) -> None:
    created = client.post("/agents", json=a_definition()).json()

    response = client.patch(f"/agents/{created['id']}", json={"name": "researcher"})

    assert response.status_code == 409


def test_renaming_an_agent_to_its_own_name_is_allowed(client: TestClient) -> None:
    """The uniqueness check has to exclude the row being updated, or saving an
    unchanged form is an error."""
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
    """`null` is meaningful here, so the update cannot drop null fields the way
    `PATCH /settings` does."""
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
    """§5 Phase 7's editor shows risk beside each checkbox, and reads it here
    rather than hardcoding a list that would drift from the validator."""
    body = client.get("/tools").json()

    assert [tool["name"] for tool in body] == list(tool_names())
    assert {tool["risk"] for tool in body} <= {"low", "medium", "high"}
    assert all(tool["description"] for tool in body)


def test_no_tool_is_available_before_the_approval_gate(client: TestClient) -> None:
    """§1 constraint 5. Phase 6 flips these, and not before."""
    assert all(tool["available"] is False for tool in client.get("/tools").json())


def test_run_shell_is_the_only_high_risk_tool() -> None:
    """A risk level that is wrong is worse than no risk level: it is what the
    user reads when deciding whether to tick the box."""
    high = {tool.name for tool in CATALOGUE if tool.risk is RiskLevel.HIGH}

    assert high == {"run_shell"}
    assert is_registered("write_file")
    assert not is_registered("rm_rf")


# --- auto_approve can only narrow --------------------------------------------


@pytest.mark.parametrize(
    ("requested", "policy", "expected"),
    [
        # The case §5 Phase 5 names: a definition cannot grant itself a level
        # the workspace has not enabled.
        ((RiskLevel.HIGH,), (), frozenset()),
        ((RiskLevel.LOW, RiskLevel.HIGH), (RiskLevel.LOW,), {RiskLevel.LOW}),
        # Nor does asking for nothing widen anything.
        ((), (RiskLevel.LOW, RiskLevel.HIGH), frozenset()),
        ((RiskLevel.LOW,), (RiskLevel.LOW,), {RiskLevel.LOW}),
    ],
)
def test_auto_approve_never_exceeds_the_workspace_policy(
    requested: tuple[RiskLevel, ...],
    policy: tuple[RiskLevel, ...],
    expected: frozenset[RiskLevel],
) -> None:
    """§5 Phase 5's security note, as arithmetic.

    Nothing consumes this in Phase 5 — there is no gate and no tool to put
    behind one. It is settled here so Phase 6 wires a workspace policy into a
    rule that already exists rather than inventing one while building the gate.
    """
    assert effective_auto_approve(requested, policy) == expected


def test_a_definition_can_store_auto_approve_without_it_taking_effect(
    client: TestClient,
) -> None:
    created = client.post("/agents", json=a_definition(auto_approve=["low", "high"])).json()

    assert created["auto_approve"] == ["low", "high"]
    # ...and with no workspace policy, it grants exactly nothing.
    assert (
        effective_auto_approve([RiskLevel(x) for x in created["auto_approve"]], ())
        == frozenset()
    )


# --- the acceptance criterion, first clause ----------------------------------


class HookedProvider(ScriptedProvider):
    """A scripted provider that runs a callback before a given model call.

    Needed for one test only: proving that editing a definition *while a run is
    in flight* leaves that run alone. Without a hook the edit can only land
    before the run starts or after it ends, neither of which is the case §5
    Phase 5 actually describes.
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
    """§5 Phase 5, acceptance criterion, first clause.

    The definition is created with an HTTP request against the same database
    the run then reads. Every assertion is made against the event log, so
    nothing here can pass by the test having built the agent itself.
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
    """§5 Phase 5: "A definition edited mid-run does not affect the in-flight
    run. Runs snapshot the definitions they started with."

    The edit lands during the supervisor's first model call — after the roster
    was loaded, before the worker is spawned. If the registry read the database
    at spawn time instead of at run start, the worker below would carry the new
    role and this test would fail.
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
    # The edit did happen — this is not passing because the write silently failed.
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
    """Validation on write is not the enforcement.

    `max_steps` is checked against the workspace cap when a definition is
    saved, but the cap is a setting and can be lowered afterwards. A rule
    enforced only at write time stops holding the moment the thing it depends
    on changes.
    """
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
    """Two agents sharing an `agent_id` would merge into one node on replay, so
    the second spawn of a definition is deduplicated — but both still point at
    the same row."""
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
    """The roster reaches the model through the system prompt, and it has to
    carry each agent's tools — a supervisor handing a file-writing subtask to
    an agent with an empty allowlist has picked wrong, and can only know that
    if it was told."""
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
    """The snapshot is the whole mechanism behind the mid-run-edit guarantee."""
    registry = await AgentRegistry.load(agents, RunLimits())
    assert registry.names == BUILTINS

    await agents.create(a_definition())

    assert registry.names == BUILTINS
    assert (await AgentRegistry.load(agents, RunLimits())).names != BUILTINS


@anyio_tests
async def test_the_registry_tolerates_a_name_a_model_capitalised(
    agents: AgentDefStore,
) -> None:
    """Names are stored lowercase, so a title-cased one is a typo rather than a
    request for a different agent."""
    registry = await AgentRegistry.load(agents, RunLimits())

    assert registry.get("Researcher") is not None
    assert registry.get(" researcher ") is not None
    assert registry.get("researchers") is None


@anyio_tests
async def test_an_empty_roster_is_described_rather_than_left_blank(
    agents: AgentDefStore,
) -> None:
    """A supervisor told nothing would spawn into the void every step until it
    ran out."""
    for definition in await agents.list_all():
        await agents.update(definition.id, {"enabled": False})

    registry = await AgentRegistry.load(agents, RunLimits())

    assert registry.names == ()
    assert "no agents available" in registry.describe()


# --- per-agent providers -----------------------------------------------------
#
# §4 lets a definition pin `provider` and `model`, with NULL meaning "inherit
# the workspace default". Honouring that is what stops those columns being
# decoration — this project has already shipped one setting that returned
# 200 OK and changed nothing.


@anyio_tests
async def test_a_definition_inherits_the_workspace_provider_by_default(
    agents: AgentDefStore, ledger: BudgetLedger
) -> None:
    workspace = WorkspaceSettings(provider="ollama", model="qwen3:4b")
    pool = ProviderPool(workspace, SecretStore(), ledger, "run-1")

    definition = await agents.create(a_definition())

    provider = pool.for_definition(definition)
    assert provider.name == "ollama"
    # Namespaced by the provider so `pricing` recognises it as free without
    # enumerating every model a user might have pulled.
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
    # ...while the workspace default is untouched by that pin.
    assert pool.default().model == "ollama/qwen3:4b"


@anyio_tests
async def test_two_agents_on_the_same_model_share_one_provider(
    agents: AgentDefStore, ledger: BudgetLedger
) -> None:
    """Each provider holds an HTTP client; a run spawning one definition five
    times should open one."""
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
    """Reported to the supervisor as a failed spawn rather than failing the run:
    one bad row should not discard what the other agents produced."""
    workspace = WorkspaceSettings(provider="ollama", model="qwen3:4b")
    pool = ProviderPool(workspace, SecretStore(), ledger, "run-1")

    definition = await agents.create(a_definition(provider="anthropic"))

    with pytest.raises(ProviderAuthError, match="No API key"):
        pool.for_definition(definition)


@anyio_tests
async def test_the_pool_rejects_a_provider_name_that_reached_the_database(
    agents: AgentDefStore, ledger: BudgetLedger
) -> None:
    """The API refuses an unknown provider on write; this is what holds if a row
    is edited some other way, or if a provider is later removed."""
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
