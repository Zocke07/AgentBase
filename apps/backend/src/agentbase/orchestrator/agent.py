"""Worker agent loop: think, call a tool, observe, repeat.

An :class:`AgentSpec` freezes an ``agent_defs`` row at spawn. Emit every loop
effect before anything else because replay reads only the log (§2).

Enforce ``spec.allowed_tools`` at call time. Offering tools is necessary but
insufficient: models can name unseen strings, so exposure and enforcement use
different sources. Control calls (``finish``, ``handoff``, ``spawn_agent``)
touch nothing; catalogue calls use sandbox, approval gate, then execution (§1
constraint 5). Refuse out-of-workspace paths before composing an approval.
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

#: Sent after prose without a call; prevents chatty models burning steps on intent.
_NO_TOOL_NUDGE: Final[str] = (
    "You did not call a tool. Call `finish` with your result if the task is "
    "done, or call another tool to make progress. Do not reply with prose alone."
)

#: Maximum model output. 4096 cut a large-file tool call into an apparent
#: missing argument, retried at full context; every priced model accepts this.
MAX_OUTPUT_TOKENS: Final[int] = 16_384

#: The providers' words for "the answer hit the output limit".
_CUT_OFF_STOPS: Final[frozenset[str]] = frozenset({"max_tokens", "length"})

_CUT_OFF_NUDGE: Final[str] = (
    "Your answer was cut off at the output limit of {limit} tokens, so what "
    "you were writing could not be read{calls}. Do less in one answer: write a "
    "smaller file, or a part of it, and continue in your next step. Do not "
    "repeat the same oversized call."
)

#: Repeated identical failures or calls before stopping the agent; retries
#: spend a full context window without learning.
MAX_SAME_FAILURES: Final[int] = 3

#: All control calls distinguish denial from an unknown-tool error.
_ALL_CONTROL_NAMES: Final[frozenset[str]] = SUPERVISOR_CONTROL_NAMES | WORKER_CONTROL_NAMES


class _Permission(Enum):
    """Permission for the tool call just made."""

    #: Held control call; execute it.
    CONTROL = auto()
    #: Allowed catalogue tool: sandbox, gate, then execute.
    CATALOGUE = auto()
    #: Registered capability absent from this agent; ``tool.denied``.
    DENIED = auto()
    #: Unknown tool; ``tool.error``.
    UNKNOWN = auto()


@dataclass(frozen=True, slots=True)
class AgentSpec:
    """Agent identity resolved and frozen at spawn.

    Mid-run definition edits cannot affect it (§5 Phase 5); carry definition
    identity so replay knows what ran, not only that it ran.
    """

    name: str
    role: str
    system_prompt: str
    #: Source ``agent_defs`` row; ``None`` for supervisor.
    definition_id: str | None = None
    #: Definition name before :meth:`Run.register_agent` deduplication.
    definition_name: str | None = None
    #: Allowlist, never denylist; names from :mod:`agentbase.tools.catalogue`.
    allowed_tools: tuple[str, ...] = ()
    #: Requested pre-approval risks, intersected with workspace policy at call;
    #: can narrow but never widen it.
    auto_approve: tuple[RiskLevel, ...] = ()
    #: Registry-clamped run ceiling.
    max_steps: int = 20
    #: Held control calls; workers lack ``spawn_agent``.
    control_names: frozenset[str] = field(default=WORKER_CONTROL_NAMES)

    def as_payload(self) -> dict[str, Any]:
        """Build the ``agent.spawned`` payload.

        Include user-authored system prompt once: it explains divergent runs,
        while ``llm.request`` omits it.
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
    """Agent-loop exit reason and result."""

    result: str
    reason: str
    steps: int
    #: Handoff recipient and task when ``reason`` is ``"handoff"``.
    handoff: tuple[str, str] | None = None


@dataclass(frozen=True, slots=True)
class ToolReply:
    """Tool-call reply fed to the next model turn.

    Unlike :class:`StepOutcome`, it does not end the agent.
    """

    content: str
    #: Call was refused, malformed, or raised.
    failed: bool = False


