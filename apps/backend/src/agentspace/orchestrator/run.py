"""Run lifecycle, the event sequence, and the mailbox agents talk through.

§5 Phase 4: "`Run` owns lifecycle and the event sequence."

**The mailbox is the part worth reading closely.** §5 Phase 4 also says agents
communicate via `agent.message` events and never direct function calls. Taken
literally that is impossible (one Python object has to call another eventually),
so the question is what "communicate" means. Here it means the *content*
never travels in a Python variable from sender to receiver:
:meth:`Mailbox.deliver` appends an `agent.message` row, and
:meth:`Mailbox.collect` reads that row back **out of SQLite**. The supervisor
learns what a worker produced by reading the log, not by receiving a return
value.

That is slower than passing a string, and it is the whole point. It makes the
Phase 4 acceptance criterion ("the full event log alone is sufficient to
reconstruct exactly what happened") structural rather than aspirational: an
event that fails to be written is not a missing log line, it is a run that
stops working. A log that can drift from reality eventually will.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from agentspace.events.types import EventType

if TYPE_CHECKING:
    from collections.abc import Callable

    from agentspace.events.store import EventStore
    from agentspace.orchestrator.limits import RunLimits
    from agentspace.store.spaces import Space

__all__ = [
    "Mailbox",
    "Run",
    "RunCancelledError",
    "RunDeadlineExceededError",
    "SpawnRefusedError",
]


class RunDeadlineExceededError(RuntimeError):
    """The run exceeded `max_run_seconds`.

    Carries a reason fit to show a user; it becomes the `run.failed` payload.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class RunCancelledError(RuntimeError):
    """The user asked the run to stop.

    Raised from the same check as the deadline and handled the same way, so
    a cancel lands where the run can still write a coherent terminal event.
    Carries the reason that becomes the `run.cancelled` payload.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class SpawnRefusedError(RuntimeError):
    """A spawn was refused because the run is already at `max_agents_per_run`.

    Not a failure of the run: the supervisor is told and carries on. See
    :mod:`agentspace.orchestrator.limits` for why this limit terminates nothing.
    """


@dataclass
class Run:
    """One run's identity, limits, clock and event sequence.

    Everything that appends to the log for this run goes through :meth:`emit`,
    so there is one place where an event is written and one place to look when
    asking what a run can emit.
    """

    store: EventStore
    id: str
    goal: str
    limits: RunLimits
    #: Injected so tests can drive the wall-clock limit without sleeping.
    clock: Callable[[], float] = time.monotonic
    #: The space this run happens in, or ``None`` under the app-wide rules.
    #: Recorded in `run.started` so a replay can say which rules applied.
    space: Space | None = None
    started_at: float = field(default=0.0, init=False)
    _agents: list[str] = field(default_factory=list, init=False)
    #: Set by `request_cancel`; consumed by `check_deadline`. A flag rather
    #: than a task cancellation so the run stops between model calls, where
    #: it can still write a terminal event, instead of mid-request.
    _cancel_reason: str | None = field(default=None, init=False)

    # --- lifecycle ---------------------------------------------------------

    async def start(self) -> None:
        """Emit `run.started` and begin the clock."""
        self.started_at = self.clock()
        payload: dict[str, Any] = {"goal": self.goal, "limits": self.limits.as_payload()}
        if self.space is not None:
            payload["space"] = self.space.as_payload()
        await self.emit(EventType.RUN_STARTED, payload)
        await self.store.set_run_status(self.id, "running")

    async def complete(self, summary: str) -> None:
        await self.emit(EventType.RUN_COMPLETED, {"summary": summary})
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

        The approval gate blocks on this rather than on a timeout of its own.
        A separate approval timeout would be a second deadline to configure and
        explain, and the two would disagree: a run with five minutes left and a
        ten-minute approval window would sit waiting for a decision it could no
        longer act on. §5 Phase 4 already made "max wall-clock per run" the
        limit that ends a run, so the gate borrows it rather than competing.
        """
        return max(0.0, self.limits.max_run_seconds - self.elapsed_seconds())

    def check_deadline(self) -> None:
        """Raise if the run has outlived `max_run_seconds`.

        Called before each model request rather than on a timer: the run has to
        stop at a point where it can still write a coherent terminal event, and
        a cancelled coroutine mid-request cannot.

        :raises RunDeadlineExceededError: with a reason fit to show a user.
        :raises RunCancelledError: when the user asked the run to stop. Checked
            first: a cancel is a decision, the deadline is an accident.
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

    @property
    def agent_names(self) -> tuple[str, ...]:
        return tuple(self._agents)

    def register_agent(self, name: str) -> str:
        """Claim a unique agent name for this run.

        Unique because `events.agent_id` is how a replay tells two agents apart
        (§4). Two workers sharing a name would merge into one node in the graph
        with no way to separate them after the fact.

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
    """Agent-to-agent messages, carried by the event log rather than around it.

    Both halves go through SQLite on purpose: see this module's docstring.
    """

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
        """Read back the latest message ``sender`` posted to ``recipient``.

        Reads the durable row rather than returning something held in memory.
        If the corresponding :meth:`deliver` never wrote its event, this raises,
        which is the property that keeps the log honest.

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
