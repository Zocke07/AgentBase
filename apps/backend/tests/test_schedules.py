"""Schedules: the cadence arithmetic, migration 009 and the store, and the
scheduler's passes, with a fake launcher standing in for the orchestrator.

The local zone is injected as a hand-written `tzinfo` with a summer-time rule
of its own, so the DST cases run the same on every machine and need no
`tzdata`. `LocalZone` itself is checked against the C library on hosts that
can reset their zone.
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime, timedelta, tzinfo
from typing import TYPE_CHECKING, Any

import pytest

from agentspace.orchestrator.scheduler import MISSED_AFTER, Fired, Scheduler
from agentspace.store.db import LATEST_SCHEMA_VERSION
from agentspace.store.schedules import (
    DailyCadence,
    IntervalCadence,
    LocalZone,
    ScheduleNotFoundError,
    ScheduleStore,
    ScheduleValidationError,
    WeeklyCadence,
    describe,
    next_occurrence,
    parse_cadence,
)
from agentspace.store.spaces import (
    DEFAULT_SPACE_ID,
    SpaceArchivedError,
    SpaceStore,
)

if TYPE_CHECKING:
    from agentspace.config import AppPaths
    from agentspace.events.store import EventStore
    from agentspace.store.db import Database

pytestmark = pytest.mark.anyio


class SummerZone(tzinfo):
    """UTC+1, and UTC+2 from the last Sunday of March to the last Sunday of
    October at 02:00 local, the European rule, hard-coded for 2026 only."""

    # Wall times by design: the rule is written in local clock terms.
    _START = datetime(2026, 3, 29, 2, 0)  # noqa: DTZ001
    _END = datetime(2026, 10, 25, 3, 0)  # noqa: DTZ001

    def _summer(self, dt: datetime | None) -> bool:
        if dt is None:
            return False
        wall = dt.replace(tzinfo=None)
        return self._START <= wall < self._END

    def utcoffset(self, dt: datetime | None) -> timedelta:
        return timedelta(hours=2 if self._summer(dt) else 1)

    def dst(self, dt: datetime | None) -> timedelta:
        return timedelta(hours=1 if self._summer(dt) else 0)

    def tzname(self, dt: datetime | None) -> str:
        return "SUMMER" if self._summer(dt) else "STANDARD"


ZONE = SummerZone()


def _utc(
    year: int, month: int, day: int, hour: int = 0, minute: int = 0, second: int = 0
) -> datetime:
    return datetime(year, month, day, hour, minute, second, tzinfo=UTC)


def _local(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=ZONE)


# --- cadence arithmetic ---------------------------------------------------------


def test_daily_names_today_when_the_time_is_still_ahead_and_tomorrow_otherwise() -> None:
    cadence = DailyCadence(kind="daily", at="09:30")
    morning = _local(2026, 9, 18, 8, 0)
    assert next_occurrence(cadence, morning, ZONE) == _local(2026, 9, 18, 9, 30)

    evening = _local(2026, 9, 18, 21, 0)
    assert next_occurrence(cadence, evening, ZONE) == _local(2026, 9, 19, 9, 30)

    # Strictly after: exactly on the minute names the next day.
    on_time = _local(2026, 9, 18, 9, 30)
    assert next_occurrence(cadence, on_time, ZONE) == _local(2026, 9, 19, 9, 30)


def test_the_result_is_in_utc_and_the_wall_time_survives_a_dst_change() -> None:
    cadence = DailyCadence(kind="daily", at="09:00")
    # The evening before summer time starts: 09:00 local the next day is
    # 07:00 UTC, not the 08:00 UTC that today's offset would give.
    before = _local(2026, 3, 28, 22, 0)
    following = next_occurrence(cadence, before, ZONE)
    assert following.tzinfo is UTC
    assert following == _utc(2026, 3, 29, 7, 0)
    assert following.astimezone(ZONE).hour == 9

    # And the evening before it ends: 09:00 local is 08:00 UTC again.
    before_end = _local(2026, 10, 24, 22, 0)
    assert next_occurrence(cadence, before_end, ZONE) == _utc(2026, 10, 25, 8, 0)


def test_weekly_skips_to_the_next_allowed_day_and_wraps_the_week() -> None:
    # 18 September 2026 is a Friday.
    cadence = WeeklyCadence(kind="weekly", at="18:00", weekdays=[0, 4])
    friday_noon = _local(2026, 9, 18, 12, 0)
    assert next_occurrence(cadence, friday_noon, ZONE) == _local(2026, 9, 18, 18, 0)

    friday_night = _local(2026, 9, 18, 19, 0)
    assert next_occurrence(cadence, friday_night, ZONE) == _local(2026, 9, 21, 18, 0)

    only_thursday = WeeklyCadence(kind="weekly", at="18:00", weekdays=[3])
    assert next_occurrence(only_thursday, friday_night, ZONE) == _local(2026, 9, 24, 18, 0)


def test_an_interval_counts_from_the_instant_it_is_asked_about() -> None:
    cadence = IntervalCadence(kind="interval", every_hours=6)
    at = _utc(2026, 9, 18, 10, 15)
    assert next_occurrence(cadence, at, ZONE) == _utc(2026, 9, 18, 16, 15)


def test_cadences_are_validated_with_a_message_for_the_user() -> None:
    assert parse_cadence({"kind": "daily", "at": "07:05"}) == DailyCadence(
        kind="daily", at="07:05"
    )
    # Weekdays come back sorted and deduplicated.
    assert parse_cadence(
        {"kind": "weekly", "at": "07:05", "weekdays": [6, 0, 6]}
    ) == WeeklyCadence(kind="weekly", at="07:05", weekdays=[0, 6])

    with pytest.raises(ScheduleValidationError, match="looks like 09:30"):
        parse_cadence({"kind": "daily", "at": "9:30"})
    with pytest.raises(ScheduleValidationError, match="looks like 09:30"):
        parse_cadence({"kind": "daily", "at": "25:00"})
    with pytest.raises(ScheduleValidationError, match="Monday"):
        parse_cadence({"kind": "weekly", "at": "07:00", "weekdays": [7]})
    with pytest.raises(ScheduleValidationError, match="daily, weekly or an interval"):
        parse_cadence({"kind": "monthly"})
    with pytest.raises(ScheduleValidationError, match="daily, weekly or an interval"):
        parse_cadence("daily")
    with pytest.raises(ScheduleValidationError):
        parse_cadence({"kind": "interval", "every_hours": 0})


def test_a_cadence_is_described_in_one_sentence() -> None:
    assert describe(DailyCadence(kind="daily", at="09:00")) == "Every day at 09:00"
    assert (
        describe(WeeklyCadence(kind="weekly", at="09:00", weekdays=[0, 1, 2, 3, 4]))
        == "Weekdays at 09:00"
    )
    assert (
        describe(WeeklyCadence(kind="weekly", at="09:00", weekdays=[0, 2, 4]))
        == "Mondays, Wednesdays and Fridays at 09:00"
    )
    assert (
        describe(WeeklyCadence(kind="weekly", at="09:00", weekdays=[6])) == "Sundays at 09:00"
    )
    assert describe(IntervalCadence(kind="interval", every_hours=1)) == "Every hour"
    assert describe(IntervalCadence(kind="interval", every_hours=6)) == "Every 6 hours"
    assert describe(IntervalCadence(kind="interval", every_hours=48)) == "Every 2 days"


def test_the_local_zone_reads_the_offset_of_the_wall_time_it_is_given(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The reason `LocalZone` exists: `datetime.now().astimezone()` would not."""
    # `tzset` does not exist on Windows, where the C library's zone cannot be
    # reset from inside the process; looked up rather than named so the
    # cross-platform typecheck does not see an attribute Windows lacks.
    tzset = getattr(time, "tzset", None)
    if tzset is None:
        pytest.skip("the C library's zone cannot be reset here")
    monkeypatch.setenv("TZ", "Europe/Amsterdam")
    tzset()
    try:
        zone = LocalZone()
        winter = datetime(2026, 1, 15, 9, 0, tzinfo=zone)
        summer = datetime(2026, 7, 15, 9, 0, tzinfo=zone)
        assert winter.utcoffset() == timedelta(hours=1)
        assert summer.utcoffset() == timedelta(hours=2)
        # Round trip through UTC lands on the same wall time.
        assert summer.astimezone(UTC).astimezone(zone).hour == 9
        # And a daily cadence computed the night before the switch is right.
        cadence = DailyCadence(kind="daily", at="09:00")
        eve = datetime(2026, 3, 28, 22, 0, tzinfo=zone)
        assert next_occurrence(cadence, eve, zone) == _utc(2026, 3, 29, 7, 0)
    finally:
        monkeypatch.delenv("TZ")
        tzset()


