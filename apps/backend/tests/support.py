"""Shared test doubles and the event-log reducer every orchestration test reads.

**Why the reducer lives in `tests/` and not in `src/`.** §5 Phase 7 owns the
real one, in TypeScript, in `RunGraph`. A Python reducer shipped in the product
would be building ahead and a second implementation to keep in sync forever.

**Why it lives here and not inside one test module.** Phase 4 introduced it in
`test_orchestrator.py`; Phase 5 needs the same reconstruction to assert that a
denied tool call, and the definition an agent was built from, are recoverable
from the log alone. Two copies of a reducer is two answers to "what does the
log say", which is the drift §2 exists to prevent — in the tests as much as in
the product.

:func:`reconstruct` reads **nothing but the event rows**: no `runs` row, no
orchestrator object, no provider, no `agent_defs` table. If something a test
wants to assert is not derivable here, the log does not contain it — which is
exactly the failure the §5 Phase 4 acceptance criterion is about, and the one
§5 Phase 5 extends by making an agent's definition part of what a replay has to
be able to see.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from agentspace.events.types import Event, EventType
from agentspace.providers.base import Completion, TextDelta, TokenUsage, ToolCall

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from agentspace.providers.base import Message, StreamEvent, ToolSpec

__all__ = [
    "FakeClock",
    "ReconstructedAgent",
    "ReconstructedRun",
    "ScriptedProvider",
    "call",
    "reconstruct",
    "says",
]


# --- the scripted provider ---------------------------------------------------


class ScriptedProvider:
    """A provider that returns a fixed sequence of completions.

    Deterministic and free, so the acceptance criteria can be asserted on every
    run of the suite. It implements the whole protocol — including `stream`,
    which is the path the orchestrator actually takes — because a double that
    implements half of one is a double that proves half of what it appears to.
    """

    name = "scripted"
    model = "claude-opus-5"

    def __init__(self, script: list[Completion]) -> None:
        self._script = list(script)
        self.requests: list[list[Message]] = []
        self.systems: list[str | None] = []
        self.offered_tools: list[list[str]] = []

    def _next(
        self, messages: list[Message], tools: list[ToolSpec] | None, system: str | None
    ) -> Completion:
        self.requests.append(list(messages))
        self.systems.append(system)
        self.offered_tools.append([tool.name for tool in tools or []])

        if not self._script:
            msg = "the orchestrator asked for more model calls than the script has"
            raise AssertionError(msg)
        return self._script.pop(0)

    async def complete(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        *,
        system: str | None = None,
        max_tokens: int = 4096,
    ) -> Completion:
        return self._next(messages, tools, system)

    async def stream(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        *,
        system: str | None = None,
        max_tokens: int = 4096,
    ) -> AsyncIterator[StreamEvent]:
        completion = self._next(messages, tools, system)
        for word in completion.text.split():
            yield TextDelta(word + " ")
        yield completion


def says(
    text: str = "",
    *calls: ToolCall,
    input_tokens: int = 100,
    output_tokens: int = 50,
) -> Completion:
    return Completion(
        provider="scripted",
        model="claude-opus-5",
        text=text,
        usage=TokenUsage(input_tokens=input_tokens, output_tokens=output_tokens),
        tool_calls=calls,
        stop_reason="tool_use" if calls else "end_turn",
    )


class FakeClock:
    """A monotonic clock that reads a scripted sequence, then holds.

    Holding on the last value rather than raising `StopIteration` matters: the
    number of clock reads is an implementation detail of the loop, and a test
    that broke when one was added would be testing the wrong thing.
    """

    def __init__(self, *values: float) -> None:
        self._values = list(values)
        self._last = values[-1]

    def __call__(self) -> float:
        return self._values.pop(0) if self._values else self._last


def call(tool: str, call_id: str = "call_1", /, **arguments: Any) -> ToolCall:
    """Build a tool call.

    Both leading parameters are positional-only: a tool argument may legitimately
    be called `name` or `tool`, which would otherwise bind to this function's own
    parameters rather than landing in the call's arguments.
    """
    return ToolCall(id=call_id, name=tool, arguments=arguments)


# --- the reconstruction ------------------------------------------------------


@dataclass
class ReconstructedAgent:
    name: str
    role: str | None = None
    model: str | None = None
    provider: str | None = None
    steps: int = 0
    finished_reason: str | None = None
    result: str | None = None
    tool_calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    tool_errors: list[str] = field(default_factory=list)
    streamed_text: str = ""

    # --- Phase 5: what this agent was built from ---------------------------
    #
    # A run is only reconstructable if a replay can say *what an agent was*,
    # not merely that it existed. Once an agent is a row a user wrote, its
    # definition is the most load-bearing fact about it: two runs of the same
    # goal differ because the definitions differed.
    definition_id: str | None = None
    definition_name: str | None = None
    system_prompt: str | None = None
    allowed_tools: tuple[str, ...] = ()
    max_steps: int | None = None
    #: Tools this agent asked for and was refused, in order.
    denied_tools: list[str] = field(default_factory=list)
    #: Every tool name the agent asked for, whether or not it was permitted.
    requested_tools: list[str] = field(default_factory=list)


@dataclass
class ReconstructedRun:
    goal: str | None = None
    limits: dict[str, Any] = field(default_factory=dict)
    status: str = "running"
    outcome: str | None = None
    agents: dict[str, ReconstructedAgent] = field(default_factory=dict)
    handoffs: list[tuple[str, str, str]] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    budget_events: list[str] = field(default_factory=list)

    def agent(self, name: str) -> ReconstructedAgent:
        return self.agents[name]


def reconstruct(events: list[Event]) -> ReconstructedRun:
    """Rebuild what happened from the event log and nothing else.

    Deliberately has no access to the `runs` table, the `agent_defs` table, the
    orchestrator, or the provider.
    """
    run = ReconstructedRun()

    for event in events:
        payload = event.payload
        agent_id = event.agent_id

        if agent_id is not None and agent_id not in run.agents:
            run.agents[agent_id] = ReconstructedAgent(name=agent_id)
        agent = run.agents[agent_id] if agent_id is not None else None

        match event.type:
            case EventType.RUN_STARTED:
                run.goal = payload.get("goal")
                run.limits = payload.get("limits", {})
            case EventType.RUN_COMPLETED:
                run.status = "completed"
                run.outcome = payload.get("summary")
            case EventType.RUN_FAILED:
                run.status = "failed"
                run.outcome = payload.get("reason")
            case EventType.AGENT_SPAWNED if agent is not None:
                agent.role = payload.get("role")
                agent.model = payload.get("model")
                agent.provider = payload.get("provider")
                agent.definition_id = payload.get("definition_id")
                agent.definition_name = payload.get("definition_name")
                agent.system_prompt = payload.get("system_prompt")
                agent.allowed_tools = tuple(payload.get("allowed_tools") or ())
                agent.max_steps = payload.get("max_steps")
            case EventType.AGENT_THINKING if agent is not None:
                agent.steps = max(agent.steps, int(payload.get("step", 0)))
            case EventType.AGENT_COMPLETED if agent is not None:
                agent.finished_reason = payload.get("reason")
            case EventType.AGENT_MESSAGE if agent is not None:
                agent.result = payload.get("text")
            case EventType.AGENT_HANDOFF if agent is not None:
                run.handoffs.append(
                    (agent.name, str(payload.get("to")), str(payload.get("task")))
                )
            case EventType.LLM_TOKEN if agent is not None:
                agent.streamed_text += str(payload.get("text", ""))
            case EventType.LLM_RESPONSE:
                run.input_tokens += int(payload.get("input_tokens", 0))
                run.output_tokens += int(payload.get("output_tokens", 0))
            case EventType.TOOL_REQUESTED if agent is not None:
                agent.requested_tools.append(str(payload.get("tool")))
            case EventType.TOOL_DENIED if agent is not None:
                agent.denied_tools.append(str(payload.get("tool")))
            case EventType.TOOL_CALLED if agent is not None:
                agent.tool_calls.append(
                    (str(payload.get("tool")), dict(payload.get("args") or {}))
                )
            case EventType.TOOL_ERROR if agent is not None:
                agent.tool_errors.append(str(payload.get("error")))
            case EventType.BUDGET_EXCEEDED | EventType.BUDGET_WARNING:
                run.budget_events.append(str(event.type))
            case _:
                pass

    return run
