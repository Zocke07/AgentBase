"""The event type contract (BUILD_SPEC §4).

This enum is the closed list from §4. Adding a member means updating the
generated TS types and the `RunGraph` reducer in the same commit — both arrive
in Phase 7, at which point this docstring becomes a three-way obligation.

**On payload models.** §3's layout comment for this module reads "event type
enum + payload models". The enum is complete here because §4 presents it as a
contract. The payloads are not: a `tool.requested` payload is defined by the
Tool protocol in Phase 6 and a `llm.response` payload by the Provider protocol
in Phase 3, and inventing their shapes now would be building ahead (§5) and
would bake in guesses that those phases then have to unpick. Phase 2 therefore
carries a typed envelope with an opaque JSON-object payload; each phase adds
the model for the events it introduces.
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
    # S105: flake8-bandit reads "token" as a credential. This is a streamed
    # LLM output token — the event emitted per chunk of a model response.
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


#: Events after which no further event can appear for that run. The SSE stream
#: uses these to close cleanly instead of holding a connection open forever.
TERMINAL_RUN_EVENTS: frozenset[EventType] = frozenset(
    {
        EventType.RUN_COMPLETED,
        EventType.RUN_FAILED,
        EventType.RUN_CANCELLED,
    }
)


class Event(BaseModel):
    """One append-only row of the log.

    ``seq`` is per-run and 1-based; it is the id the SSE stream publishes and
    the cursor ``Last-Event-ID`` carries. ``id`` is the global rowid and exists
    for ordering across runs — never use it as a resume cursor, since a client
    resuming one run would then skip every event another run interleaved.
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
    goal: str
    status: RunStatus
    origin: RunOrigin
    origin_ref: str | None = None
    created_at: datetime
    finished_at: datetime | None = None
