"""The event type contract (BUILD_SPEC §4).

Adding a member means updating the generated TS types, the TypeScript reducer
and the chat fold in the same commit. Payloads are opaque JSON objects; the
emitters define their shapes.
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

#: Statuses after which no further event will be appended for that run.
TERMINAL_RUN_STATUSES: frozenset[str] = frozenset({"completed", "failed", "cancelled"})

#: §4 `runs.origin`.
RunOrigin = Literal["ui", "discord"]


class EventType(StrEnum):
    """Every event this application can emit. The list is from §4, verbatim."""

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
    # S105: bandit reads "token" as a credential; this is a streamed output token.
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


#: Events after which no further event can appear for that run; the SSE stream closes on them.
TERMINAL_RUN_EVENTS: frozenset[EventType] = frozenset(
    {
        EventType.RUN_COMPLETED,
        EventType.RUN_FAILED,
        EventType.RUN_CANCELLED,
    }
)


class Event(BaseModel):
    """One append-only row of the log.

    ``seq`` is per-run and 1-based: the SSE id and the ``Last-Event-ID``
    cursor. ``id`` is the global rowid and is never a resume cursor.
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
    """A row of the `runs` table (§4)."""

    model_config = ConfigDict(frozen=True)

    id: str
    #: The space this run happened in. Never NULL: an unnamed space is the default one.
    space_id: str
    goal: str
    status: RunStatus
    origin: RunOrigin
    origin_ref: str | None = None
    created_at: datetime
    finished_at: datetime | None = None
