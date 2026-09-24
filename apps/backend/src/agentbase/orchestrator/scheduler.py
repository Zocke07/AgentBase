"""The scheduler: starts each schedule's run when its time comes (§5 Phase 13).

One loop in the sidecar, sleeping until the earliest ``next_run_at`` and
launching what is due through :class:`~agentbase.orchestrator.launcher.RunLauncher`,
so a scheduled run is an ordinary run in its space: same roster, rules,
folder, approval gate and budget. A call that needs approval waits for the
user like any other, up to the run's time limit; the scheduler never answers
for them.

The sidecar only lives while the window does, so the loop's first pass is a
catch-up: a schedule whose time passed while the app was closed runs once now
or is moved on, as its ``missed`` policy says. Either way the next time is
computed from the clock, never from the time that was missed, so a laptop
closed for a week does not fire seven times.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Final

from agentbase.store.spaces import SpaceArchivedError, SpaceNotFoundError

if TYPE_CHECKING:
    from agentbase.orchestrator.launcher import RunLauncher
    from agentbase.store.schedules import Schedule, ScheduleStore

__all__ = ["DEFAULT_POLL_SECONDS", "Fired", "Scheduler"]

logger = logging.getLogger("agentbase.scheduler")

#: The longest the loop sleeps between looks, so an edit made through the
#: API is picked up soon even if the wake-up were missed.
DEFAULT_POLL_SECONDS: Final[float] = 60.0

#: A schedule due longer ago than this when the loop starts is one the app
#: was closed for, not one that came due while the sidecar was starting.
MISSED_AFTER: Final[timedelta] = timedelta(minutes=2)


@dataclass(frozen=True, slots=True)
class Fired:
    """What one pass did with one due schedule."""

    schedule_id: str
    run_id: str | None
    outcome: str


@dataclass(slots=True)
class Scheduler:
    schedules: ScheduleStore
    launcher: RunLauncher
    poll_seconds: float = DEFAULT_POLL_SECONDS
    _task: asyncio.Task[None] | None = field(default=None, init=False)
    _wake: asyncio.Event = field(default_factory=asyncio.Event, init=False)

    # --- lifecycle ---------------------------------------------------------

    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop(), name="scheduler")

    async def aclose(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    def wake(self) -> None:
        """A schedule changed: look again now rather than at the next poll."""
        self._wake.set()

    # --- the loop ----------------------------------------------------------

    async def _loop(self) -> None:
        try:
            await self.catch_up()
        except Exception:
            logger.exception("the scheduler's catch-up pass failed")
        while True:
            delay = await self._seconds_until_next()
            self._wake.clear()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), timeout=delay)
            try:
                await self.tick()
            except Exception:
                # One bad pass must not end scheduling for the session.
                logger.exception("a scheduler pass failed")

    async def _seconds_until_next(self) -> float:
        soonest = await self.schedules.earliest()
        if soonest is None:
            return self.poll_seconds
        remaining = (soonest - self.schedules.now()).total_seconds()
        return max(0.0, min(remaining, self.poll_seconds))

    # --- passes ------------------------------------------------------------

    async def catch_up(self) -> list[Fired]:
        """The first pass after a launch: settle what came due while the app was closed."""
        now = self.schedules.now()
        fired: list[Fired] = []
        for schedule in await self.schedules.due(now):
            due_at = schedule.next_run_at
            if due_at is None or now - due_at <= MISSED_AFTER:
                fired.append(await self._fire(schedule, now))
                continue
            when = _local_words(due_at, self.schedules)
            if schedule.missed == "skip":
                outcome = f"Skipped: the app was closed at {when}."
                await self.schedules.advance(schedule.id, now=now, outcome=outcome, run_id=None)
                fired.append(Fired(schedule.id, None, outcome))
                logger.info("schedule %s: %s", schedule.name, outcome)
                continue
            fired.append(
                await self._fire(
                    schedule, now, note=f"the app was closed at {when}, so it ran at launch"
                )
            )
        return fired

    async def tick(self) -> list[Fired]:
        """One ordinary pass: launch everything due right now."""
        now = self.schedules.now()
        return [await self._fire(schedule, now) for schedule in await self.schedules.due(now)]

    async def _fire(self, schedule: Schedule, now: datetime, note: str | None = None) -> Fired:
        if self._still_running(schedule):
            outcome = "Skipped: the previous run had not finished."
            await self.schedules.advance(schedule.id, now=now, outcome=outcome, run_id=None)
            logger.info("schedule %s: %s", schedule.name, outcome)
            return Fired(schedule.id, None, outcome)

        try:
            run = await self.launcher.launch(
                schedule.goal,
                space_id=schedule.space_id,
                origin="schedule",
                origin_ref=schedule.id,
                max_run_seconds=schedule.max_run_seconds,
            )
        except SpaceArchivedError:
            outcome = "Turned off: its space is archived."
            await self.schedules.advance(
                schedule.id, now=now, outcome=outcome, run_id=None, enabled=False
            )
            logger.info("schedule %s: %s", schedule.name, outcome)
            return Fired(schedule.id, None, outcome)
        except SpaceNotFoundError:
            outcome = "Turned off: its space no longer exists."
            await self.schedules.advance(
                schedule.id, now=now, outcome=outcome, run_id=None, enabled=False
            )
            logger.warning("schedule %s: %s", schedule.name, outcome)
            return Fired(schedule.id, None, outcome)

        outcome = "Started a run" + (f": {note}." if note is not None else ".")
        await self.schedules.advance(schedule.id, now=now, outcome=outcome, run_id=run.id)
        logger.info("schedule %s started run %s", schedule.name, run.id)
        return Fired(schedule.id, run.id, outcome)

    def _still_running(self, schedule: Schedule) -> bool:
        """Whether the run this schedule last started is still going in this process."""
        last = schedule.last_run_id
        return last is not None and (
            last in self.launcher.live or last in self.launcher.driving
        )


def _local_words(when: datetime, schedules: ScheduleStore) -> str:
    """A due time in the machine's own words, for an outcome the user reads."""
    return when.astimezone(schedules.zone).strftime("%H:%M on %A %d %B")
