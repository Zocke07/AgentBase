"""The supervisor: decompose a goal, put agents to work, report.

§5 Phase 4: "given a goal, decomposes into subtasks and spawns worker agents."
§5 Phase 5 changed where those workers come from — the supervisor no longer
invents one by naming it, it chooses from the roster in `agent_defs`.

The supervisor is an :class:`~agentspace.orchestrator.agent.Agent` with one
extra control call, `spawn_agent`. It runs the same loop, emits the same
events, and is subject to the same step limit — a supervisor that could not run
out of steps would be the one agent able to loop forever.

**The supervisor is not itself a definition.** §5 Phase 5 says the registry
"constructs *workers* from rows", and the distinction is deliberate: the
supervisor is orchestration machinery, not a role a user would edit. It holds
no `allowed_tools` and can never reach the tool catalogue, so the one agent
present in every run is also the one that touches nothing. Its prompt is
generated from the goal and the roster, both of which are per-run facts.

**Delegation is sequential.** A spawned worker runs to completion before the
supervisor's next turn. Running workers concurrently is a real feature, and it
is not this phase's: it would need the `seq` ordering under concurrent appends
to carry orchestration meaning it does not have.

**A worker's result reaches the supervisor through the log.** The supervisor
does not read the value :meth:`Agent.execute` returns; it reads the
`agent.message` row the worker wrote, via :class:`~agentspace.orchestrator.run.Mailbox`.
See that module for why.
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

#: The supervisor's `agent_id` in the log. Fixed so a replay can find the root
#: of the graph without inferring it.
SUPERVISOR_NAME = "supervisor"

SUPERVISOR_ROLE = "Plans the work and delegates it"


def supervisor_prompt(goal: str, roster: str) -> str:
    """The supervisor's system prompt, including the roster it may draw on.

    The roster goes in the prompt rather than in `spawn_agent`'s description
    because it differs per run: it is whatever the user has defined and enabled
    at the moment the run started.
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
                # No definition, no allowlist: see the module docstring.
                max_steps=run.limits.max_steps_per_agent,
                control_names=SUPERVISOR_CONTROL_NAMES,
            ),
            tools=SUPERVISOR_TOOLS,
            # The supervisor reports to the user, not to another agent. Its
            # own `agent.message` is addressed there.
            supervisor_name="user",
            # Deliberately no runtime: the supervisor has no `allowed_tools`,
            # so `_permit` can never return CATALOGUE for it and a runtime
            # would be unreachable machinery. The one agent present in every
            # run is the one that touches nothing — see the module docstring.
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

        Every failure below is reported to the supervisor as a `tool.error` and
        leaves the run alive. A supervisor naming an agent that does not exist,
        asking for one worker too many, or picking a definition whose provider
        is not configured has made one bad call — destroying work the other
        agents have already done would trade real output for strictness. The
        step limit is what stops a supervisor that only ever makes bad calls.
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

        # Resolve the provider *before* claiming an agent slot: a definition
        # pointing at an unconfigured provider should not consume one of the
        # run's few spawns on its way to failing.
        try:
            provider = self._providers.for_definition(definition)
        except (UnknownProviderError, ProviderAuthError) as exc:
            return await self._spawn_error(call, f"Agent {definition.name!r} cannot run: {exc}")

        try:
            name = self._run.register_agent(definition.name)
        except SpawnRefusedError as exc:
            # Not a run failure: the supervisor is told and carries on with the
            # workers it has. See `orchestrator.limits` for the reasoning.
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

        # Read the worker's result out of the log rather than off the return
        # value: if the `agent.message` was never written, the run stops here
        # instead of continuing on state the log does not contain.
        result = await self._mailbox.collect(sender=name, recipient=self.name)

        # A worker cannot spawn, so a handoff comes back here as a request.
        # The shape — not the content — is read off the outcome, so this can
        # say whether the name is one the roster knows. Phase 6 watched a
        # worker hand off to a nonexistent agent and the supervisor do nothing
        # with it; what it is handed now is what to call, or why it cannot.
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
