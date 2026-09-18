"""Schedules: a goal a space runs on its own at set times (§5 Phase 13).

A schedule is a goal, a cadence and a space. The scheduler in
:mod:`agentspace.orchestrator.scheduler` launches it through the same
:class:`~agentspace.orchestrator.launcher.RunLauncher` as the window and
Discord, so a scheduled run gets the space's roster, rules and folder and no
more. Nothing here runs while the app is closed: the sidecar is a child of the
window, so a time that passes while it is closed is handled at the next launch
according to the schedule's ``missed`` policy.

Cadences are wall-clock times in the machine's local zone (daily and weekly)
or a plain interval; ``next_run_at`` is stored in UTC and always recomputed
from the cadence and the clock, never added to the previous time.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from datetime import UTC, datetime, timedelta, tzinfo
from typing import TYPE_CHECKING, Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Callable

    from agentspace.store.db import Database

__all__ = [
    "Cadence",
    "DailyCadence",
    "IntervalCadence",
    "LocalZone",
    "MissedPolicy",
    "Schedule",
    "ScheduleNotFoundError",
    "ScheduleStore",
    "ScheduleValidationError",
    "WeeklyCadence",
    "describe",
    "next_occurrence",
    "parse_cadence",
]

MissedPolicy = Literal["run_on_launch", "skip"]

#: Bounds that keep a schedule a schedule: a name that fits in a list, a goal
#: no longer than the Home form accepts, an interval between one hour and a week.
MAX_NAME_LENGTH: Final[int] = 60
MAX_GOAL_LENGTH: Final[int] = 10_000
MAX_INTERVAL_HOURS: Final[int] = 24 * 7

_WEEKDAY_NAMES: Final[tuple[str, ...]] = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)


class ScheduleValidationError(ValueError):
    """A schedule was rejected. The message is written to be shown to a user."""

    def __init__(self, message: str, field: str) -> None:
        super().__init__(message)
        self.field = field


class ScheduleNotFoundError(LookupError):
    def __init__(self, schedule_id: str) -> None:
        super().__init__(f"no schedule with id {schedule_id!r}")
        self.schedule_id = schedule_id


# --- cadences ------------------------------------------------------------------


def _check_clock(value: str) -> str:
    parts = value.split(":")
    if len(parts) != 2 or not all(part.isdigit() and len(part) == 2 for part in parts):
        msg = "a time of day looks like 09:30"
        raise ValueError(msg)
    hour, minute = int(parts[0]), int(parts[1])
    if hour > 23 or minute > 59:
        msg = "a time of day looks like 09:30"
        raise ValueError(msg)
    return value


class DailyCadence(BaseModel):
    """Every day at a local time of day."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["daily"]
    #: ``HH:MM`` in the machine's local time.
    at: str

    @field_validator("at")
    @classmethod
    def _clock(cls, value: str) -> str:
        return _check_clock(value)


class WeeklyCadence(BaseModel):
    """On chosen weekdays at a local time of day."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["weekly"]
    at: str
    #: 0 is Monday, 6 is Sunday, as :meth:`datetime.weekday` counts.
    weekdays: list[int] = Field(min_length=1, max_length=7)

    @field_validator("at")
    @classmethod
    def _clock(cls, value: str) -> str:
        return _check_clock(value)

    @field_validator("weekdays")
    @classmethod
    def _days(cls, value: list[int]) -> list[int]:
        if any(day < 0 or day > 6 for day in value):
            msg = "weekdays count from 0 (Monday) to 6 (Sunday)"
            raise ValueError(msg)
        return sorted(set(value))


class IntervalCadence(BaseModel):
    """Every so many hours, counted from the last time it was due."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["interval"]
    every_hours: int = Field(ge=1, le=MAX_INTERVAL_HOURS)


#: A plain union rather than a discriminated one: the TypeScript emitter reads
#: `anyOf`, and `kind` is a literal on each member, so validation still picks
#: the right shape.
Cadence = DailyCadence | WeeklyCadence | IntervalCadence


_CADENCE_KINDS: Final[dict[str, type[DailyCadence | WeeklyCadence | IntervalCadence]]] = {
    "daily": DailyCadence,
    "weekly": WeeklyCadence,
    "interval": IntervalCadence,
}


