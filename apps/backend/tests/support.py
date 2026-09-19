"""Shared test doubles and the event-log reducer every orchestration test reads.

The reducer lives in `tests/` because the real one is the TypeScript reducer,
and in one module because two copies would be two answers to "what does the
log say". :func:`reconstruct` reads nothing but the event rows: no `runs`
row, no orchestrator, no provider, no `agent_defs` table. If a test wants to
assert something not derivable here, the log does not contain it.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from agentspace.events.types import Event, EventType
from agentspace.providers.base import Completion, TextDelta, TokenUsage, ToolCall
from agentspace.tools.approval import ApprovalService, ApprovalStore
from agentspace.tools.runtime import ToolRuntime
from agentspace.tools.sandbox import Sandbox

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterable
    from pathlib import Path

    from agentspace.events.store import EventStore
    from agentspace.providers.base import Message, StreamEvent, ToolSpec
    from agentspace.store.db import Database
    from agentspace.tools.catalogue import RiskLevel

__all__ = [
    "FakeClock",
    "ReconstructedAgent",
    "ReconstructedRun",
    "ScriptedProvider",
    "StandingAnswer",
    "call",
    "reconstruct",
    "says",
    "tool_runtime",
]


# --- the approval gate, answered without a human -----------------------------


class StandingAnswer:
    """Answers every approval the same way, the instant it is asked.

    A test cannot click a dialog, and an unanswered gate blocks forever, so
    something has to stand in for the user. This subscribes to the service's
    own waiter registry rather than reimplementing the gate: the run still
    writes its `approvals` row, still emits `approval.requested` and
    `approval.resolved`, and still suspends on the real future. Only the
    *decision* is supplied from here.

    That distinction is the reason this is not a fake `ApprovalService`. A fake
    would make every gate test pass without the production gate ever running,
    which is precisely the class of test this project has already been bitten
    by: see CLAUDE.md on mutations that pass because the thing under test was
    never actually reached.
    """

    def __init__(self, service: ApprovalService, *, approve: bool) -> None:
        self._service = service
        self._approve = approve
        #: Every prompt a user would have been shown, in order. Tests assert on
        #: these to check §5 Phase 6's "human-legible, not raw JSON" clause.
        self.prompts: list[str] = []
        self._task: asyncio.Task[None] | None = None

    async def __aenter__(self) -> StandingAnswer:
        self._task = asyncio.create_task(self._answer_forever())
        return self

    async def __aexit__(self, *_: object) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def _answer_forever(self) -> None:
        """Poll for outstanding approvals and settle each one.

        Polling rather than a hook because the production code has no hook, and
        adding one purely for tests would put a seam in the gate that only
        tests use.
        """
        while True:
            for approval_id in list(self._service.waiting_on()):
                record = await self._service.store.get(approval_id)
                if record is not None:
                    self.prompts.append(f"{record.tool}: {record.risk}")
                with contextlib.suppress(Exception):
                    await self._service.resolve(approval_id, approved=self._approve)
            await asyncio.sleep(0.005)


def tool_runtime(
    store: EventStore,
    db: Database,
    root: Path,
    *,
    auto_approve: Iterable[RiskLevel] = (),
    tools: dict[str, Any] | None = None,
) -> tuple[ToolRuntime, ApprovalService]:
    """A real runtime over a real sandbox, gate and tool registry.

    Nothing here is a double except, optionally, the tool table itself. The
    sandbox is the production one rooted at ``root``, and the approval service
    is the production one writing to ``db``, so a test that reaches the
    filesystem is testing the thing that ships.
    """
    service = ApprovalService(ApprovalStore(db), store)
    runtime = ToolRuntime.build(Sandbox(root), service, auto_approve, tools=tools)
    return runtime, service


# --- the scripted provider ---------------------------------------------------


class ScriptedProvider:
    """A provider that returns a fixed sequence of completions.

    Deterministic and free, so the acceptance criteria can be asserted on every
    run of the suite. It implements the whole protocol (including `stream`,
    which is the path the orchestrator actually takes) because a double that
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
    thinking: str | None = None,
    stop_reason: str | None = None,
) -> Completion:
    return Completion(
        provider="scripted",
        model="claude-opus-5",
        text=text,
        usage=TokenUsage(input_tokens=input_tokens, output_tokens=output_tokens),
        tool_calls=calls,
        stop_reason=stop_reason or ("tool_use" if calls else "end_turn"),
        thinking=thinking,
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

    # --- Phase 6: the approval gate ----------------------------------------
    #
    # The whole point of the gate is that a user can answer afterwards the
    # question "what did this run do, and what did I agree to". That is only
    # answerable from the log if the request, the resolution and the execution
    # are each in it separately, so the reducer keeps them separate too.
    auto_approve: tuple[str, ...] = ()
    #: `(tool, risk)` for every approval this agent was asked to wait on.
    approvals_requested: list[tuple[str, str]] = field(default_factory=list)
    #: The human-legible sentence each approval put to the user. In the log
    #: rather than composed by the client, so a replay shows the words the user
    #: actually saw: §2 makes the UI a projection, and a client building its
    #: own wording could display one thing while the log recorded another.
    approval_prompts: list[str] = field(default_factory=list)
    #: `(tool, status)` for every approval that came back.
    approvals_resolved: list[tuple[str, str]] = field(default_factory=list)
    #: Tools that reached `tool.approved`, and whether policy did it silently.
    approved_tools: list[tuple[str, bool]] = field(default_factory=list)
    #: `(tool, reason)` for each denial: an allowlist refusal, a sandbox
    #: violation, or a user saying no.
    denials: list[tuple[str, str]] = field(default_factory=list)
    #: What blocked each denied call, when the payload says. `"sandbox"`
    #: distinguishes a traversal attempt from a declined dialog.
    denied_by: list[str | None] = field(default_factory=list)
    #: Results of tool calls that actually ran.
    tool_results: list[tuple[str, str]] = field(default_factory=list)


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
    cost_micros: int = 0
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
            case EventType.RUN_CANCELLED:
                run.status = "cancelled"
                run.outcome = payload.get("reason")
            case EventType.AGENT_SPAWNED if agent is not None:
                agent.role = payload.get("role")
                agent.model = payload.get("model")
                agent.provider = payload.get("provider")
                agent.definition_id = payload.get("definition_id")
                agent.definition_name = payload.get("definition_name")
                agent.system_prompt = payload.get("system_prompt")
                agent.allowed_tools = tuple(payload.get("allowed_tools") or ())
                agent.auto_approve = tuple(payload.get("auto_approve") or ())
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
                run.cost_micros += int(payload.get("cost_micros") or 0)
            case EventType.TOOL_REQUESTED if agent is not None:
                agent.requested_tools.append(str(payload.get("tool")))
            case EventType.TOOL_DENIED if agent is not None:
                agent.denied_tools.append(str(payload.get("tool")))
                agent.denials.append((str(payload.get("tool")), str(payload.get("reason"))))
                blocked = payload.get("blocked_by")
                agent.denied_by.append(str(blocked) if blocked is not None else None)
            case EventType.TOOL_APPROVED if agent is not None:
                agent.approved_tools.append(
                    (str(payload.get("tool")), bool(payload.get("automatic")))
                )
            case EventType.APPROVAL_REQUESTED if agent is not None:
                agent.approvals_requested.append(
                    (str(payload.get("tool")), str(payload.get("risk")))
                )
                agent.approval_prompts.append(str(payload.get("prompt")))
            case EventType.APPROVAL_RESOLVED if agent is not None:
                agent.approvals_resolved.append(
                    (str(payload.get("tool")), str(payload.get("status")))
                )
            case EventType.TOOL_CALLED if agent is not None:
                agent.tool_calls.append(
                    (str(payload.get("tool")), dict(payload.get("args") or {}))
                )
            case EventType.TOOL_RESULT if agent is not None:
                agent.tool_results.append(
                    (str(payload.get("tool")), str(payload.get("result")))
                )
            case EventType.TOOL_ERROR if agent is not None:
                agent.tool_errors.append(str(payload.get("error")))
            case EventType.BUDGET_EXCEEDED | EventType.BUDGET_WARNING:
                run.budget_events.append(str(event.type))
            case _:
                pass

    return run
