"""Schedule runner (§5 Phase 13).

One sidecar loop sleeps to earliest ``next_run_at`` and launches due work via
:class:`~agentbase.orchestrator.launcher.RunLauncher`. Scheduled work is an
ordinary space run with the same roster, rules, folder, gate, and budget; the
scheduler never answers approvals.

Its startup pass catches up schedules missed while the window was closed:
run once or advance according to ``missed``. Compute the next time from now,
not missed time, so a week-closed laptop does not fire seven runs. A
schedule whose run the app closed on is treated the same way: run again once
at launch, or noted and left, by the same policy.

A stage with an ``after`` cadence has no time of its own. When a scheduled
run finishes, :meth:`Scheduler.follow` starts the stages that follow its
schedule if it completed, and records why not if it failed or was cancelled.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Final

from agentbase.store.schedules import AfterCadence
from agentbase.store.spaces import SpaceArchivedError, SpaceNotFoundError

if TYPE_CHECKING:
    from agentbase.events.types import Run as RunRow
    from agentbase.orchestrator.launcher import RunLauncher
    from agentbase.store.schedules import Schedule, ScheduleStore

__all__ = ["DEFAULT_POLL_SECONDS", "Fired", "ScheduleBusyError", "Scheduler"]

logger = logging.getLogger("agentbase.scheduler")

#: Maximum sleep so API edits are soon seen even if wake-up was missed.
DEFAULT_POLL_SECONDS: Final[float] = 60.0

#: Startup-due threshold distinguishing closed-app work from sidecar startup.
MISSED_AFTER: Final[timedelta] = timedelta(minutes=2)


class ScheduleBusyError(RuntimeError):
    """Run now refused: the schedule's previous run is still going."""


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
    #: Runs the previous process left unfinished, failed at this launch.
    interrupted: frozenset[str] = frozenset()
    _task: asyncio.Task[None] | None = field(default=None, init=False)
    _wake: asyncio.Event = field(default_factory=asyncio.Event, init=False)
    #: Set on close, so a run finishing during shutdown starts no stage.
    _closed: bool = field(default=False, init=False)

    # --- lifecycle ---------------------------------------------------------

    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop(), name="scheduler")

    async def aclose(self) -> None:
        self._closed = True
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
        fired.extend(await self._rerun_interrupted(now, fired))
        return fired

    async def _rerun_interrupted(self, now: datetime, earlier: list[Fired]) -> list[Fired]:
        """Settle schedules whose last run the app closed on, once each.

        A stage whose chain will reach it anyway (something above it started in
        this pass, or is being run again now) waits for it rather than running
        beside it, which would run it twice or skip its run on fresh inputs.
        """
        if not self.interrupted:
            return []
        every = await self.schedules.list_all()
        by_id = {schedule.id: schedule for schedule in every}
        settled = {entry.schedule_id for entry in earlier}
        candidates = [
            schedule
            for schedule in every
            if schedule.enabled
            and schedule.id not in settled
            and schedule.last_run_id in self.interrupted
        ]
        will_run = {entry.schedule_id for entry in earlier if entry.run_id is not None} | {
            schedule.id for schedule in candidates if schedule.missed == "run_on_launch"
        }
        fired: list[Fired] = []
        for schedule in candidates:
            ahead = _ahead_in_chain(schedule, by_id, will_run)
            if ahead is not None:
                outcome = f"Will run after {ahead.name} completes."
                await self.schedules.note_outcome(schedule.id, now=now, outcome=outcome)
                fired.append(Fired(schedule.id, None, outcome))
                continue
            if schedule.missed == "skip":
                outcome = "Not run again: the app closed during its last run."
                await self.schedules.note_outcome(schedule.id, now=now, outcome=outcome)
                fired.append(Fired(schedule.id, None, outcome))
                continue
            fired.append(
                await self._fire(
                    schedule, now, note="the app closed during its last run, so it ran again"
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

    async def follow(self, run_id: str) -> None:
        """Launcher hook for every finished run; never raises into the launcher."""
        try:
            await self.on_run_finished(run_id)
        except Exception:
            logger.exception("could not start the stages after run %s", run_id)

    async def on_run_finished(self, run_id: str) -> list[Fired]:
        """Start, or record why not, the stages that follow an automation run."""
        if self._closed:
            return []
        run = await self.launcher.store.get_run(run_id)
        if (
            run is None
            or run.origin not in {"schedule", "automation"}
            or run.origin_ref is None
        ):
            return []
        followers = await self.schedules.followers(run.origin_ref)
        if not followers:
            return []
        parent = await self.schedules.get(run.origin_ref)
        name = parent.name if parent is not None else "the schedule before it"
        now = self.schedules.now()
        fired: list[Fired] = []
        for follower in followers:
            if run.status == "completed":
                fired.append(await self._fire(follower, now, note=f"it follows {name}"))
                continue
            ended = "was cancelled" if run.status == "cancelled" else "did not finish"
            outcome = f"Not started: {name}'s run {ended}."
            await self.schedules.note_outcome(follower.id, now=now, outcome=outcome)
            logger.info("schedule %s: %s", follower.name, outcome)
            fired.append(Fired(follower.id, None, outcome))
        return fired

    async def run_now(self, schedule: Schedule) -> RunRow:
        """Start a schedule by hand, bounded exactly as a timed start is.

        The same overlap guard and time limit apply, and the next time is left
        where it was.

        :raises ScheduleBusyError: while its previous run is still going.
        :raises SpaceNotFoundError: if its space no longer exists.
        :raises SpaceArchivedError: if its space is archived.
        """
        if self._still_running(schedule):
            msg = f"{schedule.name}'s previous run has not finished yet."
            raise ScheduleBusyError(msg)
        run = await self.launcher.launch(
            schedule.goal,
            space_id=schedule.space_id,
            origin="automation",
            origin_ref=schedule.id,
            max_run_seconds=schedule.max_run_seconds,
        )
        await self.schedules.note_run(
            schedule.id, now=self.schedules.now(), run_id=run.id, outcome="Started by hand."
        )
        return run

    def _still_running(self, schedule: Schedule) -> bool:
        """Whether this schedule's last run remains active in this process."""
        last = schedule.last_run_id
        return last is not None and (
            last in self.launcher.live or last in self.launcher.driving
        )


def _ahead_in_chain(
    schedule: Schedule, by_id: dict[str, Schedule], will_run: set[str]
) -> Schedule | None:
    """The nearest schedule above ``schedule`` in its chain that will run."""
    seen = {schedule.id}
    current = schedule
    while isinstance(current.cadence, AfterCadence):
        above = by_id.get(current.cadence.schedule_id)
        if above is None or above.id in seen:
            return None
        if above.id in will_run:
            return above
        seen.add(above.id)
        current = above
    return None


def _local_words(when: datetime, schedules: ScheduleStore) -> str:
    """Format a due time in the machine zone for user-facing outcomes."""
    return when.astimezone(schedules.zone).strftime("%H:%M on %A %d %B")
