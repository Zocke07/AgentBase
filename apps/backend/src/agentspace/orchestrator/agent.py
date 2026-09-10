"""The worker agent loop: think, call a tool, observe, repeat.

§5 Phase 4 built the loop. §5 Phase 5 changed what an agent *is*: no longer a
name and a prompt the supervisor invented, but a row of `agent_defs` the user
wrote. :class:`AgentSpec` is the resolved form of that row — the snapshot a run
is held to, frozen at spawn.

Everything the loop does becomes an event before it has any other effect,
because the log is the only thing a replay gets to read (§2).

**Where the allowlist is enforced, and why it is here.** §5 Phase 5 requires
that an agent whose `allowed_tools` omits a tool cannot call it "even when its
system prompt explicitly instructs it to". Two things are needed for that and
only one of them is obvious:

1. The agent is not *offered* what it may not use. That is decided by whoever
   builds its `tools` list — see :mod:`agentspace.orchestrator.registry`.
2. The agent is not *permitted* what it may not use, checked against
   ``spec.allowed_tools`` at the moment of the call.

Only the second is a boundary. A model can name any tool string it likes
regardless of what it was shown — the `_unknown_tool` path below exists because
they do — so an orchestrator relying on step 1 alone would execute the call the
moment a model asked for something it was never offered. The two read different
sources on purpose, so neither can quietly become the other's proof.

**On what a tool is in this phase.** The only calls that actually *execute*
here end a turn, hand work over, or ask for a worker — see
:mod:`agentspace.orchestrator.control`. A catalogue tool an agent is permitted
still does not run, because permission from a definition is not permission from
the user, and collecting the latter is Phase 6's approval gate (§1 constraint
5). The event sequence is nonetheless the real one — `tool.requested`,
`tool.called`, `tool.result` — so Phase 6 adds the approval events between the
first two rather than reshaping what is already here.
"""

from __future__ import annotations

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
from agentspace.tools.catalogue import is_registered

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

#: Every control call that exists anywhere, used to tell "you may not have this"
#: apart from "this is not a thing". A worker asking for `spawn_agent` is being
#: refused a real capability; a worker asking for `frobnicate` is confused, and
#: a log that recorded both as denials would say nothing about either.
_ALL_CONTROL_NAMES: Final[frozenset[str]] = SUPERVISOR_CONTROL_NAMES | WORKER_CONTROL_NAMES


class _Permission(Enum):
    """What the agent is allowed to do with a tool call it just made."""

    #: A control call this agent holds. Executes.
    CONTROL = auto()
    #: A catalogue tool on this agent's allowlist. Permitted by the definition,
    #: but not executable until Phase 6's approval gate exists.
    AWAITING_GATE = auto()
    #: A real capability this agent does not have. `tool.denied`.
    DENIED = auto()
    #: Not a tool at all. `tool.error`.
    UNKNOWN = auto()