# --- the store -------------------------------------------------------------------


class Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock(_local(2026, 9, 18, 8, 0).astimezone(UTC))


@pytest.fixture
def schedules(db: Database, clock: Clock) -> ScheduleStore:
    return ScheduleStore(db, clock=clock, zone=ZONE)


@pytest.fixture
def spaces(db: Database, app_paths: AppPaths) -> SpaceStore:
    return SpaceStore(db, app_paths.spaces_dir)


def _fields(**overrides: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "space_id": DEFAULT_SPACE_ID,
        "name": "Morning digest",
        "goal": "Summarise what changed in the notes since yesterday.",
        "cadence": {"kind": "daily", "at": "09:00"},
    }
    fields.update(overrides)
    return fields


def test_migration_009_is_the_latest_and_adds_the_table(db: Database) -> None:
    assert LATEST_SCHEMA_VERSION == 9
    with db.read() as connection:
        columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(schedules)").fetchall()
        }
    assert {"id", "space_id", "goal", "cadence", "missed", "enabled", "next_run_at"} <= columns


async def test_creating_a_schedule_computes_its_first_time_in_utc(
    schedules: ScheduleStore,
) -> None:
    created = await schedules.create(_fields())
    assert created.enabled is True
    assert created.next_run_at == _utc(2026, 9, 18, 7, 0)  # 09:00 in the zone
    assert created.last_run_at is None
    assert created.cadence == DailyCadence(kind="daily", at="09:00")

    listed = await schedules.list_all(DEFAULT_SPACE_ID)
    assert [entry.id for entry in listed] == [created.id]
    assert await schedules.list_all("some-other-space") == []


