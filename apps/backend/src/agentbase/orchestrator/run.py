"""Run lifecycle, event sequence, and agent mailbox.

Agents communicate through ``agent.message`` events, never direct calls (§5
Phase 4): :meth:`Mailbox.deliver` appends and :meth:`Mailbox.collect` reads
SQLite. A worker result never travels in a Python variable. If its event fails
to write, the run stops rather than losing an audit line.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from agentbase.events.types import EventType
from agentbase.providers.pricing import format_micros

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from agentbase.events.store import EventStore
    from agentbase.events.types import RunOrigin
    from agentbase.knowledge.store import SearchHit
    from agentbase.orchestrator.limits import RunLimits
    from agentbase.store.spaces import Space

__all__ = [
    "UNATTENDED_ORIGINS",
    "Mailbox",
    "Run",
    "RunCancelledError",
    "RunCostExceededError",
    "RunDeadlineExceededError",
    "SpawnRefusedError",
]


#: Origins with nobody watching: a question in such a run waits only briefly.
UNATTENDED_ORIGINS: frozenset[RunOrigin] = frozenset({"schedule"})


class RunCostExceededError(RuntimeError):
    """Run reached its per-run cost ceiling (§5 Phase 3)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class RunDeadlineExceededError(RuntimeError):
    """Run exceeded ``max_run_seconds``; ``reason`` becomes ``run.failed`` payload."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class RunCancelledError(RuntimeError):
    """User requested a stop; deadline check raises this as ``run.cancelled``."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class SpawnRefusedError(RuntimeError):
    """Spawn refused at ``max_agents_per_run``; supervisor continues the run."""


