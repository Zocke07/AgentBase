"""Supervisor: decompose goals, delegate roster work, report.

It is an :class:`~agentbase.orchestrator.agent.Agent` with ``spawn_agent``
and the same loop/step limit. It has no ``allowed_tools`` or catalogue access,
so every run's root agent touches nothing. Delegation is sequential; workers
return results via written ``agent.message`` rows, not Python return values.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from agentbase.events.types import EventType
from agentbase.orchestrator.agent import Agent, AgentSpec, StepOutcome, ToolReply
from agentbase.orchestrator.control import SUPERVISOR_CONTROL_NAMES, SUPERVISOR_TOOLS
from agentbase.orchestrator.run import SpawnRefusedError
from agentbase.providers.base import ProviderAuthError
from agentbase.providers.factory import UnknownProviderError

if TYPE_CHECKING:
    from agentbase.knowledge.store import KnowledgeStore
    from agentbase.orchestrator.registry import AgentRegistry, ProviderPool
    from agentbase.orchestrator.run import Mailbox, Run
    from agentbase.providers.base import Provider, ToolCall
    from agentbase.tools.runtime import ToolRuntime

__all__ = ["SUPERVISOR_NAME", "SUPERVISOR_ROLE", "Supervisor", "supervisor_prompt"]

logger = logging.getLogger("agentbase.orchestrator")

#: Fixed supervisor ``agent_id`` so replay can find the root.
SUPERVISOR_NAME = "supervisor"

SUPERVISOR_ROLE = "Plans the work and delegates it"


def supervisor_prompt(
    goal: str, roster: str, knowledge_context: str = "", time_note: str = ""
) -> str:
    """Build supervisor system prompt; roster differs per run, not per spawn."""
    knowledge = f"\n\n{knowledge_context}" if knowledge_context else ""
    started = f"{time_note}\n\n" if time_note else ""
    return (
        "You are the supervisor of a small team of AI agents.\n\n"
        f"The user's goal is:\n{goal}\n\n"
        f"{started}"
        "These agents are available to you:\n"
        f"{roster}\n\n"
        "Break the goal into the smallest number of subtasks that genuinely "
        "need doing, and use `spawn_agent` to give each one to the agent whose "
        "role fits it best. You must use one of the agent names listed above "
        "exactly as written. An agent runs to completion and its result comes "
        "back to you as the tool result.\n\n"
        "When you have everything you need, call `finish` with the complete "
        "answer to the user's goal. Do not call `finish` before you have "
        "delegated the work, and do not do the work yourself."
        f"{knowledge}"
    )


class Supervisor(Agent):
    """Agent that can delegate work to its roster."""

    def __init__(
        self,
        run: Run,
        mailbox: Mailbox,
        provider: Provider,
        goal: str,
        registry: AgentRegistry,
        providers: ProviderPool,
        runtime: ToolRuntime | None = None,
        knowledge: KnowledgeStore | None = None,
        space_id: str | None = None,
        knowledge_context: str = "",
        excluded_citations: frozenset[str] = frozenset(),
        time_note: str = "",
    ) -> None:
        super().__init__(
            run=run,
            mailbox=mailbox,
            provider=provider,
            spec=AgentSpec(
                name=SUPERVISOR_NAME,
                role=SUPERVISOR_ROLE,
                system_prompt=supervisor_prompt(
                    goal, registry.describe(), knowledge_context, time_note
                ),
                # No definition or allowlist.
                max_steps=run.limits.max_steps_per_agent,
                control_names=SUPERVISOR_CONTROL_NAMES,
            ),
            tools=SUPERVISOR_TOOLS,
            # Supervisor's ``agent.message`` goes to user.
            supervisor_name="user",
            # No runtime: without ``allowed_tools`` it is unreachable.
            runtime=None,
        )
        self._registry = registry
        self._providers = providers
        #: Worker runtime only; supervisor never uses it.
        self._runtime_for_workers = runtime
        self._knowledge = knowledge
        self._space_id = space_id
        self._excluded_citations = excluded_citations

    async def _dispatch(self, call: ToolCall, step: int) -> StepOutcome | ToolReply:
        if call.name == "spawn_agent":
            return await self._spawn(call)

        return await super()._dispatch(call, step)

    async def _spawn(self, call: ToolCall) -> ToolReply:
        """Put one roster agent to work and report its result.

        Every failure is ``tool.error`` and leaves run alive; one bad call must
        not destroy other work, while step limit stops an all-error supervisor.
        """
        requested = _text(call.arguments, "agent")
        task = _text(call.arguments, "task")

        definition = self._registry.get(requested) if requested else None
        if definition is None:
            return await self._spawn_error(
                call,
                f"There is no agent named {requested!r}. Available agents: "
                f"{', '.join(self._registry.names) or 'none'}.",
            )

        # Resolve provider before claiming a slot.
        try:
            provider = self._providers.for_definition(definition)
        except (UnknownProviderError, ProviderAuthError) as exc:
            return await self._spawn_error(call, f"Agent {definition.name!r} cannot run: {exc}")

        try:
            name = self._run.register_agent(definition.name)
        except SpawnRefusedError as exc:
            # Not a run failure; continue with existing workers.
            return await self._spawn_error(call, str(exc))

        spec = self._registry.spec_for(definition, name)

        await self._run.emit(
            EventType.AGENT_SPAWNED,
            {**spec.as_payload(), "provider": provider.name, "model": provider.model},
            agent_id=name,
        )
        await self._emit(EventType.AGENT_HANDOFF, {"to": name, "task": task})

        worker = Agent(
            run=self._run,
            mailbox=self._mailbox,
            provider=provider,
            spec=spec,
            tools=self._registry.tools_for(definition, self._runtime_for_workers),
            supervisor_name=self.name,
            runtime=self._runtime_for_workers,
        )
        worker_context = ""
        if self._knowledge is not None and self._space_id is not None:
            try:
                worker_context = await self._knowledge.context_for(
                    self._space_id,
                    task,
                    excluded_citations=set(self._excluded_citations),
                )
            except OSError:
                logger.exception("knowledge retrieval failed for worker %s", name)
        augmented_task = f"{task}\n\n{worker_context}" if worker_context else task
        outcome = await worker.execute(augmented_task)

        # Read log, not return value: missing durable result stops here.
        result = await self._mailbox.collect(sender=name, recipient=self.name)

        # Workers cannot spawn; handoffs return a request and roster guidance.
        payload: dict[str, Any] = {
            "tool": call.name,
            "call_id": call.id,
            "agent": name,
            "result": result,
        }
        guidance = ""
        if outcome.handoff is not None:
            recipient, asked = outcome.handoff
            known = self._registry.get(recipient) is not None
            payload["handoff"] = {"to": recipient, "known": known}
            if known:
                guidance = (
                    f"\n\nAgent {name} handed this off to {recipient!r} rather than "
                    f"finishing it. To continue, call spawn_agent with "
                    f"agent={recipient!r} and task={asked!r}, or decide otherwise."
                )
            else:
                guidance = (
                    f"\n\nAgent {name} handed this off to {recipient!r}, which is not on "
                    f"this roster. Available agents: "
                    f"{', '.join(self._registry.names) or 'none'}. Pick one of them, "
                    f"do without, or finish and say what could not be done."
                )

        await self._emit(EventType.TOOL_RESULT, payload)
        return ToolReply(f"Agent {name} reported:\n{result}{guidance}")

    async def _spawn_error(self, call: ToolCall, message: str) -> ToolReply:
        await self._emit(
            EventType.TOOL_ERROR,
            {"tool": call.name, "call_id": call.id, "error": message},
        )
        return ToolReply(message)


def _text(arguments: dict[str, object], key: str) -> str:
    value = arguments.get(key)
    return value.strip() if isinstance(value, str) else ""
