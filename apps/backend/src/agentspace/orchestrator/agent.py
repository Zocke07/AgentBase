"""The worker agent loop: think, call a tool, observe, repeat.

§5 Phase 4. Everything the loop does becomes an event before it has any other
effect, because the log is the only thing a replay gets to read (§2).

**On what a tool is in this phase.** The only calls offered here end a turn,
hand work over, or ask for a worker — see
:mod:`agentspace.orchestrator.control` for why nothing that touches the
filesystem, the shell or the network can exist before Phase 6's approval gate.
The event sequence is nonetheless the real one — `tool.requested`,
`tool.called`, `tool.result` — so Phase 6 adds the approval events between the
first two rather than reshaping what is already here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from agentspace.events.types import EventType
from agentspace.providers.base import (
    Completion,
    Message,
    ProviderError,
    Role,
    TextDelta,
)

if TYPE_CHECKING:
    from agentspace.orchestrator.run import Mailbox, Run
    from agentspace.providers.base import Provider, ToolCall, ToolSpec

__all__ = ["Agent", "AgentSpec", "StepOutcome", "ToolReply"]

#: What the model is told when it produces prose but calls nothing. Without a
#: nudge a chatty model burns every step saying it is about to begin.
_NO_TOOL_NUDGE: Final[str] = (
    "You did not call a tool. Call `finish` with your result if the task is "
    "done, or call another tool to make progress. Do not reply with prose alone."
)


@dataclass(frozen=True, slots=True)
class AgentSpec:
    """What an agent is, before it has run anything.

    Phase 5 replaces this with rows from `agent_defs`; keeping it a plain value
    object means that change is a different constructor, not a different loop.
    """

    name: str
    role: str
    system_prompt: str


@dataclass(frozen=True, slots=True)
class StepOutcome:
    """Why an agent's loop ended, and what it produced."""

    result: str
    reason: str
    steps: int


@dataclass(frozen=True, slots=True)
class ToolReply:
    """What a tool call hands back to the model so the loop can continue.

    Distinct from :class:`StepOutcome` because the two mean opposite things: an
    outcome ends the agent, a reply feeds the next turn. A single "string or
    None" return would collapse them and make "the agent finished" and "the
    tool said nothing" the same value.
    """

    content: str


