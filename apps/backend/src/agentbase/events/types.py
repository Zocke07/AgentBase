"""Event-type contract (BUILD_SPEC §4).

Adding a member also updates generated TypeScript types, its reducer, and the
chat fold. Payloads are opaque JSON; emitters define their shapes.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "TERMINAL_RUN_EVENTS",
    "TERMINAL_RUN_STATUSES",
    "Event",
    "EventType",
    "Run",
    "RunOrigin",
    "RunStatus",
]

#: §4 `runs.status`.
RunStatus = Literal["pending", "running", "paused", "completed", "failed", "cancelled"]

#: Statuses after which a run receives no more events.
TERMINAL_RUN_STATUSES: frozenset[str] = frozenset({"completed", "failed", "cancelled"})

#: §4 `runs.origin`: ``schedule`` is clock-fired and ``automation`` is Run now.
RunOrigin = Literal["ui", "discord", "schedule", "automation", "monitor"]


class EventType(StrEnum):
    """Every event this application emits; list matches §4 verbatim."""

    RUN_STARTED = "run.started"
    RUN_COMPLETED = "run.completed"
    RUN_FAILED = "run.failed"
    RUN_PAUSED = "run.paused"
    RUN_CANCELLED = "run.cancelled"

    AGENT_SPAWNED = "agent.spawned"
    AGENT_THINKING = "agent.thinking"
    AGENT_MESSAGE = "agent.message"
    AGENT_HANDOFF = "agent.handoff"
    AGENT_COMPLETED = "agent.completed"

    LLM_REQUEST = "llm.request"
    # S105: Bandit sees a credential; this is a streamed output token.
    LLM_TOKEN = "llm.token"  # noqa: S105
    LLM_RESPONSE = "llm.response"
    LLM_ERROR = "llm.error"

    TOOL_REQUESTED = "tool.requested"
    TOOL_APPROVED = "tool.approved"
    TOOL_DENIED = "tool.denied"
    TOOL_CALLED = "tool.called"
    TOOL_RESULT = "tool.result"
    TOOL_ERROR = "tool.error"

    APPROVAL_REQUESTED = "approval.requested"
    APPROVAL_RESOLVED = "approval.resolved"

    BUDGET_WARNING = "budget.warning"
    BUDGET_EXCEEDED = "budget.exceeded"

    CHANNEL_INBOUND = "channel.inbound"
    CHANNEL_OUTBOUND = "channel.outbound"


#: Terminal events after which SSE closes for that run.
TERMINAL_RUN_EVENTS: frozenset[EventType] = frozenset(
    {
        EventType.RUN_COMPLETED,
        EventType.RUN_FAILED,
        EventType.RUN_CANCELLED,
    }
)


class Event(BaseModel):
    """Append-only log row.

    ``seq`` is a 1-based per-run SSE/``Last-Event-ID`` cursor; global rowid
    ``id`` is never a resume cursor.
    """

    model_config = ConfigDict(frozen=True)

    id: int
    run_id: str
    seq: int
    agent_id: str | None = None
    type: EventType
    payload: dict[str, Any] = Field(default_factory=dict)
    ts: datetime


class Run(BaseModel):
    """``runs`` table row (§4)."""

    model_config = ConfigDict(frozen=True)

    id: str
    #: Space where the run occurred; never NULL because unnamed selects default.
    space_id: str
    goal: str
    status: RunStatus
    origin: RunOrigin
    origin_ref: str | None = None
    #: What an automation's run is called: its schedule's name, or the moves a
    #: market alert explains. ``None`` for a person's own run, named by its goal.
    title: str | None = None
    created_at: datetime
    finished_at: datetime | None = None
