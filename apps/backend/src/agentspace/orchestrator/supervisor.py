"""The supervisor: decompose a goal, put roster agents to work, report.

An :class:`~agentspace.orchestrator.agent.Agent` with one extra control call,
`spawn_agent`, the same loop and the same step limit. It is orchestration
machinery, not a definition: no `allowed_tools`, never a catalogue tool, so
the one agent in every run is the one that touches nothing. Delegation is
sequential, and a worker's result reaches the supervisor through the
`agent.message` row it wrote, not the return value.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agentspace.events.types import EventType
from agentspace.orchestrator.agent import Agent, AgentSpec, StepOutcome, ToolReply
from agentspace.orchestrator.control import SUPERVISOR_CONTROL_NAMES, SUPERVISOR_TOOLS
from agentspace.orchestrator.run import SpawnRefusedError
from agentspace.providers.base import ProviderAuthError
from agentspace.providers.factory import UnknownProviderError

if TYPE_CHECKING:
    from agentspace.orchestrator.registry import AgentRegistry, ProviderPool
    from agentspace.orchestrator.run import Mailbox, Run
    from agentspace.providers.base import Provider, ToolCall
    from agentspace.tools.runtime import ToolRuntime

__all__ = ["SUPERVISOR_NAME", "SUPERVISOR_ROLE", "Supervisor", "supervisor_prompt"]

#: The supervisor's `agent_id` in the log: fixed, so a replay can find the root.
SUPERVISOR_NAME = "supervisor"

SUPERVISOR_ROLE = "Plans the work and delegates it"


def supervisor_prompt(goal: str, roster: str) -> str:
    """The supervisor's system prompt.

    The roster is here, not in `spawn_agent`, because it differs per run.
    """
    return (
        "You are the supervisor of a small team of AI agents.\n\n"
        f"The user's goal is:\n{goal}\n\n"
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
    )


class Supervisor(Agent):
    """An agent that can also put the roster to work."""

    def __init__(
        self,
        run: Run,
        mailbox: Mailbox,
        provider: Provider,
        goal: str,
        registry: AgentRegistry,
        providers: ProviderPool,
        runtime: ToolRuntime | None = None,
    ) -> None:
        super().__init__(
            run=run,
            mailbox=mailbox,
            provider=provider,
            spec=AgentSpec(
                name=SUPERVISOR_NAME,
                role=SUPERVISOR_ROLE,
                system_prompt=supervisor_prompt(goal, registry.describe()),
                # No definition, no allowlist.
                max_steps=run.limits.max_steps_per_agent,
                control_names=SUPERVISOR_CONTROL_NAMES,
            ),
            tools=SUPERVISOR_TOOLS,
            # The supervisor's own `agent.message` is addressed to the user.
            supervisor_name="user",
            # No runtime: with no `allowed_tools` it would be unreachable.
            runtime=None,
        )
        self._registry = registry
        self._providers = providers
        #: Handed to the workers this supervisor spawns, never used by itself.
        self._runtime_for_workers = runtime

    async def _dispatch(self, call: ToolCall, step: int) -> StepOutcome | ToolReply:
        if call.name == "spawn_agent":
            return await self._spawn(call)

        return await super()._dispatch(call, step)

    async def _spawn(self, call: ToolCall) -> ToolReply:
        """Put one roster agent to work, and report what it produced.

        Every failure here is a `tool.error` that leaves the run alive: one
        bad call should not destroy the other agents' work, and the step
        limit stops a supervisor that only makes bad calls.
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

        # Before claiming an agent slot, so a bad provider does not spend one.
        try:
            provider = self._providers.for_definition(definition)
        except (UnknownProviderError, ProviderAuthError) as exc:
            return await self._spawn_error(call, f"Agent {definition.name!r} cannot run: {exc}")

        try:
            name = self._run.register_agent(definition.name)
        except SpawnRefusedError as exc:
            # Not a run failure: the supervisor carries on with the workers it has.
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
        outcome = await worker.execute(task)

        # From the log, not the return value: a result the log lacks stops the run here.
        result = await self._mailbox.collect(sender=name, recipient=self.name)

        # A worker cannot spawn, so a handoff comes back as a request, with
        # what to call or why the name is not on the roster.
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