def parse_cadence(raw: Any) -> Cadence:
    """Validate a cadence from JSON or a dict, with one message a user can act on.

    Dispatches on ``kind`` first: validating against the union would report
    every member's complaints, most of them about a shape the user never chose.
    """
    if isinstance(raw, DailyCadence | WeeklyCadence | IntervalCadence):
        return raw
    if not isinstance(raw, dict):
        raise ScheduleValidationError("a cadence is daily, weekly or an interval", "cadence")
    model = _CADENCE_KINDS.get(str(raw.get("kind")))
    if model is None:
        raise ScheduleValidationError("a cadence is daily, weekly or an interval", "cadence")
    try:
        return model.model_validate(raw)
    except ValidationError as exc:
        first = exc.errors()[0]
        message = str(first["msg"]).removeprefix("Value error, ")
        raise ScheduleValidationError(message, "cadence") from exc


def describe(cadence: Cadence) -> str:
    """The cadence as one plain sentence, the same one wherever it is shown."""
    if isinstance(cadence, DailyCadence):
        return f"Every day at {cadence.at}"
    if isinstance(cadence, WeeklyCadence):
        if len(cadence.weekdays) == 7:
            return f"Every day at {cadence.at}"
        if cadence.weekdays == [0, 1, 2, 3, 4]:
            return f"Weekdays at {cadence.at}"
        names = [f"{_WEEKDAY_NAMES[day]}s" for day in cadence.weekdays]
        joined = names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"
        return f"{joined} at {cadence.at}"
    if cadence.every_hours == 1:
        return "Every hour"
    if cadence.every_hours % 24 == 0:
        days = cadence.every_hours // 24
        return "Every day" if days == 1 else f"Every {days} days"
    return f"Every {cadence.every_hours} hours"


class LocalZone(tzinfo):
    """The machine's local time, correct for any wall time, through the C library.

    ``datetime.now().astimezone()`` freezes the offset in force right now, so
    "tomorrow at 09:00" computed the evening before a DST switch would land an
    hour off. Asking ``mktime`` about the wall time itself gives the offset
    that will apply then. This is the ``LocalTimezone`` recipe from the
    :mod:`datetime` documentation.
    """

    def __init__(self) -> None:
        # Read when built rather than when imported, so a process that resets
        # its zone (`time.tzset()` in a test) gets a zone that agrees with it.
        self._standard = timedelta(seconds=-time.timezone)
        self._summer = timedelta(seconds=-time.altzone) if time.daylight else self._standard
        self._shift = self._summer - self._standard

    def utcoffset(self, dt: datetime | None) -> timedelta:
        return self._summer if self._is_dst(dt) else self._standard

    def dst(self, dt: datetime | None) -> timedelta:
        return self._shift if self._is_dst(dt) else timedelta(0)

    def tzname(self, dt: datetime | None) -> str:
        return time.tzname[1 if self._is_dst(dt) else 0]

    def fromutc(self, dt: datetime) -> datetime:
        # `dt` carries this zone but holds a UTC wall time; read it as such.
        stamp = (dt.replace(tzinfo=UTC) - datetime(1970, 1, 1, tzinfo=UTC)).total_seconds()
        local = time.localtime(stamp)
        # The hour that repeats when summer time ends: the same wall time a
        # shift earlier is the first of the pair, so this one is the second.
        repeated = (
            self._shift != timedelta(0)
            and local[:6] == time.localtime(stamp - self._shift.total_seconds())[:6]
        )
        return datetime(*local[:6], microsecond=dt.microsecond, tzinfo=self, fold=int(repeated))

    def _is_dst(self, dt: datetime | None) -> bool:
        if dt is None:
            return False
        fields = (dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, dt.weekday(), 0, -1)
        return time.localtime(time.mktime(fields)).tm_isdst > 0


def _parse_clock(value: str) -> tuple[int, int]:
    hour, minute = value.split(":")
    return int(hour), int(minute)


def next_occurrence(cadence: Cadence, after: datetime, zone: tzinfo) -> datetime:
    """The first time strictly after ``after`` that the cadence names, in UTC.

    ``after`` is any aware instant; wall-clock cadences are read in ``zone``.
    """
    if isinstance(cadence, IntervalCadence):
        return (after + timedelta(hours=cadence.every_hours)).astimezone(UTC)

    hour, minute = _parse_clock(cadence.at)
    allowed = set(cadence.weekdays) if isinstance(cadence, WeeklyCadence) else set(range(7))
    local = after.astimezone(zone)
    day = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    # A ZoneInfo or LocalZone reads the offset from the wall time it is
    # given; re-attaching the zone after arithmetic is what makes that happen
    # across a DST change, where adding a day to an aware datetime would
    # carry the old offset.
    for offset in range(8):
        candidate = (day + timedelta(days=offset)).replace(tzinfo=zone)
        if candidate.weekday() in allowed and candidate > after:
            return candidate.astimezone(UTC)
    msg = "a weekly cadence always names a day within a week"  # pragma: no cover
    raise AssertionError(msg)  # pragma: no cover


