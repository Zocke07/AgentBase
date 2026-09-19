"""The worker agent loop: think, call a tool, observe, repeat.

An agent is :class:`AgentSpec`, the frozen form of an `agent_defs` row taken at
spawn. Everything the loop does becomes an event before it has any other
effect, because the log is the only thing a replay gets to read (§2).

The allowlist is enforced here, against ``spec.allowed_tools``, at the moment
of the call. Not *offering* a tool (the registry's job) is necessary and not
sufficient: a model can name any tool string it was never shown, so exposure
and enforcement read different sources on purpose.

Control calls (`finish`, `handoff`, `spawn_agent`) touch nothing and execute
directly. A catalogue tool reaches the disk, the shell or the network, so it
goes through :meth:`Agent._catalogue_call`: sandbox, then approval gate, then
execution, in that order (§1 constraint 5). A path outside the workspace is
refused before an approval prompt is composed; a question a user can answer
wrongly is not a boundary.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TYPE_CHECKING, Any, Final

from agentspace.events.types import EventType
from agentspace.orchestrator.control import (
    SUPERVISOR_CONTROL_NAMES,
    WORKER_CONTROL_NAMES,
)
from agentspace.providers.base import (
    Completion,
    Message,
    ProviderError,
    Role,
    TextDelta,
)
from agentspace.tools.base import ToolArgumentError, ToolExecutionError
from agentspace.tools.catalogue import is_registered
from agentspace.tools.sandbox import SandboxViolationError, UrlNotAllowedError

if TYPE_CHECKING:
    from agentspace.orchestrator.run import Mailbox, Run
    from agentspace.providers.base import Provider, ToolCall, ToolSpec
    from agentspace.tools.catalogue import RiskLevel
    from agentspace.tools.runtime import ToolRuntime

__all__ = ["Agent", "AgentSpec", "StepOutcome", "ToolReply"]

logger = logging.getLogger("agentspace.orchestrator")

#: Sent when the model produces prose and calls nothing; without it a chatty
#: model burns every step saying it is about to begin.
_NO_TOOL_NUDGE: Final[str] = (
    "You did not call a tool. Call `finish` with your result if the task is "
    "done, or call another tool to make progress. Do not reply with prose alone."
)

#: Every control call anywhere, so "you may not have this" (a denial) can be
#: told from "this is not a thing" (an error).
_ALL_CONTROL_NAMES: Final[frozenset[str]] = SUPERVISOR_CONTROL_NAMES | WORKER_CONTROL_NAMES


class _Permission(Enum):
    """What the agent is allowed to do with a tool call it just made."""

    #: A control call this agent holds. Executes.
    CONTROL = auto()
    #: A catalogue tool on this agent's allowlist. Sandbox, then gate, then execute.
    CATALOGUE = auto()
    #: A real capability this agent does not have. `tool.denied`.
    DENIED = auto()
    #: Not a tool at all. `tool.error`.
    UNKNOWN = auto()


@dataclass(frozen=True, slots=True)
class AgentSpec:
    """What an agent is, resolved and frozen at the moment it spawns.

    Frozen because a definition edited mid-run must not affect the in-flight
    run (§5 Phase 5); the definition's identity travels with it so a replay
    can say what the agent was, not only that it ran.
    """

    name: str
    role: str
    system_prompt: str
    #: The `agent_defs` row this came from; ``None`` for the supervisor.
    definition_id: str | None = None
    #: The definition's own name, before `Run.register_agent` deduplicated it.
    definition_name: str | None = None
    #: An allowlist, never a denylist. Names from :mod:`agentspace.tools.catalogue`.
    allowed_tools: tuple[str, ...] = ()
    #: Risk levels this definition asks to have pre-approved. Intersected with
    #: the workspace policy at the call: it can narrow that policy, never widen it.
    auto_approve: tuple[RiskLevel, ...] = ()
    #: Already clamped to the run's ceiling by the registry.
    max_steps: int = 20
    #: Which control calls this agent holds. A worker's set lacks `spawn_agent`.
    control_names: frozenset[str] = field(default=WORKER_CONTROL_NAMES)

    def as_payload(self) -> dict[str, Any]:
        """The shape written into `agent.spawned`.

        The system prompt is here, once per agent: it is user-authored and the
        most load-bearing fact about why two runs of one goal differed, and
        `llm.request` carries the message list without it.
        """
        return {
            "role": self.role,
            "definition_id": self.definition_id,
            "definition_name": self.definition_name,
            "system_prompt": self.system_prompt,
            "allowed_tools": list(self.allowed_tools),
            "auto_approve": [str(level) for level in self.auto_approve],
            "max_steps": self.max_steps,
        }


@dataclass(frozen=True, slots=True)
class StepOutcome:
    """Why an agent's loop ended, and what it produced."""

    result: str
    reason: str
    steps: int
    #: Set when ``reason`` is ``"handoff"``: who to, and what they were asked.
    handoff: tuple[str, str] | None = None


