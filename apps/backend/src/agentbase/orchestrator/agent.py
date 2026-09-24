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

import json
import logging
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TYPE_CHECKING, Any, Final

from agentbase.events.types import EventType
from agentbase.orchestrator.control import (
    SUPERVISOR_CONTROL_NAMES,
    WORKER_CONTROL_NAMES,
)
from agentbase.providers.base import (
    Completion,
    Message,
    ProviderError,
    Role,
    TextDelta,
)
from agentbase.tools.base import ToolArgumentError, ToolExecutionError
from agentbase.tools.catalogue import is_registered
from agentbase.tools.sandbox import SandboxViolationError, UrlNotAllowedError

if TYPE_CHECKING:
    from agentbase.orchestrator.run import Mailbox, Run
    from agentbase.providers.base import Provider, ToolCall, ToolSpec
    from agentbase.tools.catalogue import RiskLevel
    from agentbase.tools.runtime import ToolRuntime

__all__ = ["Agent", "AgentSpec", "StepOutcome", "ToolReply"]

logger = logging.getLogger("agentbase.orchestrator")

#: Sent when the model produces prose and calls nothing; without it a chatty
#: model burns every step saying it is about to begin.
_NO_TOOL_NUDGE: Final[str] = (
    "You did not call a tool. Call `finish` with your result if the task is "
    "done, or call another tool to make progress. Do not reply with prose alone."
)

#: The most output tokens one model answer may carry. 4096 cut a tool call
#: that wrote one large file to a broken half, which read as a missing
#: argument and was retried at full context until the step limit; every
#: model the price table lists accepts at least this.
MAX_OUTPUT_TOKENS: Final[int] = 16_384

#: The providers' words for "the answer hit the output limit".
_CUT_OFF_STOPS: Final[frozenset[str]] = frozenset({"max_tokens", "length"})

_CUT_OFF_NUDGE: Final[str] = (
    "Your answer was cut off at the output limit of {limit} tokens, so what "
    "you were writing could not be read{calls}. Do less in one answer: write a "
    "smaller file, or a part of it, and continue in your next step. Do not "
    "repeat the same oversized call."
)

#: How many times in a row the same call may fail the same way, or be made
#: with the same arguments, before the agent is stopped: a model that repeats
#: itself spends a full context window on each try and learns nothing from it.
MAX_SAME_FAILURES: Final[int] = 3

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
    #: An allowlist, never a denylist. Names from :mod:`agentbase.tools.catalogue`.
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
    #: The call did not do what was asked: refused, malformed, or it raised.
    failed: bool = False


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
        # The same failure, again and again, is how a model burns a step
        # budget: the key is the tool and its message, and a success resets it.
        last_failure: tuple[str, str] | None = None
        same_failures = 0

        for step in range(1, self._spec.max_steps + 1):
            self._run.check_deadline()
            await self._run.check_cost()

            await self._emit(EventType.AGENT_THINKING, {"step": step})

            completion = await self._call_model(messages, step)
            last_text = completion.text or last_text

            if completion.stop_reason in _CUT_OFF_STOPS:
                # A truncated answer's tool calls are half a call each: not
                # run, and the model is told why rather than shown a missing
                # argument it would only supply again.
                await self._cut_off(completion, messages)
                key = ("(answer)", "cut off at the output limit")
                same_failures = same_failures + 1 if key == last_failure else 1
                last_failure = key
                if same_failures >= MAX_SAME_FAILURES:
                    return await self._stuck(step, "the answer", key[1], same_failures)
                continue

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
                # A failure counts by its message; a success by its arguments,
                # since the identical call made again and again is a loop too.
                key = (
                    (call.name, outcome.content)
                    if outcome.failed
                    else (call.name, json.dumps(call.arguments, sort_keys=True, default=str))
                )
                same_failures = same_failures + 1 if key == last_failure else 1
                last_failure = key
                if same_failures >= MAX_SAME_FAILURES:
                    why = (
                        outcome.content
                        if outcome.failed
                        else "the same call with the same arguments, which had already answered"
                    )
                    return await self._stuck(step, call.name, why, same_failures)

        return await self._out_of_steps(last_text)

    async def _cut_off(self, completion: Completion, messages: list[Message]) -> None:
        """Record a truncated answer and tell the model what to do instead."""
        messages.append(Message(role=Role.ASSISTANT, content=completion.text or "(cut off)"))
        names = ", ".join(call.name for call in completion.tool_calls)
        for call in completion.tool_calls:
            await self._emit(
                EventType.TOOL_ERROR,
                {
                    "tool": call.name,
                    "call_id": call.id,
                    "error": (
                        f"{call.name} was not run: the answer was cut off at the output "
                        f"limit of {MAX_OUTPUT_TOKENS} tokens before the call was complete."
                    ),
                },
            )
        messages.append(
            Message(
                role=Role.USER,
                content=_CUT_OFF_NUDGE.format(
                    limit=MAX_OUTPUT_TOKENS,
                    calls=f", and the call to {names} did not happen" if names else "",
                ),
            )
        )

    async def _stuck(self, step: int, what: str, error: str, count: int) -> StepOutcome:
        """Stop an agent that keeps failing the same way, and say so to the supervisor."""
        result = (
            f"{self._spec.name} stopped: {what} failed the same way {count} times in a "
            f"row ({error}). It needs a different approach, not another try."
        )
        await self._mailbox.deliver(self._spec.name, self._supervisor, result)
        await self._emit(
            EventType.AGENT_COMPLETED, {"reason": "stuck", "steps": step, "error": error}
        )
        return StepOutcome(result=result, reason="stuck", steps=step)

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
                messages,
                self._tools,
                system=self._spec.system_prompt,
                max_tokens=MAX_OUTPUT_TOKENS,
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
        return ToolReply(reason, failed=True)

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
            return ToolReply(error, failed=True)

        try:
            prepared = tool.prepare(call.arguments, runtime.sandbox)
        except (SandboxViolationError, UrlNotAllowedError) as exc:
            return await self._sandbox_denied(call, str(exc))
        except ToolArgumentError as exc:
            await self._emit(
                EventType.TOOL_ERROR,
                {"tool": call.name, "call_id": call.id, "error": str(exc)},
            )
            return ToolReply(str(exc), failed=True)

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
            return ToolReply(decision.reason, failed=True)

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
            return ToolReply(str(exc), failed=True)
        except Exception as exc:
            # An unplanned exception in a tool must not take the run with it.
            logger.exception("tool %s failed in run %s", call.name, self._run.id)
            error = f"{call.name} failed unexpectedly: {exc}"
            await self._emit(
                EventType.TOOL_ERROR,
                {"tool": call.name, "call_id": call.id, "error": error},
            )
            return ToolReply(error, failed=True)

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
        return ToolReply(reason, failed=True)

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
        return ToolReply(error, failed=True)

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