# --- the row -------------------------------------------------------------------


class Schedule(BaseModel):
    """One row of `schedules`. Frozen: the scheduler reads it, then writes through the store."""

    model_config = ConfigDict(frozen=True)

    id: str
    space_id: str
    name: str
    goal: str
    cadence: Cadence
    missed: MissedPolicy = "run_on_launch"
    enabled: bool = True
    #: When the scheduler will next start this, in UTC. ``None`` while disabled.
    next_run_at: datetime | None = None
    last_run_at: datetime | None = None
    #: The run the scheduler last started, or ``None`` if that run was deleted.
    last_run_id: str | None = None
    #: What the scheduler did last time this was due, in words.
    last_outcome: str | None = None
    created_at: datetime
    updated_at: datetime


_SELECT: Final[str] = (
    "SELECT id, space_id, name, goal, cadence, missed, enabled, next_run_at, last_run_at,"
    " last_run_id, last_outcome, created_at, updated_at FROM schedules"
)


def _when(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value is not None else None


def _row_to_schedule(row: sqlite3.Row) -> Schedule:
    return Schedule(
        id=row["id"],
        space_id=row["space_id"],
        name=row["name"],
        goal=row["goal"],
        cadence=parse_cadence(json.loads(row["cadence"])),
        missed=row["missed"],
        enabled=bool(row["enabled"]),
        next_run_at=_when(row["next_run_at"]),
        last_run_at=_when(row["last_run_at"]),
        last_run_id=row["last_run_id"],
        last_outcome=row["last_outcome"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


def _validated_columns(fields: dict[str, Any], *, creating: bool) -> dict[str, Any]:
    """The columns a create or update may write, each checked.

    A key that is absent is left alone. ``cadence`` is stored as JSON, and
    ``enabled`` is what decides whether ``next_run_at`` is set at all.
    """
    columns: dict[str, Any] = {}

    if "name" in fields or creating:
        name = str(fields.get("name", "")).strip()
        if not name:
            raise ScheduleValidationError("a schedule needs a name", "name")
        if len(name) > MAX_NAME_LENGTH:
            raise ScheduleValidationError(
                f"a name is at most {MAX_NAME_LENGTH} characters", "name"
            )
        columns["name"] = name

    if "goal" in fields or creating:
        goal = str(fields.get("goal", "")).strip()
        if not goal:
            raise ScheduleValidationError("a schedule needs a goal to run", "goal")
        if len(goal) > MAX_GOAL_LENGTH:
            raise ScheduleValidationError(
                f"a goal is at most {MAX_GOAL_LENGTH} characters", "goal"
            )
        columns["goal"] = goal

    if "cadence" in fields or creating:
        raw = fields.get("cadence")
        if raw is None:
            raise ScheduleValidationError("a schedule needs a cadence", "cadence")
        cadence = (
            raw
            if isinstance(raw, DailyCadence | WeeklyCadence | IntervalCadence)
            else parse_cadence(raw)
        )
        columns["cadence"] = json.dumps(cadence.model_dump(mode="json"), sort_keys=True)

    if "missed" in fields:
        missed = fields["missed"]
        if missed not in ("run_on_launch", "skip"):
            raise ScheduleValidationError(
                "a missed run is either run at the next launch or skipped", "missed"
            )
        columns["missed"] = missed

    if "enabled" in fields:
        columns["enabled"] = 1 if bool(fields["enabled"]) else 0

    return columns


class ScheduleStore:
    """Reads and writes `schedules`, keeping `next_run_at` consistent with `enabled`.

    The store computes the next occurrence itself on every write that could
    change it, so a row is never enabled without a time or disabled with one.
    The clock and zone are injectable for the tests.
    """

    def __init__(
        self,
        db: Database,
        *,
        clock: Callable[[], datetime] | None = None,
        zone: tzinfo | None = None,
    ) -> None:
        self._db = db
        self._clock: Callable[[], datetime] = (
            clock if clock is not None else (lambda: datetime.now(UTC))
        )
        self.zone: tzinfo = zone if zone is not None else LocalZone()

    def now(self) -> datetime:
        return self._clock()

    # --- reads -------------------------------------------------------------

    async def list_all(self, space_id: str | None = None) -> list[Schedule]:
        return await asyncio.to_thread(self._list_sync, space_id)

    def _list_sync(self, space_id: str | None) -> list[Schedule]:
        with self._db.read() as connection:
            if space_id is None:
                rows = connection.execute(f"{_SELECT} ORDER BY name COLLATE NOCASE").fetchall()
            else:
                rows = connection.execute(
                    f"{_SELECT} WHERE space_id = ? ORDER BY name COLLATE NOCASE", (space_id,)
                ).fetchall()
        return [_row_to_schedule(row) for row in rows]

    async def get(self, schedule_id: str) -> Schedule | None:
        return await asyncio.to_thread(self._get_sync, schedule_id)

    def _get_sync(self, schedule_id: str) -> Schedule | None:
        with self._db.read() as connection:
            row = connection.execute(f"{_SELECT} WHERE id = ?", (schedule_id,)).fetchone()
        return _row_to_schedule(row) if row is not None else None

    async def require(self, schedule_id: str) -> Schedule:
        schedule = await self.get(schedule_id)
        if schedule is None:
            raise ScheduleNotFoundError(schedule_id)
        return schedule

    async def due(self, now: datetime) -> list[Schedule]:
        """Every enabled schedule whose time has come, earliest first."""
        return await asyncio.to_thread(self._due_sync, now)

    def _due_sync(self, now: datetime) -> list[Schedule]:
        with self._db.read() as connection:
            rows = connection.execute(
                f"{_SELECT} WHERE enabled = 1 AND next_run_at IS NOT NULL AND next_run_at <= ?"
                " ORDER BY next_run_at",
                (now.astimezone(UTC).isoformat(),),
            ).fetchall()
        return [_row_to_schedule(row) for row in rows]

    async def earliest(self) -> datetime | None:
        """When the next enabled schedule is due, so the loop can sleep until then."""
        return await asyncio.to_thread(self._earliest_sync)

    def _earliest_sync(self) -> datetime | None:
        with self._db.read() as connection:
            row = connection.execute(
                "SELECT MIN(next_run_at) AS soonest FROM schedules"
                " WHERE enabled = 1 AND next_run_at IS NOT NULL"
            ).fetchone()
        return _when(row["soonest"]) if row is not None else None

    # --- writes ------------------------------------------------------------

    async def create(self, fields: dict[str, Any]) -> Schedule:
        return await asyncio.to_thread(self._create_sync, fields)

    def _create_sync(self, fields: dict[str, Any]) -> Schedule:
        space_id = fields.get("space_id")
        if not isinstance(space_id, str) or not space_id:
            raise ScheduleValidationError("a schedule belongs to a space", "space_id")
        columns = _validated_columns(fields, creating=True)
        enabled = columns.get("enabled", 1)
        now = self.now()
        cadence = parse_cadence(json.loads(columns["cadence"]))
        next_run = next_occurrence(cadence, now, self.zone).isoformat() if enabled else None
        schedule_id = str(uuid.uuid4())
        stamp = now.isoformat()

        with self._db.write() as connection:
            space = connection.execute(
                "SELECT id FROM spaces WHERE id = ?", (space_id,)
            ).fetchone()
            if space is None:
                raise ScheduleValidationError(f"no space with id {space_id!r}", "space_id")
            keys = ["id", "space_id", *columns, "next_run_at", "created_at", "updated_at"]
            placeholders = ", ".join("?" for _ in keys)
            connection.execute(
                f"INSERT INTO schedules ({', '.join(keys)}) VALUES ({placeholders})",  # noqa: S608
                (schedule_id, space_id, *columns.values(), next_run, stamp, stamp),
            )
            row = connection.execute(f"{_SELECT} WHERE id = ?", (schedule_id,)).fetchone()
        return _row_to_schedule(row)

    async def update(self, schedule_id: str, changes: dict[str, Any]) -> Schedule:
        """Apply a partial update. A cadence or enabled change recomputes `next_run_at`."""
        return await asyncio.to_thread(self._update_sync, schedule_id, changes)

    def _update_sync(self, schedule_id: str, changes: dict[str, Any]) -> Schedule:
        columns = _validated_columns(changes, creating=False)
        now = self.now()

        with self._db.write() as connection:
            row = connection.execute(f"{_SELECT} WHERE id = ?", (schedule_id,)).fetchone()
            if row is None:
                raise ScheduleNotFoundError(schedule_id)
            existing = _row_to_schedule(row)

            enabled = bool(columns.get("enabled", 1 if existing.enabled else 0))
            cadence = (
                parse_cadence(json.loads(columns["cadence"]))
                if "cadence" in columns
                else existing.cadence
            )
            if "cadence" in columns or "enabled" in columns:
                columns["next_run_at"] = (
                    next_occurrence(cadence, now, self.zone).isoformat() if enabled else None
                )

            if columns:
                columns["updated_at"] = now.isoformat()
                assignments = ", ".join(f"{column} = ?" for column in columns)
                connection.execute(
                    f"UPDATE schedules SET {assignments} WHERE id = ?",  # noqa: S608
                    (*columns.values(), schedule_id),
                )
            row = connection.execute(f"{_SELECT} WHERE id = ?", (schedule_id,)).fetchone()
        return _row_to_schedule(row)

    async def advance(
        self,
        schedule_id: str,
        *,
        now: datetime,
        outcome: str,
        run_id: str | None,
        enabled: bool = True,
    ) -> Schedule:
        """Record what the scheduler did and move the schedule to its next time.

        The next time is computed from ``now``, not from the time that was
        due, so a catch-up after days closed does not fire again immediately.
        ``enabled=False`` retires the schedule, for a space that can no longer run.
        """
        return await asyncio.to_thread(
            self._advance_sync, schedule_id, now, outcome, run_id, enabled
        )

    def _advance_sync(
        self, schedule_id: str, now: datetime, outcome: str, run_id: str | None, enabled: bool
    ) -> Schedule:
        with self._db.write() as connection:
            row = connection.execute(f"{_SELECT} WHERE id = ?", (schedule_id,)).fetchone()
            if row is None:
                raise ScheduleNotFoundError(schedule_id)
            existing = _row_to_schedule(row)
            next_run = (
                next_occurrence(existing.cadence, now, self.zone).isoformat()
                if enabled
                else None
            )
            fired = now.astimezone(UTC).isoformat()
            connection.execute(
                "UPDATE schedules SET next_run_at = ?, last_outcome = ?, enabled = ?,"
                " last_run_at = COALESCE(?, last_run_at), last_run_id = COALESCE(?, last_run_id),"
                " updated_at = ? WHERE id = ?",
                (
                    next_run,
                    outcome,
                    1 if enabled else 0,
                    fired if run_id is not None else None,
                    run_id,
                    fired,
                    schedule_id,
                ),
            )
            row = connection.execute(f"{_SELECT} WHERE id = ?", (schedule_id,)).fetchone()
        return _row_to_schedule(row)

    async def note_run(
        self, schedule_id: str, *, now: datetime, run_id: str, outcome: str
    ) -> Schedule:
        """Record a run started outside the cadence ("Run now"); `next_run_at` stays."""
        return await asyncio.to_thread(self._note_run_sync, schedule_id, now, run_id, outcome)

    def _note_run_sync(
        self, schedule_id: str, now: datetime, run_id: str, outcome: str
    ) -> Schedule:
        stamp = now.astimezone(UTC).isoformat()
        with self._db.write() as connection:
            changed = connection.execute(
                "UPDATE schedules SET last_run_at = ?, last_run_id = ?, last_outcome = ?,"
                " updated_at = ? WHERE id = ?",
                (stamp, run_id, outcome, stamp, schedule_id),
            ).rowcount
            if not changed:
                raise ScheduleNotFoundError(schedule_id)
            row = connection.execute(f"{_SELECT} WHERE id = ?", (schedule_id,)).fetchone()
        return _row_to_schedule(row)

    async def delete(self, schedule_id: str) -> None:
        await asyncio.to_thread(self._delete_sync, schedule_id)

    def _delete_sync(self, schedule_id: str) -> None:
        with self._db.write() as connection:
            deleted = connection.execute(
                "DELETE FROM schedules WHERE id = ?", (schedule_id,)
            ).rowcount
        if not deleted:
            raise ScheduleNotFoundError(schedule_id)