@dataclass(frozen=True, slots=True)
class AgentSpec:
    """What an agent is, resolved and frozen at the moment it spawns.

    Phase 4 built this from whatever the supervisor typed. Phase 5 builds it
    from a row of `agent_defs` — see
    :meth:`agentspace.orchestrator.registry.AgentRegistry.spec_for` — which is
    why the definition's identity travels with it: a replay has to be able to
    say not just that an agent ran but *what it was*, and the answer changed
    from "a string a model produced" to "a row a user wrote".

    Frozen for the same reason :class:`~agentspace.orchestrator.limits.RunLimits`
    is: §5 Phase 5 says "a definition edited mid-run does not affect the
    in-flight run", and a snapshot that can be mutated in place is not one.
    """

    name: str
    role: str
    system_prompt: str
    #: The `agent_defs` row this came from, or ``None`` for the supervisor,
    #: which is orchestration rather than a roster entry.
    definition_id: str | None = None
    #: The definition's own name, before `Run.register_agent` deduplicated it.
    #: ``name`` may be `researcher-2`; this stays `researcher`.
    definition_name: str | None = None
    #: An allowlist, never a denylist (§5 Phase 5). Names from
    #: :mod:`agentspace.tools.catalogue`.
    allowed_tools: tuple[str, ...] = ()
    #: Already clamped to the run's global ceiling by the registry.
    max_steps: int = 20
    #: Which control calls this agent holds. A worker's set does not contain
    #: `spawn_agent`, and that is a boundary rather than a presentation choice.
    control_names: frozenset[str] = field(default=WORKER_CONTROL_NAMES)

    def as_payload(self) -> dict[str, Any]:
        """The shape written into `agent.spawned`.

        The log is the only thing a replay gets to read, so what an agent was
        built from has to be in it. The system prompt is included because in
        Phase 5 it is *user-authored data* — the single most load-bearing fact
        about why two runs of the same goal behaved differently — and until now
        it appeared in no event at all: `llm.request` carries the message list,
        but the system prompt travels beside it as a separate provider argument.

        Once per agent rather than once per step: `llm.request` already repeats
        the transcript on every turn, and the prompt does not change.
        """
        return {
            "role": self.role,
            "definition_id": self.definition_id,
            "definition_name": self.definition_name,
            "system_prompt": self.system_prompt,
            "allowed_tools": list(self.allowed_tools),
            "max_steps": self.max_steps,
        }


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

    def _permit(self, name: str) -> _Permission:
        """Decide what this agent may do with a call to ``name``.

        Reads ``spec.allowed_tools`` and ``spec.control_names`` — never
        ``self._tools``. That separation is the point: `self._tools` is what the
        model was shown, and a model is free to ignore it.
        """
        if name in self._spec.control_names:
            return _Permission.CONTROL

        if name in self._spec.allowed_tools and is_registered(name):
            return _Permission.AWAITING_GATE

        # A real capability this agent does not hold, versus a name that means
        # nothing anywhere. Both stop the call; only the first is a denial.
        if is_registered(name) or name in _ALL_CONTROL_NAMES:
            return _Permission.DENIED

        return _Permission.UNKNOWN

    async def _handle_call(self, call: ToolCall, step: int) -> StepOutcome | ToolReply:
        """Emit the call's events, decide whether it may proceed, then dispatch.

        The order matters and is asserted by the tests: `tool.requested` is
        written *before* the permission check, so a replay shows what the agent
        tried to do rather than only that something failed. §5 Phase 5's claim
        is that a forbidden call is blocked, and "blocked" is only observable if
        the attempt is in the log beside the refusal.
        """
        details = {"tool": call.name, "args": call.arguments, "call_id": call.id}
        await self._emit(EventType.TOOL_REQUESTED, details)

        match self._permit(call.name):
            case _Permission.DENIED:
                return await self._denied(call)
            case _Permission.UNKNOWN:
                return await self._unknown_tool(call)
            case _Permission.AWAITING_GATE:
                return await self._awaiting_gate(call)
            case _Permission.CONTROL:
                pass

        # Phase 6 inserts the approval gate exactly here, between the decision
        # that an agent *may* call something and the record that it *did*.
        await self._emit(EventType.TOOL_CALLED, details)
        return await self._dispatch(call, step)

    async def _denied(self, call: ToolCall) -> ToolReply:
        """A real tool this agent's definition does not permit.

        §5 Phase 6 requires a sandbox denial to be "visible in the event log as
        `tool.denied`"; an allowlist denial is the same kind of fact and uses
        the same event. The agent is told plainly rather than being left to
        infer it — there is nothing to conceal from a model whose own
        capabilities these are, and a vague refusal just burns the next step.
        """
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

    async def _awaiting_gate(self, call: ToolCall) -> ToolReply:
        """Permitted by the definition, and still not executable.

        A definition's allowlist says which tools this agent *may* ask for. It
        does not say the user has agreed to any particular call, which is what
        §5 Phase 6's approval gate collects — so in Phase 5 the call stops here.
        No `tool.called` is written, because `tool.called` means the call
        executed and this one did not.
        """
        error = (
            f"{call.name!r} is not available yet: tool execution goes through an "
            f"approval gate that is not built. Continue without it, and say so in "
            f"your result."
        )
        await self._emit(
            EventType.TOOL_ERROR,
            {"tool": call.name, "call_id": call.id, "error": error},
        )
        return ToolReply(error)

    async def _dispatch(self, call: ToolCall, step: int) -> StepOutcome | ToolReply:
        """Carry out one control call.

        Overridden to add a control call, never to skip the events
        :meth:`_handle_call` has already written or the check it has made.

        The final fallback is unreachable while `control_names` and the branches
        here agree, and is here because that agreement is the sort that breaks
        silently: a control call added to the set but not to the dispatch would
        otherwise be treated as whatever the last branch happens to be.
        """
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
        steps = self._spec.max_steps
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
