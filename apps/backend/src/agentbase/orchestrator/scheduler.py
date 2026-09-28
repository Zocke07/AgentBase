"""Schedule runner (§5 Phase 13).

One sidecar loop sleeps to earliest ``next_run_at`` and launches due work via
:class:`~agentbase.orchestrator.launcher.RunLauncher`. Scheduled work is an
ordinary space run with the same roster, rules, folder, gate, and budget; the
scheduler never answers approvals.

Its startup pass catches up schedules missed while the window was closed:
run once or advance according to ``missed``. Compute the next time from now,
not missed time, so a week-closed laptop does not fire seven runs.
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

#: Maximum sleep so API edits are soon seen even if wake-up was missed.
DEFAULT_POLL_SECONDS: Final[float] = 60.0

#: Startup-due threshold distinguishing closed-app work from sidecar startup.
MISSED_AFTER: Final[timedelta] = timedelta(minutes=2)


@dataclass(frozen=True, slots=True)
class Fired:
    """Outcome for one due schedule in one pass."""

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
        """Wake now after a schedule change instead of waiting for poll."""
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
                # One failed pass must not end session scheduling.
                logger.exception("a scheduler pass failed")

    async def _seconds_until_next(self) -> float:
        soonest = await self.schedules.earliest()
        if soonest is None:
            return self.poll_seconds
        remaining = (soonest - self.schedules.now()).total_seconds()
        return max(0.0, min(remaining, self.poll_seconds))

    # --- passes ------------------------------------------------------------

    async def catch_up(self) -> list[Fired]:
        """Startup pass: settle work due while the app was closed."""
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
        """Ordinary pass: launch all currently due schedules."""
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
        """Whether this schedule's last run remains active in this process."""
        last = schedule.last_run_id
        return last is not None and (
            last in self.launcher.live or last in self.launcher.driving
        )


def _local_words(when: datetime, schedules: ScheduleStore) -> str:
    """Format a due time in the machine zone for user-facing outcomes."""
    return when.astimezone(schedules.zone).strftime("%H:%M on %A %d %B")
