"""Run lifecycle, the event sequence, and the mailbox agents talk through.

Agents communicate via `agent.message` events, never direct calls (§5 Phase
4): :meth:`Mailbox.deliver` appends the row and :meth:`Mailbox.collect` reads
it back out of SQLite, so a worker's result never travels in a Python
variable. Slower than passing a string, and the point: an event that fails to
be written is a run that stops working, not a missing log line.
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
    from agentbase.knowledge.store import SearchHit
    from agentbase.orchestrator.limits import RunLimits
    from agentbase.store.spaces import Space

__all__ = [
    "Mailbox",
    "Run",
    "RunCancelledError",
    "RunCostExceededError",
    "RunDeadlineExceededError",
    "SpawnRefusedError",
]


class RunCostExceededError(RuntimeError):
    """The run spent what one run may; §5 Phase 3's cap, at the run's own scale."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class RunDeadlineExceededError(RuntimeError):
    """The run exceeded `max_run_seconds`. ``reason`` becomes the `run.failed` payload."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class RunCancelledError(RuntimeError):
    """The user asked the run to stop.

    Raised from the deadline check; ``reason`` becomes `run.cancelled`.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class SpawnRefusedError(RuntimeError):
    """A spawn refused at `max_agents_per_run`.

    Not a failure of the run: the supervisor carries on.
    """


@dataclass
class Run:
    """One run's identity, limits, clock and event sequence.

    Every append goes through :meth:`emit`.
    """

    store: EventStore
    id: str
    goal: str
    limits: RunLimits
    #: Injected so tests can drive the wall-clock limit without sleeping.
    clock: Callable[[], float] = time.monotonic
    #: The space this run happens in, recorded in `run.started`; ``None`` under app-wide rules.
    space: Space | None = None
    #: The excerpts retrieved before this run started, recorded for replay.
    knowledge: tuple[SearchHit, ...] = ()
    #: Citations the user removed in the pre-run retrieval inspector.
    knowledge_exclusions: tuple[str, ...] = ()
    #: What this run has spent so far, asked before each model call; ``None``
    #: where no ledger is wired (tests of the loop alone), which means no ceiling.
    spent_so_far: Callable[[], Awaitable[int]] | None = None
    started_at: float = field(default=0.0, init=False)
    _agents: list[str] = field(default_factory=list, init=False)
    #: Set by `request_cancel`, consumed by `check_deadline`: a flag, so the
    #: run stops between model calls where it can still write a terminal event.
    _cancel_reason: str | None = field(default=None, init=False)

    # --- lifecycle ---------------------------------------------------------

    async def start(self) -> None:
        """Emit `run.started` and begin the clock."""
        self.started_at = self.clock()
        payload: dict[str, Any] = {"goal": self.goal, "limits": self.limits.as_payload()}
        if self.space is not None:
            payload["space"] = self.space.as_payload()
        if self.knowledge:
            payload["knowledge"] = [hit.model_dump(mode="json") for hit in self.knowledge]
        if self.knowledge_exclusions:
            payload["knowledge_exclusions"] = list(self.knowledge_exclusions)
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
        """Ask the run to stop at its next check. The first reason wins."""
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
        """How much wall-clock budget is left, never negative.

        The approval gate blocks on this rather than on a timeout of its own,
        so it cannot wait for a decision the run could no longer act on.
        """
        return max(0.0, self.limits.max_run_seconds - self.elapsed_seconds())

    def check_deadline(self) -> None:
        """Raise if the run has outlived `max_run_seconds` or was cancelled.

        Called before each model request rather than on a timer, so the run
        stops where it can still write a coherent terminal event.

        :raises RunDeadlineExceededError: with a reason fit to show a user.
        :raises RunCancelledError: when the user asked the run to stop; checked first.
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

    async def check_cost(self) -> None:
        """Raise if the run has spent what `max_run_cost_micros` allows.

        Asked before each model request, like the deadline, from the ledger's
        rows for this run: an agent retrying an oversized call at a full
        context window can spend a month's budget in an hour, and the step
        limit alone does not see money.

        :raises RunCostExceededError: with a reason fit to show a user.
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

    @property
    def agent_names(self) -> tuple[str, ...]:
        return tuple(self._agents)

    def register_agent(self, name: str) -> str:
        """Claim a unique agent name for this run; two agents sharing one would merge on replay.

        :raises SpawnRefusedError: when the run is already at `max_agents_per_run`.
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
    """Agent-to-agent messages, carried by the event log rather than around it."""

    def __init__(self, run: Run) -> None:
        self._run = run

    async def deliver(self, sender: str, recipient: str, text: str) -> None:
        """Post a message from one agent to another."""
        await self._run.emit(
            EventType.AGENT_MESSAGE,
            {"to": recipient, "text": text},
            agent_id=sender,
        )

    async def collect(self, sender: str, recipient: str) -> str:
        """Read back the latest message ``sender`` posted to ``recipient``, from the log.

        :raises LookupError: when no such message is in the log.
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
