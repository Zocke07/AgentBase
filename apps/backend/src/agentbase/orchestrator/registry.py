"""Turning `agent_defs` rows into running agents.

:class:`AgentRegistry` is the roster a run was started with, read once in
:meth:`AgentRegistry.load` and never re-read: a definition edited mid-run must
not affect the in-flight run (§5 Phase 5). :class:`ProviderPool` resolves which
provider each agent talks to, since a definition may pin its own `provider`
and `model`. `max_steps` is clamped here as well as on write, because the
workspace cap is a setting that can be lowered after a row is written.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from agentbase.budget.ledger import BudgetedProvider
from agentbase.orchestrator.agent import AgentSpec
from agentbase.orchestrator.control import (
    WORKER_CONTROL_NAMES,
    WORKER_TOOLS,
    catalogue_specs,
)
from agentbase.providers.factory import build_provider
from agentbase.store.spaces import DEFAULT_SPACE_ID

if TYPE_CHECKING:
    import httpx2

    from agentbase.budget.ledger import BudgetLedger
    from agentbase.orchestrator.limits import RunLimits
    from agentbase.providers.base import Provider, ToolSpec
    from agentbase.providers.chatgpt import ChatGPTInferenceRuntime
    from agentbase.secrets import SecretStore
    from agentbase.store.agents import AgentDef, AgentDefStore
    from agentbase.store.settings import WorkspaceSettings
    from agentbase.tools.runtime import ToolRuntime

__all__ = ["AgentRegistry", "ProviderPool", "compose_worker_prompt"]

#: Appended to every worker's user-authored system prompt: how to end a turn,
#: which is a fact about this orchestrator a prompt author cannot know. It
#: names only `finish` and `handoff`, which every agent holds, and grants nothing.
WORKER_PROTOCOL: Final[str] = (
    "You have been given one subtask as part of a larger job.\n\n"
    "When the subtask is done, call `finish` with your result: that is the "
    "only way to end your turn, and your result is the only thing passed back. "
    "If the subtask is genuinely outside your role, call `handoff` instead. "
    "Be concise and concrete."
)


def compose_worker_prompt(definition: AgentDef) -> str:
    """The system prompt a worker actually receives: the user's text, then the protocol."""
    return f"{definition.system_prompt}\n\n{WORKER_PROTOCOL}"


@dataclass(frozen=True, slots=True)
class AgentRegistry:
    """The roster one run was started with, and how to build from it."""

    #: Enabled definitions only.
    definitions: tuple[AgentDef, ...]
    #: The run's global `max_steps_per_agent`, applied over each row's own.
    max_steps_ceiling: int

    @classmethod
    async def load(
        cls, agents: AgentDefStore, limits: RunLimits, *, space_id: str = DEFAULT_SPACE_ID
    ) -> AgentRegistry:
        """Read one space's roster once, at run start.

        Another space's rows never reach this tuple.
        """
        return cls(
            definitions=tuple(await agents.list_enabled(space_id)),
            max_steps_ceiling=limits.max_steps_per_agent,
        )

    # --- the roster --------------------------------------------------------

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(definition.name for definition in self.definitions)

    def get(self, name: str) -> AgentDef | None:
        """Resolve a roster name, tolerating the case a model got wrong."""
        for definition in self.definitions:
            if definition.name == name:
                return definition

        folded = name.strip().lower()
        for definition in self.definitions:
            if definition.name == folded:
                return definition
        return None

    def describe(self) -> str:
        """The roster as the supervisor is told about it, tools included so it can choose."""
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

        ``run_name`` is what `Run.register_agent` handed back, possibly with a
        deduplication suffix (`researcher-2`).
        """
        return AgentSpec(
            name=run_name,
            role=definition.role,
            system_prompt=compose_worker_prompt(definition),
            definition_id=definition.id,
            definition_name=definition.name,
            allowed_tools=definition.allowed_tools,
            # As the definition asked, not as applied: the intersection with
            # the workspace policy happens once, in `ToolRuntime.auto_approve_for`.
            auto_approve=definition.auto_approve,
            max_steps=min(definition.max_steps, self.max_steps_ceiling),
            control_names=WORKER_CONTROL_NAMES,
        )

    def tools_for(
        self, definition: AgentDef, runtime: ToolRuntime | None = None
    ) -> list[ToolSpec]:
        """What this agent's model is shown.

        Exposure, not enforcement (that is :meth:`Agent._permit`). An allowlist
        entry with no implementation behind it is skipped, since offering it
        would spend the agent a step to find out. Without a ``runtime`` only
        the control calls are shown.
        """
        if runtime is None:
            return list(WORKER_TOOLS)

        tools = [
            tool
            for tool in (runtime.get(name) for name in definition.allowed_tools)
            if tool is not None
        ]
        return [*WORKER_TOOLS, *catalogue_specs(tools)]


class ProviderPool:
    """Which provider each agent talks to.

    A definition may pin `provider` and `model`; ``NULL`` inherits the
    workspace default. Every provider handed out is wrapped in
    :class:`~agentbase.budget.ledger.BudgetedProvider`, so a pinned model is
    still refused at the cap. Cached per (provider, model) because each holds
    an HTTP client.
    """

    def __init__(
        self,
        workspace: WorkspaceSettings,
        secrets: SecretStore,
        ledger: BudgetLedger,
        run_id: str,
        client: httpx2.AsyncClient | None = None,
        chatgpt_runtime: ChatGPTInferenceRuntime | None = None,
        override: Provider | None = None,
    ) -> None:
        self._workspace = workspace
        self._secrets = secrets
        self._ledger = ledger
        self._run_id = run_id
        self._client = client
        self._chatgpt_runtime = chatgpt_runtime
        self._override = override
        self._cache: dict[tuple[str, str, str], Provider] = {}

    def default(self) -> Provider:
        """The workspace provider: the supervisor's, and any definition that pins nothing."""
        return self.for_definition(None)

    def for_definition(self, definition: AgentDef | None) -> Provider:
        """Resolve, build and cache the provider this definition should use.

        :raises UnknownProviderError: for a provider name with no implementation.
        :raises ProviderAuthError: when the provider needs a key that did not
            arrive. Both reach the supervisor as a `tool.error` on the spawn
            rather than failing the run.
        """
        if self._override is not None:
            # A test's scripted provider; the caller still wraps it in the budget guard.
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

        key = (settings.provider, settings.model, settings.openai_access)
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        provider = BudgetedProvider(
            build_provider(
                settings,
                self._secrets,
                self._client,
                chatgpt_runtime=self._chatgpt_runtime,
            ),
            self._ledger,
            self._run_id,
        )
        self._cache[key] = provider
        return provider