class Agent:
    """Worker that runs until finish, handoff, or step exhaustion."""

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
        #: ``None`` permits no catalogue execution (supervisor); permitted
        #: calls then return ``tool.error``.
        self._runtime = runtime

    @property
    def name(self) -> str:
        return self._spec.name

    @property
    def spec(self) -> AgentSpec:
        return self._spec

    async def execute(self, task: str) -> StepOutcome:
        """Work until done, handed off, or out of steps."""
        messages: list[Message] = [Message(role=Role.USER, content=task)]
        last_text = ""
        # Track tool/message failures; success resets. Repeats burn step budget.
        last_failure: tuple[str, str] | None = None
        same_failures = 0

        for step in range(1, self._spec.max_steps + 1):
            self._run.check_deadline()
            await self._run.check_cost()

            await self._emit(EventType.AGENT_THINKING, {"step": step})

            completion = await self._call_model(messages, step)
            last_text = completion.text or last_text

            if completion.stop_reason in _CUT_OFF_STOPS:
                # Do not run truncated calls; explain rather than expose a
                # missing argument the model would resend.
                await self._cut_off(completion, messages)
                key = ("(answer)", "cut off at the output limit")
                same_failures = same_failures + 1 if key == last_failure else 1
                last_failure = key
                if same_failures >= MAX_SAME_FAILURES:
                    return await self._stuck(step, "the answer", key[1], same_failures)
                continue

            if not completion.tool_calls:
                # Preserve prose as context, then nudge a call.
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
                # Count failures by message and successes by arguments; both
                # can form a loop.
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
        """Record a truncated answer and give corrective guidance."""
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
        """Stop repeated failures and report them to the supervisor."""
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
        """Make one streamed request and log every stage."""
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
            # Provider protocol guarantees terminal completion.
            msg = f"{self._provider.name} ended the stream with no completion"
            await self._emit(EventType.LLM_ERROR, {"error": msg})
            raise ProviderError(msg)

        await self._emit(
            EventType.LLM_RESPONSE,
            {
                "text": completion.text,
                # Provider-exposed reasoning, if any; separate from ``text``.
                "thinking": completion.thinking,
                "input_tokens": completion.usage.input_tokens,
                "output_tokens": completion.usage.output_tokens,
                # ``None`` only from an unwrapped provider; app never builds one.
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
        """Decide whether this agent may call ``name``.

        Read spec, not ``self._tools``: models may ignore displayed tools.
        """
        if name in self._spec.control_names:
            return _Permission.CONTROL

        if name in self._spec.allowed_tools and is_registered(name):
            return _Permission.CATALOGUE

        # Distinguish unheld real capability from unknown name.
        if is_registered(name) or name in _ALL_CONTROL_NAMES:
            return _Permission.DENIED

        return _Permission.UNKNOWN

    async def _handle_call(self, call: ToolCall, step: int) -> StepOutcome | ToolReply:
        """Log a call, check permission, then dispatch.

        Write ``tool.requested`` before permission so replay includes attempts
        beside refusals.
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
        """Deny a registered tool absent from this definition as ``tool.denied``."""
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
        """Run permitted tool: sandbox, gate, then execution.

        Missing implementation/bad arguments yield ``tool.error``; sandbox or
        gate refusal yields ``tool.denied``. Emit ``tool.called`` only for runs.
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
            # Allowed valid call failed; inform agent and continue.
            await self._emit(
                EventType.TOOL_ERROR,
                {"tool": call.name, "call_id": call.id, "error": str(exc)},
            )
            return ToolReply(str(exc), failed=True)
        except Exception as exc:
            # Unexpected tool failure must not end the run.
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
        """Deny at sandbox layer before any approval."""
        await self._emit(
            EventType.TOOL_DENIED,
            {
                "tool": call.name,
                "args": call.arguments,
                "call_id": call.id,
                "reason": reason,
                # Distinguish sandbox attempt from declined dialog in replay.
                "blocked_by": "sandbox",
            },
        )
        return ToolReply(reason, failed=True)

    async def _dispatch(self, call: ToolCall, step: int) -> StepOutcome | ToolReply:
        """Execute one control call.

        Fallback is unreachable while ``control_names`` and branches agree but
        protects against silent drift.
        """
        if call.name == "finish":
            return await self._finish(call, step)

        if call.name == "handoff":
            return await self._handoff(call, step)

        return await self._unknown_tool(call)

    async def _unknown_tool(self, call: ToolCall) -> ToolReply:
        """Report an unknown tool as a bad call, not a crashed run."""
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
        """End a worker turn and let supervisor decide next step.

        Workers cannot spawn or command agents directly.
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
        """§4 has no ``agent.failed``; step limits complete with a reason."""
        steps = self._spec.max_steps
        result = last_text or f"{self._spec.name} stopped after {steps} steps with no result."

        await self._mailbox.deliver(self._spec.name, self._supervisor, result)
        await self._emit(EventType.AGENT_COMPLETED, {"reason": "max_steps", "steps": steps})
        return StepOutcome(result=result, reason="max_steps", steps=steps)

    # --- plumbing ----------------------------------------------------------

    async def _emit(self, event_type: EventType, payload: dict[str, Any]) -> None:
        await self._run.emit(event_type, payload, agent_id=self._spec.name)


def _text_argument(arguments: dict[str, Any], key: str) -> str:
    """Read a string argument while tolerating wrong model-provided shape."""
    value = arguments.get(key)
    if isinstance(value, str):
        return value
    return "" if value is None else str(value)
