"""Convert ``agent_defs`` rows into running agents.

:class:`AgentRegistry` loads a run's roster once; mid-run definition edits
cannot affect it (§5 Phase 5). :class:`ProviderPool` resolves definition-level
provider/model pins. Clamp ``max_steps`` here and on write because workspace
caps can drop after row creation.
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

#: Append orchestrator turn-ending protocol to every user-authored worker
#: prompt. It names only universally held ``finish``/``handoff`` and grants nothing.
WORKER_PROTOCOL: Final[str] = (
    "You have been given one subtask as part of a larger job.\n\n"
    "When the subtask is done, call `finish` with your result: that is the "
    "only way to end your turn, and your result is the only thing passed back. "
    "If the subtask is genuinely outside your role, call `handoff` instead. "
    "Be concise and concrete."
)


def compose_worker_prompt(definition: AgentDef) -> str:
    """Build worker system prompt: user text followed by protocol."""
    return f"{definition.system_prompt}\n\n{WORKER_PROTOCOL}"


@dataclass(frozen=True, slots=True)
class AgentRegistry:
    """Frozen run roster and builders for its agents."""

    #: Enabled definitions only.
    definitions: tuple[AgentDef, ...]
    #: Global ``max_steps_per_agent`` cap applied over each row's setting.
    max_steps_ceiling: int

    @classmethod
    async def load(
        cls, agents: AgentDefStore, limits: RunLimits, *, space_id: str = DEFAULT_SPACE_ID
    ) -> AgentRegistry:
        """Load one space's roster once at run start; exclude other-space rows."""
        return cls(
            definitions=tuple(await agents.list_enabled(space_id)),
            max_steps_ceiling=limits.max_steps_per_agent,
        )

    # --- the roster --------------------------------------------------------

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(definition.name for definition in self.definitions)

    def get(self, name: str) -> AgentDef | None:
        """Resolve a roster name, tolerating model-provided casing errors."""
        for definition in self.definitions:
            if definition.name == name:
                return definition

        folded = name.strip().lower()
        for definition in self.definitions:
            if definition.name == folded:
                return definition
        return None

    def describe(self) -> str:
        """Describe roster and tools to supervisor for delegation choices."""
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
        """Build frozen spec for one ``definition`` spawn.

        ``run_name`` comes from :meth:`Run.register_agent` and may carry a
        deduplication suffix (``researcher-2``).
        """
        return AgentSpec(
            name=run_name,
            role=definition.role,
            system_prompt=compose_worker_prompt(definition),
            definition_id=definition.id,
            definition_name=definition.name,
            allowed_tools=definition.allowed_tools,
            # Preserve request; ``ToolRuntime.auto_approve_for`` intersects it
            # with workspace policy exactly once.
            auto_approve=definition.auto_approve,
            max_steps=min(definition.max_steps, self.max_steps_ceiling),
            control_names=WORKER_CONTROL_NAMES,
        )

    def tools_for(
        self, definition: AgentDef, runtime: ToolRuntime | None = None
    ) -> list[ToolSpec]:
        """Return tools shown to this agent's model.

        This exposes, not enforces (:meth:`Agent._permit`). Skip allowlist
        entries lacking implementations; without ``runtime``, show controls only.
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
    """Resolve providers for agents.

    Definition pins override workspace provider/model; ``NULL`` inherits.
    Wrap every result in :class:`~agentbase.budget.ledger.BudgetedProvider` so
    pins still respect caps. Cache by provider/model because each holds HTTP client.
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
        """Return workspace provider for supervisor and unpinned definitions."""
        return self.for_definition(None)

    def for_definition(self, definition: AgentDef | None) -> Provider:
        """Resolve, build, and cache this definition's provider.

        :raises UnknownProviderError: for provider names without implementation.
        :raises ProviderAuthError: when required key did not arrive. Both reach
            supervisor as spawn ``tool.error``, not run failure.
        """
        if self._override is not None:
            # Scripted test provider still arrives budget-wrapped.
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