async def test_the_store_refuses_what_a_user_would_regret(schedules: ScheduleStore) -> None:
    with pytest.raises(ScheduleValidationError) as blank:
        await schedules.create(_fields(name="  "))
    assert blank.value.field == "name"

    with pytest.raises(ScheduleValidationError) as no_goal:
        await schedules.create(_fields(goal=""))
    assert no_goal.value.field == "goal"

    with pytest.raises(ScheduleValidationError) as bad_time:
        await schedules.create(_fields(cadence={"kind": "daily", "at": "noon"}))
    assert bad_time.value.field == "cadence"

    with pytest.raises(ScheduleValidationError) as no_space:
        await schedules.create(_fields(space_id="ghost"))
    assert no_space.value.field == "space_id"

    with pytest.raises(ScheduleValidationError) as policy:
        await schedules.create(_fields(missed="ignore"))
    assert policy.value.field == "missed"

    with pytest.raises(ScheduleNotFoundError):
        await schedules.update("ghost", {"name": "x"})
    with pytest.raises(ScheduleNotFoundError):
        await schedules.delete("ghost")


async def test_disabling_clears_the_time_and_enabling_recomputes_it(
    schedules: ScheduleStore, clock: Clock
) -> None:
    created = await schedules.create(_fields())
    off = await schedules.update(created.id, {"enabled": False})
    assert off.enabled is False
    assert off.next_run_at is None
    assert await schedules.due(clock.now + timedelta(days=3)) == []

    clock.now = _local(2026, 9, 20, 12, 0).astimezone(UTC)
    on = await schedules.update(created.id, {"enabled": True})
    assert on.next_run_at == _utc(2026, 9, 21, 7, 0)

    # A new cadence is recomputed from now too, not from the old time.
    weekly = await schedules.update(
        created.id, {"cadence": {"kind": "weekly", "at": "07:00", "weekdays": [6]}}
    )
    assert weekly.next_run_at == _utc(2026, 9, 27, 5, 0)
    # An unrelated edit leaves the time alone.
    renamed = await schedules.update(created.id, {"name": "Sunday digest"})
    assert renamed.next_run_at == weekly.next_run_at


