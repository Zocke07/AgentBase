"""Turning `agent_defs` rows into running agents.

§5 Phase 5: "`registry.py` loads definitions from the DB at run start. It no
longer imports agent classes; it constructs workers from rows."

Two things live here, both answering "how does a row become an agent":

* :class:`AgentRegistry` — the roster a run was started with, frozen, plus the
  construction of an :class:`~agentspace.orchestrator.agent.AgentSpec` from one
  of its rows.
* :class:`ProviderPool` — which provider an agent talks to, since §4 lets a
  definition pin its own `provider` and `model` and inherit the workspace
  default when it does not.

**The roster is a snapshot, and that is a requirement rather than an
optimisation.** §5 Phase 5: "A definition edited mid-run does not affect the
in-flight run. Runs snapshot the definitions they started with; changing an
agent is not a way to mutate a running agent." So the rows are read once, in
:meth:`AgentRegistry.load`, and every spawn thereafter reads that tuple — never
the database. The same reasoning as
:class:`~agentspace.orchestrator.limits.RunLimits`: a run must not be held to
different rules at step 1 and step 12, and a replay has to be able to say what
the rules were.

**`max_steps` is clamped here, not only on write.**
:mod:`agentspace.store.agents` rejects a definition whose `max_steps` exceeds
the workspace cap, but the cap is a *setting* and can be lowered afterwards. A
rule enforced only at write time stops holding the moment the thing it depends
on changes, so the ceiling is applied again at the point of use.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from agentspace.budget.ledger import BudgetedProvider
from agentspace.orchestrator.agent import AgentSpec
from agentspace.orchestrator.control import (
    WORKER_CONTROL_NAMES,
    WORKER_TOOLS,
    catalogue_specs,
)
from agentspace.providers.factory import build_provider
from agentspace.tools.catalogue import lookup

if TYPE_CHECKING:
    import httpx2

    from agentspace.budget.ledger import BudgetLedger
    from agentspace.orchestrator.limits import RunLimits
    from agentspace.providers.base import Provider, ToolSpec
    from agentspace.secrets import SecretStore
    from agentspace.store.agents import AgentDef, AgentDefStore
    from agentspace.store.settings import WorkspaceSettings

__all__ = ["AgentRegistry", "ProviderPool", "compose_worker_prompt"]

#: Appended to every worker's user-authored system prompt.
#:
#: **This is mechanics, not privilege.** A definition's prompt says what the
#: agent is for; it cannot say how to end a turn, because the answer is a fact
#: about this orchestrator that a user writing a prompt has no reason to know.
#: Without it a perfectly reasonable prompt produces an agent that talks until
#: it runs out of steps.
#:
#: Nothing here grants anything. It names `finish` and `handoff`, which every
#: agent holds regardless of its allowlist (§5 Phase 5: an empty allowlist
#: still "can reason and hand off"), and says nothing about the tool catalogue —
#: what an agent may touch is decided by its row and enforced in
#: :meth:`~agentspace.orchestrator.agent.Agent._permit`, never by prompt text.
WORKER_PROTOCOL: Final[str] = (
    "You have been given one subtask as part of a larger job.\n\n"
    "When the subtask is done, call `finish` with your result — that is the "
    "only way to end your turn, and your result is the only thing passed back. "
    "If the subtask is genuinely outside your role, call `handoff` instead. "
    "Be concise and concrete."
)


def compose_worker_prompt(definition: AgentDef) -> str:
    """The system prompt a worker actually receives.

    The user's text first, so it reads as the agent's own instructions rather
    than as a footnote to boilerplate, and the protocol after it.
    """
    return f"{definition.system_prompt}\n\n{WORKER_PROTOCOL}"


@dataclass(frozen=True, slots=True)
class AgentRegistry:
    """The roster one run was started with, and how to build from it."""

    #: Enabled definitions only. A disabled row is not deleted, it is simply
    #: not something this run's supervisor can spawn.
    definitions: tuple[AgentDef, ...]
    #: The run's global `max_steps_per_agent`, applied over each row's own.
    max_steps_ceiling: int

    @classmethod
    async def load(cls, agents: AgentDefStore, limits: RunLimits) -> AgentRegistry:
        """Read the roster once, at run start."""
        return cls(
            definitions=tuple(await agents.list_enabled()),
            max_steps_ceiling=limits.max_steps_per_agent,
        )

    # --- the roster --------------------------------------------------------

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(definition.name for definition in self.definitions)

    def get(self, name: str) -> AgentDef | None:
        """Resolve a roster name, tolerating the case a model got wrong.

        Names are stored lowercase (see `store.agents.NAME_PATTERN`), and a
        model that title-cases one is making a typo rather than asking for a
        different agent. Matching exactly first keeps the common path honest.
        """
        for definition in self.definitions:
            if definition.name == name:
                return definition

        folded = name.strip().lower()
        for definition in self.definitions:
            if definition.name == folded:
                return definition
        return None

    def describe(self) -> str:
        """The roster as the supervisor is told about it.

        Includes each agent's tools because that is what makes a sensible
        choice possible: a supervisor that hands a file-writing subtask to an
        agent with an empty allowlist has picked the wrong agent, and it can
        only know that if it was told.
        """
        if not self.definitions:
            return (
                "You have no agents available. You will have to answer the goal "
                "yourself and call `finish`."
            )

        lines = []
        for definition in self.definitions:
            tools = ", ".join(definition.allowed_tools) or "no tools"
            lines.append(f"- {definition.name}: {definition.role} ({tools})")
        return "\n".join(lines)

    # --- construction ------------------------------------------------------

    def spec_for(self, definition: AgentDef, run_name: str) -> AgentSpec:
        """Build the frozen spec for one spawn of ``definition``.

        ``run_name`` is what `Run.register_agent` handed back, which may carry
        a deduplication suffix — spawning `researcher` twice produces
        `researcher` and `researcher-2`, two agents in the graph, one
        definition behind both.
        """
        return AgentSpec(
            name=run_name,
            role=definition.role,
            system_prompt=compose_worker_prompt(definition),
            definition_id=definition.id,
            definition_name=definition.name,
            allowed_tools=definition.allowed_tools,
            max_steps=min(definition.max_steps, self.max_steps_ceiling),
            control_names=WORKER_CONTROL_NAMES,
        )

    def tools_for(self, definition: AgentDef) -> list[ToolSpec]:
        """What this agent's model is shown.

        Exposure, not enforcement — see
        :meth:`agentspace.orchestrator.agent.Agent._permit` for the boundary. An
        unknown name in `allowed_tools` is skipped rather than raised on: the
        row was validated when it was written, and a run is not the place to
        discover that a tool was later removed from the catalogue.
        """
        declarations = [
            declaration
            for declaration in (lookup(name) for name in definition.allowed_tools)
            if declaration is not None
        ]
        return [*WORKER_TOOLS, *catalogue_specs(declarations)]


class ProviderPool:
    """Which provider each agent talks to.

    §4 lets a definition pin `provider` and `model`, with ``NULL`` meaning
    "inherit the workspace default". Honouring that is what stops the columns
    being decoration — this project has already shipped one setting that
    returned `200 OK` and changed nothing (see CLAUDE.md, Phase 4), and a
    per-agent model that silently did nothing would be the same bug wearing a
    different hat.

    Every provider handed out is wrapped in
    :class:`~agentspace.budget.ledger.BudgetedProvider`, so an agent with its
    own model is still refused when the monthly cap is reached. A pool rather
    than a fresh provider per spawn because each one holds an HTTP client, and
    a run that spawns the same definition five times should open one.
    """

    def __init__(
        self,
        workspace: WorkspaceSettings,
        secrets: SecretStore,
        ledger: BudgetLedger,
        run_id: str,
        client: httpx2.AsyncClient | None = None,
        override: Provider | None = None,
    ) -> None:
        self._workspace = workspace
        self._secrets = secrets
        self._ledger = ledger
        self._run_id = run_id
        self._client = client
        self._override = override
        self._cache: dict[tuple[str, str], Provider] = {}

    def default(self) -> Provider:
        """The workspace provider, used by the supervisor and by any definition
        that pins neither field."""
        return self.for_definition(None)

    def for_definition(self, definition: AgentDef | None) -> Provider:
        """Resolve, build and cache the provider this definition should use.

        :raises UnknownProviderError: for a provider name with no implementation.
        :raises ProviderAuthError: when the resolved provider needs a key that
            did not arrive over the stdin handshake. Both reach the supervisor
            as a `tool.error` on the spawn rather than failing the run — a
            definition pointing at an unconfigured provider is one bad row, not
            a reason to discard the work the other agents have done.
        """
        if self._override is not None:
            # A test's scripted provider. Still wrapped by the caller, so a test
            # cannot accidentally prove the cap holds on a path that bypasses it.
            return self._override

        settings = self._workspace
        if definition is not None and (
            definition.provider is not None or definition.model is not None
        ):
            settings = self._workspace.model_copy(
                update={
                    key: value
                    for key, value in (
                        ("provider", definition.provider),
                        ("model", definition.model),
                    )
                    if value is not None
                }
            )

        key = (settings.provider, settings.model)
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        provider = BudgetedProvider(
            build_provider(settings, self._secrets, self._client),
            self._ledger,
            self._run_id,
        )
        self._cache[key] = provider
        return provider