@dataclass(frozen=True, slots=True)
class ToolReply:
    """What a tool call hands back to the model so the loop can continue.

    A separate type from :class:`StepOutcome` because an outcome ends the
    agent and a reply feeds the next turn.
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
        runtime: ToolRuntime | None = None,
    ) -> None:
        self._run = run
        self._mailbox = mailbox
        self._provider = provider
        self._spec = spec
        self._tools = tools
        self._supervisor = supervisor_name
        #: ``None`` means no catalogue tool can execute (the supervisor's case);
        #: a permitted call then becomes a `tool.error` saying so.
        self._runtime = runtime

    @property
    def name(self) -> str:
        return self._spec.name

    @property
    def spec(self) -> AgentSpec:
        return self._spec

    async def execute(self, task: str) -> StepOutcome:
        """Work the task until done, handed off, or out of steps."""
        messages: list[Message] = [Message(role=Role.USER, content=task)]
        last_text = ""

        for step in range(1, self._spec.max_steps + 1):
            self._run.check_deadline()

            await self._emit(EventType.AGENT_THINKING, {"step": step})

            completion = await self._call_model(messages, step)
            last_text = completion.text or last_text

            if not completion.tool_calls:
                # Prose with no call: keep it for context, then nudge.
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
            # The protocol guarantees a terminal completion.
            msg = f"{self._provider.name} ended the stream with no completion"
            await self._emit(EventType.LLM_ERROR, {"error": msg})
            raise ProviderError(msg)

        await self._emit(
            EventType.LLM_RESPONSE,
            {
                "text": completion.text,
                # Reasoning the provider exposed, or None. Not part of `text`.
                "thinking": completion.thinking,
                "input_tokens": completion.usage.input_tokens,
                "output_tokens": completion.usage.output_tokens,
                # None only from an unwrapped provider, which the app never builds.
                "cost_micros": completion.cost_micros,
                "stop_reason": completion.stop_reason,
                "tool_calls": [
                    {"id": call.id, "name": call.name, "arguments": call.arguments}
                    for call in completion.tool_calls
                ],
            },
        )
        return completion

    # --- tool calls --------------------------------------------------------

    def _permit(self, name: str) -> _Permission:
        """Decide what this agent may do with a call to ``name``.

        Reads the spec, never ``self._tools``: that list is what the model was
        shown, and a model is free to ignore it.
        """
        if name in self._spec.control_names:
            return _Permission.CONTROL

        if name in self._spec.allowed_tools and is_registered(name):
            return _Permission.CATALOGUE

        # A real capability this agent lacks, versus a name that means nothing.
        if is_registered(name) or name in _ALL_CONTROL_NAMES:
            return _Permission.DENIED

        return _Permission.UNKNOWN

    async def _handle_call(self, call: ToolCall, step: int) -> StepOutcome | ToolReply:
        """Emit the call's events, decide whether it may proceed, then dispatch.

        `tool.requested` is written *before* the permission check, so a replay
        shows what the agent tried, beside the refusal.
        """
        details = {"tool": call.name, "args": call.arguments, "call_id": call.id}
        await self._emit(EventType.TOOL_REQUESTED, details)

        match self._permit(call.name):
            case _Permission.DENIED:
                return await self._denied(call)
            case _Permission.UNKNOWN:
                return await self._unknown_tool(call)
            case _Permission.CATALOGUE:
                return await self._catalogue_call(call)
            case _Permission.CONTROL:
                pass

        await self._emit(EventType.TOOL_CALLED, details)
        return await self._dispatch(call, step)

    async def _denied(self, call: ToolCall) -> ToolReply:
        """A real tool this agent's definition does not permit: `tool.denied`."""
        permitted = ", ".join(sorted(self._spec.allowed_tools)) or "none"
        reason = (
            f"{self._spec.name!r} is not permitted to call {call.name!r}. "
            f"Tools this agent may use: {permitted}. This is set by the agent's "
            f"definition and cannot be changed from inside the run."
        )
        await self._emit(
            EventType.TOOL_DENIED,
            {
                "tool": call.name,
                "args": call.arguments,
                "call_id": call.id,
                "reason": reason,
            },
        )
        return ToolReply(reason)

    async def _catalogue_call(self, call: ToolCall) -> ToolReply:
        """Sandbox, then gate, then execute: a permitted tool's whole journey.

        Each way it can stop is a different event: no implementation or bad
        arguments are `tool.error`; out of the sandbox or refused at the gate
        are `tool.denied`. `tool.called` is written only when the call runs.
        """
        runtime = self._runtime
        tool = runtime.get(call.name) if runtime is not None else None
        if runtime is None or tool is None:
            error = (
                f"{call.name!r} is not available in this run. Continue without "
                f"it, and say so in your result."
            )
            await self._emit(
                EventType.TOOL_ERROR,
                {"tool": call.name, "call_id": call.id, "error": error},
            )
            return ToolReply(error)

        try:
            prepared = tool.prepare(call.arguments, runtime.sandbox)
        except (SandboxViolationError, UrlNotAllowedError) as exc:
            return await self._sandbox_denied(call, str(exc))
        except ToolArgumentError as exc:
            await self._emit(
                EventType.TOOL_ERROR,
                {"tool": call.name, "call_id": call.id, "error": str(exc)},
            )
            return ToolReply(str(exc))

        decision = await runtime.approvals.request(
            run_id=self._run.id,
            agent=self._spec.name,
            prepared=prepared,
            risk=tool.risk,
            auto_approve=runtime.auto_approve_for(self._spec.auto_approve),
            deadline=self._run.remaining_seconds(),
            policy=runtime.policy_for(call.name, self._spec.auto_approve),
        )

        if not decision.allowed:
            await self._emit(
                EventType.TOOL_DENIED,
                {
                    "tool": call.name,
                    "args": call.arguments,
                    "call_id": call.id,
                    "approval_id": decision.approval_id,
                    "reason": decision.reason,
                },
            )
            return ToolReply(decision.reason)

        await self._emit(
            EventType.TOOL_APPROVED,
            {
                "tool": call.name,
                "call_id": call.id,
                "approval_id": decision.approval_id,
                "automatic": decision.automatic,
                "summary": prepared.summary,
            },
        )
        await self._emit(
            EventType.TOOL_CALLED,
            {"tool": call.name, "args": call.arguments, "call_id": call.id},
        )

        try:
            result = await tool.execute(prepared, runtime.sandbox)
        except ToolExecutionError as exc:
            # Allowed, correct, and failed anyway: the agent is told and keeps going.
            await self._emit(
                EventType.TOOL_ERROR,
                {"tool": call.name, "call_id": call.id, "error": str(exc)},
            )
            return ToolReply(str(exc))
        except Exception as exc:
            # An unplanned exception in a tool must not take the run with it.
            logger.exception("tool %s failed in run %s", call.name, self._run.id)
            error = f"{call.name} failed unexpectedly: {exc}"
            await self._emit(
                EventType.TOOL_ERROR,
                {"tool": call.name, "call_id": call.id, "error": error},
            )
            return ToolReply(error)

        await self._emit(
            EventType.TOOL_RESULT,
            {"tool": call.name, "call_id": call.id, "result": result},
        )
        return ToolReply(result)

    async def _sandbox_denied(self, call: ToolCall, reason: str) -> ToolReply:
        """Blocked at the sandbox layer, before anybody was asked."""
        await self._emit(
            EventType.TOOL_DENIED,
            {
                "tool": call.name,
                "args": call.arguments,
                "call_id": call.id,
                "reason": reason,
                # Tells a traversal attempt from a declined dialog on replay.
                "blocked_by": "sandbox",
            },
        )
        return ToolReply(reason)

    async def _dispatch(self, call: ToolCall, step: int) -> StepOutcome | ToolReply:
        """Carry out one control call.

        The fallback is unreachable while `control_names` and these branches
        agree; it is here because that agreement can break silently.
        """
        if call.name == "finish":
            return await self._finish(call, step)

        if call.name == "handoff":
            return await self._handoff(call, step)

        return await self._unknown_tool(call)

    async def _unknown_tool(self, call: ToolCall) -> ToolReply:
        """A tool that does not exist: a bad call, not a crashed run."""
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

        The worker completes and the supervisor decides what to do with the
        request; a worker cannot spawn or command another agent directly.
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
        return StepOutcome(
            result=result, reason="handoff", steps=step, handoff=(recipient, task)
        )

    async def _out_of_steps(self, last_text: str) -> StepOutcome:
        """§4 has no `agent.failed`, so a step limit *completes* with a reason."""
        steps = self._spec.max_steps
        result = last_text or f"{self._spec.name} stopped after {steps} steps with no result."

        await self._mailbox.deliver(self._spec.name, self._supervisor, result)
        await self._emit(EventType.AGENT_COMPLETED, {"reason": "max_steps", "steps": steps})
        return StepOutcome(result=result, reason="max_steps", steps=steps)

    # --- plumbing ----------------------------------------------------------

    async def _emit(self, event_type: EventType, payload: dict[str, Any]) -> None:
        await self._run.emit(event_type, payload, agent_id=self._spec.name)


def _text_argument(arguments: dict[str, Any], key: str) -> str:
    """Read a string argument, tolerating a model that sent the wrong shape."""
    value = arguments.get(key)
    if isinstance(value, str):
        return value
    return "" if value is None else str(value)
