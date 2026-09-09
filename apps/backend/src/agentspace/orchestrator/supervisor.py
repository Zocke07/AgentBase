"""The supervisor: decompose a goal, spawn workers, delegate, report.

§5 Phase 4: "given a goal, decomposes into subtasks and spawns worker agents."

The supervisor is an :class:`~agentspace.orchestrator.agent.Agent` with one
extra call, `spawn_agent`. It runs the same loop, emits the same events, and is
subject to the same step limit — a supervisor that could not run out of steps
would be the one agent able to loop forever.

**Delegation is sequential.** A spawned worker runs to completion before the
supervisor's next turn. Running workers concurrently is a real feature, and it
is not this phase's: it would need the `seq` ordering under concurrent appends
to carry orchestration meaning it does not have, and the acceptance criterion
("the event log alone is sufficient to reconstruct exactly what happened")
should be met on the simple shape before it is claimed on the hard one.

**A worker's result reaches the supervisor through the log.** The supervisor
does not read the value :meth:`Agent.execute` returns; it reads the
`agent.message` row the worker wrote, via :class:`~agentspace.orchestrator.run.Mailbox`.
See that module for why.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentspace.events.types import EventType
from agentspace.orchestrator.agent import Agent, AgentSpec, StepOutcome, ToolReply
from agentspace.orchestrator.control import SUPERVISOR_TOOLS, WORKER_TOOLS
from agentspace.orchestrator.run import SpawnRefusedError

if TYPE_CHECKING:
    from agentspace.orchestrator.run import Mailbox, Run
    from agentspace.providers.base import Provider, ToolCall

__all__ = ["SUPERVISOR_NAME", "Supervisor", "supervisor_prompt", "worker_prompt"]

#: The supervisor's `agent_id` in the log. Fixed so a replay can find the root
#: of the graph without inferring it.
SUPERVISOR_NAME = "supervisor"


def supervisor_prompt(goal: str) -> str:
    return (
        "You are the supervisor of a small team of AI agents.\n\n"
        f"The user's goal is:\n{goal}\n\n"
        "Break this goal into the smallest number of subtasks that genuinely "
        "need doing. For each one, call `spawn_agent` with a short lowercase "
        "name, a one-line role, and the subtask. A worker runs to completion "
        "and its result comes back to you as the tool result.\n\n"
        "When you have everything you need, call `finish` with the complete "
        "answer to the user's goal. Do not call `finish` before you have "
        "delegated the work, and do not do the work yourself."
    )


def worker_prompt(role: str) -> str:
    return (
        f"You are a worker agent. Your role: {role}\n\n"
        "You have been given one subtask. Carry it out and call `finish` with "
        "your result. If the subtask is genuinely outside your role, call "
        "`handoff` instead. Be concise and concrete."
    )


class Supervisor(Agent):
    """An agent that can also create workers."""

    def __init__(
        self,
        run: Run,
        mailbox: Mailbox,
        provider: Provider,
        goal: str,
    ) -> None:
        super().__init__(
            run=run,
            mailbox=mailbox,
            provider=provider,
            spec=AgentSpec(
                name=SUPERVISOR_NAME,
                role="Plans the work and delegates it",
                system_prompt=supervisor_prompt(goal),
            ),
            tools=SUPERVISOR_TOOLS,
            # The supervisor reports to the user, not to another agent. Its
            # own `agent.message` is addressed there.
            supervisor_name="user",
        )
        self._provider = provider

    async def _dispatch(self, call: ToolCall, step: int) -> StepOutcome | ToolReply:
        if call.name == "spawn_agent":
            return await self._spawn(call)

        return await super()._dispatch(call, step)

    async def _spawn(self, call: ToolCall) -> ToolReply:
        """Create a worker, delegate to it, and report what it produced."""
        requested = _text(call.arguments, "name") or "worker"
        role = _text(call.arguments, "role") or "Carries out a subtask"
        task = _text(call.arguments, "task")

        try:
            name = self._run.register_agent(requested)
        except SpawnRefusedError as exc:
            # Not a run failure: the supervisor is told and carries on with the
            # workers it has. See `orchestrator.limits` for the reasoning.
            await self._emit(
                EventType.TOOL_ERROR,
                {"tool": call.name, "call_id": call.id, "error": str(exc)},
            )
            return ToolReply(str(exc))

        await self._run.emit(
            EventType.AGENT_SPAWNED,
            {
                "role": role,
                "provider": self._provider.name,
                "model": self._provider.model,
                "requested_name": requested,
            },
            agent_id=name,
        )
        await self._emit(EventType.AGENT_HANDOFF, {"to": name, "task": task})

        worker = Agent(
            run=self._run,
            mailbox=self._mailbox,
            provider=self._provider,
            spec=AgentSpec(name=name, role=role, system_prompt=worker_prompt(role)),
            tools=WORKER_TOOLS,
            supervisor_name=self.name,
        )
        await worker.execute(task)

        # Read the worker's result out of the log rather than off the return
        # value: if the `agent.message` was never written, the run stops here
        # instead of continuing on state the log does not contain.
        result = await self._mailbox.collect(sender=name, recipient=self.name)

        await self._emit(
            EventType.TOOL_RESULT,
            {"tool": call.name, "call_id": call.id, "agent": name, "result": result},
        )
        return ToolReply(f"Worker {name} reported:\n{result}")


def _text(arguments: dict[str, object], key: str) -> str:
    value = arguments.get(key)
    return value.strip() if isinstance(value, str) else ""