async def test_advance_records_the_outcome_and_moves_on_from_now(
    schedules: ScheduleStore, clock: Clock, store: EventStore
) -> None:
    created = await schedules.create(_fields())
    run = await store.create_run("g", origin="schedule", origin_ref=created.id)

    # Fired a week late (the app was closed): the next time is tomorrow, not
    # a week of catch-ups.
    clock.now = _utc(2026, 9, 25, 7, 0, 30)
    advanced = await schedules.advance(
        created.id, now=clock.now, outcome="Started a run.", run_id=run.id
    )
    assert advanced.last_run_id == run.id
    assert advanced.last_run_at == clock.now
    assert advanced.last_outcome == "Started a run."
    assert advanced.next_run_at == _utc(2026, 9, 26, 7, 0)

    # A skip keeps the previous run's identity.
    skipped = await schedules.advance(
        created.id, now=clock.now, outcome="Skipped.", run_id=None
    )
    assert skipped.last_run_id == run.id
    assert skipped.last_outcome == "Skipped."

    # Deleting the run clears the reference rather than dangling it.
    with store._db.write() as connection:
        connection.execute("UPDATE runs SET status = 'completed' WHERE id = ?", (run.id,))
    await store.delete_run(run.id)
    assert (await schedules.require(created.id)).last_run_id is None


async def test_deleting_a_space_takes_its_schedules_with_it(
    schedules: ScheduleStore, spaces: SpaceStore
) -> None:
    lab = await spaces.create({"name": "Lab"})
    created = await schedules.create(_fields(space_id=lab.id))
    await spaces.delete(lab.id)
    assert await schedules.get(created.id) is None


# --- the scheduler -----------------------------------------------------------------


class FakeLauncher:
    """Records what the scheduler asked for; refuses spaces the test names."""

    def __init__(self, store: EventStore, spaces: SpaceStore) -> None:
        self._store = store
        self._spaces = spaces
        self.launched: list[dict[str, Any]] = []
        self.live: dict[str, object] = {}
        self.driving: set[str] = set()

    async def launch(self, goal: str, **kwargs: Any) -> Any:
        space = await self._spaces.require(kwargs["space_id"])
        if space.archived:
            raise SpaceArchivedError(space.name)
        run = await self._store.create_run(
            goal, origin=kwargs["origin"], origin_ref=kwargs["origin_ref"], space_id=space.id
        )
        self.launched.append({"goal": goal, "run_id": run.id, **kwargs})
        return run


@pytest.fixture
def launcher(store: EventStore, spaces: SpaceStore) -> FakeLauncher:
    return FakeLauncher(store, spaces)


@pytest.fixture
def scheduler(schedules: ScheduleStore, launcher: FakeLauncher) -> Scheduler:
    return Scheduler(schedules, launcher, poll_seconds=0.05)  # type: ignore[arg-type]


async def test_a_tick_launches_what_is_due_as_a_scheduled_run_and_nothing_else(
    schedules: ScheduleStore, scheduler: Scheduler, launcher: FakeLauncher, clock: Clock
) -> None:
    due = await schedules.create(_fields(name="Due"))
    later = await schedules.create(
        _fields(name="Later", cadence={"kind": "daily", "at": "18:00"})
    )
    assert await scheduler.tick() == []

    clock.now = _utc(2026, 9, 18, 7, 0, 5)
    fired = await scheduler.tick()
    assert [entry.schedule_id for entry in fired] == [due.id]
    assert launcher.launched == [
        {
            "goal": due.goal,
            "run_id": fired[0].run_id,
            "space_id": DEFAULT_SPACE_ID,
            "origin": "schedule",
            "origin_ref": due.id,
        }
    ]
    moved = await schedules.require(due.id)
    assert moved.last_run_id == fired[0].run_id
    assert moved.next_run_at == _utc(2026, 9, 19, 7, 0)
    assert (await schedules.require(later.id)).last_run_id is None

    # Nothing fires twice for one time.
    assert await scheduler.tick() == []