class Agent:
    """One worker. Runs until it finishes, hands off, or runs out of steps."""

    def __init__(
        self,
        run: Run,
        mailbox: Mailbox,
        provider: Provider,
        spec: AgentSpec,
        tools: list[ToolSpec],
        supervisor_name: str,
    ) -> None:
        self._run = run
        self._mailbox = mailbox
        self._provider = provider
        self._spec = spec
        self._tools = tools
        self._supervisor = supervisor_name

    @property
    def name(self) -> str:
        return self._spec.name

    async def execute(self, task: str) -> StepOutcome:
        """Work the task until done, handed off, or out of steps."""
        messages: list[Message] = [Message(role=Role.USER, content=task)]
        last_text = ""

        for step in range(1, self._run.limits.max_steps_per_agent + 1):
            self._run.check_deadline()

            await self._emit(EventType.AGENT_THINKING, {"step": step})

            completion = await self._call_model(messages, step)
            last_text = completion.text or last_text

            if not completion.tool_calls:
                # Prose with no call. Keep it in the transcript so the next turn
                # has context, and tell the model what it must do instead.
                messages.append(Message(role=Role.ASSISTANT, content=completion.text))
                messages.append(Message(role=Role.USER, content=_NO_TOOL_NUDGE))
                continue

            messages.append(
                Message(role=Role.ASSISTANT, content=completion.text or "(tool call)")
            )

            for call in completion.tool_calls:
                outcome = await self._handle_call(call, step)
                if isinstance(outcome, StepOutcome):
                    return outcome

                messages.append(
                    Message(
                        role=Role.TOOL,
                        content=outcome.content,
                        tool_call_id=call.id,
                    )
                )

        return await self._out_of_steps(last_text)

    # --- the model ---------------------------------------------------------

    async def _call_model(self, messages: list[Message], step: int) -> Completion:
        """One streamed request, with every stage of it in the log."""
        await self._emit(
            EventType.LLM_REQUEST,
            {
                "provider": self._provider.name,
                "model": self._provider.model,
                "step": step,
                "messages": [
                    {"role": str(message.role), "content": message.content}
                    for message in messages
                ],
            },
        )

        completion: Completion | None = None
        try:
            async for event in self._provider.stream(
                messages, self._tools, system=self._spec.system_prompt
            ):
                if isinstance(event, TextDelta):
                    await self._emit(EventType.LLM_TOKEN, {"text": event.text})
                else:
                    completion = event
        except ProviderError as exc:
            await self._emit(EventType.LLM_ERROR, {"error": str(exc)})
            raise

        if completion is None:
            # The protocol guarantees a terminal completion. A provider that
            # ends without one is broken in a way the loop cannot paper over.
            msg = f"{self._provider.name} ended the stream with no completion"
            await self._emit(EventType.LLM_ERROR, {"error": msg})
            raise ProviderError(msg)

        await self._emit(
            EventType.LLM_RESPONSE,
            {
                "text": completion.text,
                "input_tokens": completion.usage.input_tokens,
                "output_tokens": completion.usage.output_tokens,
                "stop_reason": completion.stop_reason,
                "tool_calls": [
                    {"id": call.id, "name": call.name, "arguments": call.arguments}
                    for call in completion.tool_calls
                ],
            },
        )
        return completion

    # --- tool calls --------------------------------------------------------

    async def _handle_call(self, call: ToolCall, step: int) -> StepOutcome | ToolReply:
        """Emit the call's events, then dispatch it.

        The two halves are separate so a subclass can add a tool without
        restating — or quietly diverging from — the event sequence every call
        must produce.
        """
        await self._emit(
            EventType.TOOL_REQUESTED,
            {"tool": call.name, "args": call.arguments, "call_id": call.id},
        )

        # Phase 6 inserts the approval gate exactly here. Nothing reachable in
        # this phase touches the filesystem, the shell or the network, so there
        # is nothing yet for a gate to protect (§1 constraint 5).
        await self._emit(
            EventType.TOOL_CALLED,
            {"tool": call.name, "args": call.arguments, "call_id": call.id},
        )

        return await self._dispatch(call, step)

    async def _dispatch(self, call: ToolCall, step: int) -> StepOutcome | ToolReply:
        """Carry out one control call. Overridden to add tools, never to skip
        the events :meth:`_handle_call` has already written."""
        if call.name == "finish":
            return await self._finish(call, step)

        if call.name == "handoff":
            return await self._handoff(call, step)

        return await self._unknown_tool(call)

    async def _unknown_tool(self, call: ToolCall) -> ToolReply:
        """A model can name a tool that does not exist. That is a bad call, not
        a crashed run — it is told what it may actually use and tries again."""
        error = (
            f"{call.name!r} is not a tool you can call. Available tools: "
            f"{', '.join(tool.name for tool in self._tools)}."
        )
        await self._emit(
            EventType.TOOL_ERROR,
            {"tool": call.name, "call_id": call.id, "error": error},
        )
        return ToolReply(error)

    async def _finish(self, call: ToolCall, step: int) -> StepOutcome:
        result = _text_argument(call.arguments, "result")

        await self._emit(
            EventType.TOOL_RESULT,
            {"tool": call.name, "call_id": call.id, "result": result},
        )
        await self._mailbox.deliver(self._spec.name, self._supervisor, result)
        await self._emit(EventType.AGENT_COMPLETED, {"reason": "finished", "steps": step})
        return StepOutcome(result=result, reason="finished", steps=step)

    async def _handoff(self, call: ToolCall, step: int) -> StepOutcome:
        """A worker deciding the next step is not its job.

        The handoff is recorded and the agent completes; the supervisor reads
        the request in the worker's result and decides what to do with it. The
        worker does not get to spawn or command another agent directly — that
        would let any agent widen the run's shape from inside its own turn.
        """
        recipient = _text_argument(call.arguments, "to")
        task = _text_argument(call.arguments, "task")

        await self._emit(EventType.AGENT_HANDOFF, {"to": recipient, "task": task})
        await self._emit(
            EventType.TOOL_RESULT,
            {"tool": call.name, "call_id": call.id, "result": f"handed off to {recipient}"},
        )

        result = f"Handed off to {recipient}: {task}"
        await self._mailbox.deliver(self._spec.name, self._supervisor, result)
        await self._emit(EventType.AGENT_COMPLETED, {"reason": "handoff", "steps": step})
        return StepOutcome(result=result, reason="handoff", steps=step)

    async def _out_of_steps(self, last_text: str) -> StepOutcome:
        """§4 has no `agent.failed`, so a step limit *completes* with a reason."""
        steps = self._run.limits.max_steps_per_agent
        result = last_text or f"{self._spec.name} stopped after {steps} steps with no result."

        await self._mailbox.deliver(self._spec.name, self._supervisor, result)
        await self._emit(EventType.AGENT_COMPLETED, {"reason": "max_steps", "steps": steps})
        return StepOutcome(result=result, reason="max_steps", steps=steps)

    # --- plumbing ----------------------------------------------------------

    async def _emit(self, event_type: EventType, payload: dict[str, Any]) -> None:
        await self._run.emit(event_type, payload, agent_id=self._spec.name)


def _text_argument(arguments: dict[str, Any], key: str) -> str:
    """Read a string argument, tolerating a model that sent the wrong shape.

    A malformed argument is a bad tool call, not a crashed run — the same
    stance the provider adapters take when `arguments` will not parse.
    """
    value = arguments.get(key)
    if isinstance(value, str):
        return value
    return "" if value is None else str(value)
