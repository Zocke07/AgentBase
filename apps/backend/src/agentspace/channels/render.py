"""The chat reply, as a pure fold of the event log.

§2: "the UI is a pure projection of the event log". A chat message is a second
projection of the same log, and this module is that projection: no I/O, no
platform, no clock, nothing but events in and a string out. The adapter
re-renders from scratch on every edit rather than appending, for the reason
Phase 7 gave about live versus replay: an accumulating renderer and a rebuilding
one agree until one of them gains a feature. Here there is only the rebuilding
one, so a reconnect, a resume or a restart shows what the log says rather than
what this process happened to witness.

**Plain text, no markdown.** Agent output is arbitrary text (file contents,
shell output, model prose), and Discord's markdown turns a stray `*`, `_` or
backtick in it into formatting, or swallows it. The decision was originally
forced by Telegram's MarkdownV2, where an unescaped character is a 400 that
discards the whole message; Telegram is gone and the reasoning survives it.
One renderer, no escaping, nothing to get wrong.

**The terminal summary is a claim, and it is rendered beside a count of what
executed.** This is Phase 7's decision carried across unchanged, and it matters
more here than there. Four live runs in this project have ended `completed`
with a summary describing work the log shows never happened: `finish` called by
an agent that never called `write_file` at all. A dashboard user can look at the
event log and see the disagreement. A chat user cannot see anything except this
message, so the message has to carry the check itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final, Literal, assert_never

from agentspace.events.types import EventType

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from agentspace.events.types import Event

__all__ = [
    "DISCORD_MESSAGE_LIMIT",
    "AgentLine",
    "ChatView",
    "PendingApproval",
    "RunClaim",
    "fold",
    "render",
]

#: Discord rejects a message body over this outright, rather than truncating.
DISCORD_MESSAGE_LIMIT: Final[int] = 2000

#: How many activity lines to keep before clamping starts trimming them. A
#: chat message is a status board, not a log dump; the log is in the dashboard.
MAX_ACTIVITY_LINES: Final[int] = 12

ChatStatus = Literal["pending", "running", "completed", "failed", "cancelled"]
AgentState = Literal["spawned", "thinking", "waiting", "done"]


def _text(payload: dict[str, Any], key: str, default: str = "") -> str:
    value = payload.get(key)
    return value if isinstance(value, str) else default


def _ellipsise(value: str, limit: int) -> str:
    collapsed = " ".join(value.split())
    return collapsed if len(collapsed) <= limit else collapsed[: limit - 1] + "…"


@dataclass(frozen=True, slots=True)
class AgentLine:
    """One agent, as a chat reader needs it: who, what for, and how it is doing."""

    name: str
    role: str = ""
    state: AgentState = "spawned"
    steps: int = 0
    reason: str = ""


@dataclass(frozen=True, slots=True)
class PendingApproval:
    """A question the run is currently suspended on."""

    approval_id: str
    agent: str
    prompt: str
    risk: str = "medium"


@dataclass(frozen=True, slots=True)
class RunClaim:
    """A terminal event's own account of itself.

    ``kind`` separates the two, because only one of them is a claim about work
    that may not have happened: a `run.failed` reason is written by this
    application and a `run.completed` summary is written by a model.
    """

    kind: Literal["summary", "failure"]
    text: str


@dataclass(frozen=True, slots=True)
class ChatView:
    """Everything the chat reply shows, derived from events and nothing else."""

    run_id: str | None = None
    goal: str | None = None
    origin: str | None = None
    identity: str | None = None
    status: ChatStatus = "pending"
    claim: RunClaim | None = None
    agents: tuple[AgentLine, ...] = ()
    approvals: tuple[PendingApproval, ...] = ()
    activity: tuple[str, ...] = ()
    tool_calls: int = 0
    denials: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    event_count: int = 0


@dataclass
class _Accumulator:
    """Mutable working state. :func:`fold` freezes it into a `ChatView`."""

    run_id: str | None = None
    goal: str | None = None
    origin: str | None = None
    identity: str | None = None
    status: ChatStatus = "pending"
    claim: RunClaim | None = None
    agents: dict[str, AgentLine] = field(default_factory=dict)
    approvals: dict[str, PendingApproval] = field(default_factory=dict)
    activity: list[str] = field(default_factory=list)
    tool_calls: int = 0
    denials: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    event_count: int = 0

    def note(self, line: str) -> None:
        self.activity.append(line)
        if len(self.activity) > MAX_ACTIVITY_LINES:
            del self.activity[0]

    def agent(self, name: str) -> AgentLine:
        return self.agents.get(name, AgentLine(name=name))

    def set_agent(self, name: str, **changes: Any) -> None:
        current = self.agent(name)
        self.agents[name] = AgentLine(
            name=name,
            role=changes.get("role", current.role),
            state=changes.get("state", current.state),
            steps=changes.get("steps", current.steps),
            reason=changes.get("reason", current.reason),
        )


def fold(events: Iterable[Event]) -> ChatView:
    """Reduce an event log into everything the chat reply needs.

    Deliberately one function with one `match`, mirroring the TypeScript
    reducer's single `switch`. §4's note that adding an event type means
    updating the reducer applies to this one too, and a reader checking whether
    that was done should have exactly one place to look per projection.
    """
    state = _Accumulator()
    for event in events:
        _apply(state, event)
    return _freeze(state)


def _apply(state: _Accumulator, event: Event) -> None:
    payload = event.payload or {}
    agent = event.agent_id or ""
    state.event_count += 1
    state.run_id = event.run_id

    match event.type:
        case EventType.CHANNEL_INBOUND:
            state.origin = _text(payload, "channel") or None
            identity = payload.get("identity")
            state.identity = identity if isinstance(identity, str) else None

        case EventType.CHANNEL_OUTBOUND:
            pass

        case EventType.RUN_STARTED:
            state.goal = _text(payload, "goal") or None
            state.status = "running"

        case EventType.RUN_COMPLETED:
            state.status = "completed"
            state.claim = RunClaim("summary", _text(payload, "summary"))

        case EventType.RUN_FAILED:
            state.status = "failed"
            state.claim = RunClaim("failure", _text(payload, "reason"))

        case EventType.RUN_CANCELLED:
            state.status = "cancelled"
            state.claim = RunClaim("failure", _text(payload, "reason", "Cancelled."))

        case EventType.RUN_PAUSED:
            state.status = "running"

        case EventType.AGENT_SPAWNED:
            state.set_agent(agent, role=_text(payload, "role"), state="spawned")

        case EventType.AGENT_THINKING:
            step = payload.get("step")
            state.set_agent(agent, state="thinking", steps=step if isinstance(step, int) else 0)

        case EventType.AGENT_MESSAGE:
            state.note(f"{agent}: {_ellipsise(_text(payload, 'text'), 110)}")

        case EventType.AGENT_HANDOFF:
            state.note(f"{agent} → {_text(payload, 'to', '?')}")

        case EventType.AGENT_COMPLETED:
            steps = payload.get("steps")
            state.set_agent(
                agent,
                state="done",
                reason=_text(payload, "reason", "done"),
                steps=steps if isinstance(steps, int) else state.agent(agent).steps,
            )

        # `llm.token` changes no state at all, and that is the point. Anthropic
        # coalesces 1-10 deltas unpredictably and a pure tool-call response
        # emits none, so a UI treating tokens as liveness reads a working agent
        # as idle. `agent.thinking` and `llm.request` are the liveness signals.
        case EventType.LLM_TOKEN | EventType.LLM_REQUEST | EventType.LLM_RESPONSE:
            pass

        case EventType.LLM_ERROR | EventType.TOOL_ERROR:
            state.errors.append(_ellipsise(_text(payload, "error"), 140))

        case EventType.TOOL_REQUESTED | EventType.TOOL_APPROVED:
            pass

        case EventType.TOOL_CALLED:
            state.tool_calls += 1
            state.note(f"{agent} → {_text(payload, 'tool', '?')}")

        case EventType.TOOL_RESULT:
            state.note(f"{agent} ← {_ellipsise(_text(payload, 'result'), 100)}")

        case EventType.TOOL_DENIED:
            blocked = _text(payload, "blocked_by")
            where = f" [{blocked}]" if blocked else ""
            state.denials.append(
                f"{_text(payload, 'tool', '?')}{where}: "
                f"{_ellipsise(_text(payload, 'reason'), 90)}"
            )

        case EventType.APPROVAL_REQUESTED:
            approval_id = _text(payload, "approval_id")
            if approval_id:
                state.approvals[approval_id] = PendingApproval(
                    approval_id=approval_id,
                    agent=agent,
                    prompt=_text(payload, "prompt"),
                    risk=_text(payload, "risk", "medium"),
                )
                state.set_agent(agent, state="waiting")

        case EventType.APPROVAL_RESOLVED:
            state.approvals.pop(_text(payload, "approval_id"), None)

        case EventType.BUDGET_WARNING:
            state.note(_text(payload, "reason", "Budget warning."))

        case EventType.BUDGET_EXCEEDED:
            state.errors.append(_text(payload, "reason", "Monthly budget exceeded."))

        case _:
            # Unreachable, and that is the point. `assert_never` makes
            # `mypy --strict` prove this match covers every member of
            # `EventType`, so adding an event type without teaching this fold
            # about it is a **build failure** rather than a chat reply that
            # quietly says less than the log does.
            #
            # This is deliberately stronger than the TypeScript reducer's
            # `default` branch, which records the type in `unrecognised` and
            # renders it. The asymmetry is real: the browser is a separately
            # built artefact that can lag the server it is talking to, so it has
            # to handle a type it has never heard of at runtime. This fold is
            # compiled from the same enum it is folding, so the question can be
            # settled before the process starts. `Event.type` is a validated
            # `EventType` (a row with an unknown type string fails in
            # `EventStore._row_to_event`), so nothing reaches this at runtime.
            assert_never(event.type)


def _freeze(state: _Accumulator) -> ChatView:
    return ChatView(
        run_id=state.run_id,
        goal=state.goal,
        origin=state.origin,
        identity=state.identity,
        status=state.status,
        claim=state.claim,
        agents=tuple(state.agents.values()),
        approvals=tuple(state.approvals.values()),
        activity=tuple(state.activity),
        tool_calls=state.tool_calls,
        denials=tuple(state.denials),
        errors=tuple(state.errors),
        event_count=state.event_count,
    )


# --- rendering ---------------------------------------------------------------

_STATUS_MARK: Final[dict[str, str]] = {
    "pending": "·",
    "running": "▶",
    "completed": "✓",
    "failed": "✗",
    "cancelled": "✗",
}


def _sections(view: ChatView) -> list[list[str]]:
    """The message as blocks, most valuable first for the clamp to work with."""
    head = [f"{_STATUS_MARK.get(view.status, '·')} {view.goal or 'Run'}"]
    where = view.origin or "chat"
    who = f" · {view.identity}" if view.identity else ""
    head.append(f"   {where}{who} · {view.status}")

    blocks = [head]

    if view.agents:
        agents = ["Agents"]
        for line in view.agents:
            detail = line.reason if line.state == "done" else line.state
            steps = f", {line.steps} steps" if line.steps else ""
            role = f": {_ellipsise(line.role, 48)}" if line.role else ""
            agents.append(f"  {line.name}{role} ({detail}{steps})")
        blocks.append(agents)

    if view.activity:
        blocks.append(["Recent", *(f"  {line}" for line in view.activity)])

    if view.denials:
        blocks.append(["Blocked", *(f"  {line}" for line in view.denials)])

    if view.errors:
        blocks.append(["Errors", *(f"  {line}" for line in view.errors)])

    if view.approvals:
        waiting = ["⏸ Waiting for approval"]
        for pending in view.approvals:
            waiting.append(
                f"  {pending.agent}: {_ellipsise(pending.prompt, 160)} [{pending.risk}]"
            )
        blocks.append(waiting)

    if view.claim is not None:
        blocks.append(_claim_block(view))

    return blocks


def _claim_block(view: ChatView) -> list[str]:
    claim = view.claim
    if claim is None:  # pragma: no cover: guarded by the caller
        return []

    if claim.kind == "failure":
        return ["Why the run stopped", f"  {_ellipsise(claim.text, 400)}"]

    calls = view.tool_calls
    noun = "tool call" if calls == 1 else "tool calls"
    return [
        "The supervisor's account of the run",
        f"  {_ellipsise(claim.text, 400)}",
        f"  This is what the agent said it did. What it actually did is the "
        f"{calls} {noun} this run made.",
    ]


def render(view: ChatView, *, limit: int) -> str:
    """Render ``view`` as plain text that fits inside ``limit`` characters.

    **What gets dropped first is the activity tail**, because it is the only
    part of the message a reader can recover elsewhere: the whole log is in the
    dashboard. The goal and the terminal claim exist nowhere else in the
    conversation, so they are the last things to go, and the hard truncation
    at the end exists only so that this function cannot return something the
    platform will reject outright, which for Discord is a 400 rather than a
    truncation.
    """
    blocks = _sections(view)
    activity_index = _index_of_activity(blocks)

    while _length(blocks) > limit and activity_index is not None:
        activity = blocks[activity_index]
        if len(activity) <= 2:
            blocks.pop(activity_index)
            activity_index = None
        else:
            # Drop the oldest line, not the newest: what an agent is doing now
            # is worth more than what it did four steps ago.
            del activity[1]

    text = _join(blocks)
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _index_of_activity(blocks: Sequence[list[str]]) -> int | None:
    for index, block in enumerate(blocks):
        if block and block[0] == "Recent":
            return index
    return None


def _join(blocks: Sequence[list[str]]) -> str:
    return "\n\n".join("\n".join(block) for block in blocks if block)


def _length(blocks: Sequence[list[str]]) -> int:
    return len(_join(blocks))