async def test_catch_up_runs_a_missed_schedule_once_or_skips_it_as_its_policy_says(
    schedules: ScheduleStore, scheduler: Scheduler, launcher: FakeLauncher, clock: Clock
) -> None:
    run_later = await schedules.create(_fields(name="Run later", missed="run_on_launch"))
    skip = await schedules.create(_fields(name="Skip", missed="skip"))
    # Due 09:00 on the 18th; the app opens three days later at noon.
    clock.now = _local(2026, 9, 21, 12, 0).astimezone(UTC)

    fired = {entry.schedule_id: entry for entry in await scheduler.catch_up()}
    assert fired[run_later.id].run_id is not None
    assert fired[run_later.id].outcome == (
        "Started a run: the app was closed at 09:00 on Friday 18 September, so it ran at launch."
    )
    assert fired[skip.id].run_id is None
    assert (
        fired[skip.id].outcome == "Skipped: the app was closed at 09:00 on Friday 18 September."
    )
    assert [entry["origin_ref"] for entry in launcher.launched] == [run_later.id]

    # Both move to tomorrow, from now: one catch-up, not three.
    for schedule_id in (run_later.id, skip.id):
        assert (await schedules.require(schedule_id)).next_run_at == _utc(2026, 9, 22, 7, 0)


async def test_catch_up_treats_a_time_that_just_passed_as_ordinary(
    schedules: ScheduleStore, scheduler: Scheduler, clock: Clock
) -> None:
    created = await schedules.create(_fields(missed="skip"))
    clock.now = _utc(2026, 9, 18, 7, 0) + MISSED_AFTER - timedelta(seconds=1)
    fired = await scheduler.catch_up()
    assert fired[0].schedule_id == created.id
    assert fired[0].run_id is not None
    assert fired[0].outcome == "Started a run."


async def test_a_schedule_whose_previous_run_is_still_going_is_skipped(
    schedules: ScheduleStore, scheduler: Scheduler, launcher: FakeLauncher, clock: Clock
) -> None:
    created = await schedules.create(_fields(cadence={"kind": "interval", "every_hours": 1}))
    clock.now += timedelta(hours=1, seconds=1)
    first = await scheduler.tick()
    assert first[0].run_id is not None
    launcher.driving.add(first[0].run_id)

    clock.now += timedelta(hours=1, seconds=1)
    second = await scheduler.tick()
    assert second == [Fired(created.id, None, "Skipped: the previous run had not finished.")]
    assert len(launcher.launched) == 1
    assert (await schedules.require(created.id)).last_run_id == first[0].run_id

    launcher.driving.clear()
    clock.now += timedelta(hours=1, seconds=1)
    assert (await scheduler.tick())[0].run_id is not None


async def test_an_archived_space_turns_its_schedule_off_rather_than_failing_forever(
    schedules: ScheduleStore, scheduler: Scheduler, spaces: SpaceStore, clock: Clock
) -> None:
    lab = await spaces.create({"name": "Lab"})
    created = await schedules.create(_fields(space_id=lab.id))
    await spaces.update(lab.id, {"archived": True})

    clock.now = _utc(2026, 9, 18, 7, 0, 5)
    fired = await scheduler.tick()
    assert fired == [Fired(created.id, None, "Turned off: its space is archived.")]
    stopped = await schedules.require(created.id)
    assert stopped.enabled is False
    assert stopped.next_run_at is None


async def test_the_loop_fires_on_time_and_wakes_for_an_edit(
    schedules: ScheduleStore, scheduler: Scheduler, launcher: FakeLauncher, clock: Clock
) -> None:
    await scheduler.start()
    try:
        created = await schedules.create(
            _fields(cadence={"kind": "interval", "every_hours": 1})
        )
        await asyncio.sleep(0.15)
        assert launcher.launched == []

        clock.now += timedelta(hours=1, seconds=1)
        scheduler.wake()
        for _ in range(50):
            await asyncio.sleep(0.02)
            if launcher.launched:
                break
        assert [entry["origin_ref"] for entry in launcher.launched] == [created.id]
    finally:
        await scheduler.aclose()