@dataclass
class Run:
    """Run identity, limits, clock, and event sequence; append only through :meth:`emit`."""

    store: EventStore
    id: str
    goal: str
    limits: RunLimits
    #: Injectable clock for wall-limit tests without sleeping.
    clock: Callable[[], float] = time.monotonic
    #: Run space recorded in ``run.started``; ``None`` under app-wide rules.
    space: Space | None = None
    #: Pre-run retrieved excerpts, recorded for replay.
    knowledge: tuple[SearchHit, ...] = ()
    #: Citations removed in the pre-run retrieval inspector.
    knowledge_exclusions: tuple[str, ...] = ()
    #: Run spend queried before model calls; ``None`` without a ledger means no ceiling.
    spent_so_far: Callable[[], Awaitable[int]] | None = None
    #: Where the run came from; an unattended origin shortens question waits.
    origin: RunOrigin = "ui"
    #: How long a question waits in a run nobody watches; ``None`` waits out the run.
    question_seconds: int | None = None
    #: The approval policy this run acts under, recorded in ``run.started``.
    #: With nobody answering calls one by one, it is why each call ran.
    approval: dict[str, Any] | None = None
    started_at: float = field(default=0.0, init=False)
    _agents: list[str] = field(default_factory=list, init=False)
    #: Set by ``request_cancel`` and consumed by ``check_deadline`` between
    #: model calls, where a terminal event can still be written.
    _cancel_reason: str | None = field(default=None, init=False)

    # --- lifecycle ---------------------------------------------------------

    async def start(self) -> None:
        """Emit ``run.started`` and start the clock."""
        self.started_at = self.clock()
        payload: dict[str, Any] = {"goal": self.goal, "limits": self.limits.as_payload()}
        if self.space is not None:
            payload["space"] = self.space.as_payload()
        if self.knowledge:
            payload["knowledge"] = [hit.model_dump(mode="json") for hit in self.knowledge]
        if self.knowledge_exclusions:
            payload["knowledge_exclusions"] = list(self.knowledge_exclusions)
        if self.approval is not None:
            payload["approval"] = self.approval
        await self.emit(EventType.RUN_STARTED, payload)
        await self.store.set_run_status(self.id, "running")

    async def complete(self, summary: str, memory_path: str | None = None) -> None:
        payload = {"summary": summary}
        if memory_path is not None:
            payload["memory_path"] = memory_path
        await self.emit(EventType.RUN_COMPLETED, payload)
        await self.store.set_run_status(self.id, "completed")

    async def fail(self, reason: str) -> None:
        await self.emit(EventType.RUN_FAILED, {"reason": reason})
        await self.store.set_run_status(self.id, "failed")

    async def cancel(self, reason: str) -> None:
        await self.emit(EventType.RUN_CANCELLED, {"reason": reason})
        await self.store.set_run_status(self.id, "cancelled")

    # --- cancellation -------------------------------------------------------

    def request_cancel(self, reason: str) -> None:
        """Request a stop at the next check; first reason wins."""
        if self._cancel_reason is None:
            self._cancel_reason = reason

    @property
    def cancel_requested(self) -> bool:
        return self._cancel_reason is not None

    # --- the event sequence ------------------------------------------------

    async def emit(
        self,
        event_type: EventType,
        payload: dict[str, Any] | None = None,
        agent_id: str | None = None,
    ) -> None:
        await self.store.append(self.id, event_type, payload or {}, agent_id=agent_id)

    # --- limits ------------------------------------------------------------

    def elapsed_seconds(self) -> float:
        return self.clock() - self.started_at

    def remaining_seconds(self) -> float:
        """Return nonnegative wall-clock budget remaining.

        The approval gate uses it so it cannot await a decision the run cannot act on.
        """
        return max(0.0, self.limits.max_run_seconds - self.elapsed_seconds())

    @property
    def unattended(self) -> bool:
        """Whether nobody is watching this run to answer its questions."""
        return self.question_seconds is not None

    def question_deadline(self) -> float:
        """How long the gate may wait for an answer to this run's next question."""
        remaining = self.remaining_seconds()
        if self.question_seconds is None:
            return remaining
        return min(remaining, float(self.question_seconds))

    def check_deadline(self) -> None:
        """Raise after cancellation or ``max_run_seconds`` expiry.

        Check before each model request, not on a timer, so terminal events
        remain coherent.

        :raises RunDeadlineExceededError: with a user-facing reason.
        :raises RunCancelledError: when user requested a stop; checked first.
        """
        if self._cancel_reason is not None:
            raise RunCancelledError(self._cancel_reason)

        elapsed = self.elapsed_seconds()
        if elapsed >= self.limits.max_run_seconds:
            msg = (
                f"This run hit its time limit of {self.limits.max_run_seconds}s "
                f"(ran for {elapsed:.0f}s). Raise the limit in settings to allow "
                f"longer runs."
            )
            raise RunDeadlineExceededError(msg)

    async def check_cost(self, next_call_micros: int = 0) -> None:
        """Raise when spending ``next_call_micros`` more could pass the ceiling.

        Query run-ledger rows before each model request: a full-context retry
        loop can burn a monthly budget despite its step limit. The next call's
        pessimistic cost is counted too, as the monthly cap counts it, so an
        unattended run stops before the call that would cross its ceiling.

        :raises RunCostExceededError: with a user-facing reason.
        """
        ceiling = self.limits.max_run_cost_micros
        if ceiling <= 0 or self.spent_so_far is None:
            return
        spent = await self.spent_so_far()
        if spent >= ceiling:
            msg = (
                f"This run hit its cost limit of {format_micros(ceiling)} (spent "
                f"{format_micros(spent)}). Raise the limit in settings to allow "
                f"costlier runs."
            )
            raise RunCostExceededError(msg)
        if spent + next_call_micros > ceiling:
            msg = (
                f"This run stopped before its cost limit of {format_micros(ceiling)}: "
                f"it has spent {format_micros(spent)}, and its next model call could "
                f"add up to {format_micros(next_call_micros)}. Raise the limit in "
                f"settings to allow costlier runs."
            )
            raise RunCostExceededError(msg)

    @property
    def agent_names(self) -> tuple[str, ...]:
        return tuple(self._agents)

    def register_agent(self, name: str) -> str:
        """Claim a unique run-local agent name; duplicates merge on replay.

        :raises SpawnRefusedError: at ``max_agents_per_run``.
        """
        if len(self._agents) >= self.limits.max_agents_per_run:
            msg = (
                f"This run already has its maximum of "
                f"{self.limits.max_agents_per_run} agents "
                f"({', '.join(self._agents)}). Finish with the agents you have."
            )
            raise SpawnRefusedError(msg)

        unique = name
        suffix = 2
        while unique in self._agents:
            unique = f"{name}-{suffix}"
            suffix += 1

        self._agents.append(unique)
        return unique


class Mailbox:
    """Agent-to-agent messages carried by the event log."""

    def __init__(self, run: Run) -> None:
        self._run = run

    async def deliver(self, sender: str, recipient: str, text: str) -> None:
        """Post a message between agents."""
        await self._run.emit(
            EventType.AGENT_MESSAGE,
            {"to": recipient, "text": text},
            agent_id=sender,
        )

    async def collect(self, sender: str, recipient: str) -> str:
        """Read latest message from ``sender`` to ``recipient`` from the log.

        :raises LookupError: if none exists in the log.
        """
        events = await self._run.store.read(self._run.id)

        for event in reversed(events):
            if (
                event.type is EventType.AGENT_MESSAGE
                and event.agent_id == sender
                and event.payload.get("to") == recipient
            ):
                text = event.payload.get("text")
                return text if isinstance(text, str) else ""

        msg = (
            f"no agent.message from {sender!r} to {recipient!r} in the log for "
            f"run {self._run.id}: the event was never appended, so the result "
            f"it carried does not exist"
        )
        raise LookupError(msg)
