"""Schedule CRUD, run-now, and cadence-preview endpoints.

:mod:`agentbase.store.schedules` owns the rules; this maps refusals to
``{message, field}`` responses and wakes the scheduler after every write.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from agentbase.events.types import Run
from agentbase.orchestrator.scheduler import ScheduleBusyError
from agentbase.store.schedules import (
    MAX_GOAL_LENGTH,
    MAX_NAME_LENGTH,
    AfterCadence,
    Cadence,
    MissedPolicy,
    Schedule,
    ScheduleNotFoundError,
    ScheduleValidationError,
    describe,
    next_occurrence,
)
from agentbase.store.spaces import SpaceArchivedError, SpaceNotFoundError

if TYPE_CHECKING:
    from agentbase.orchestrator.scheduler import Scheduler
    from agentbase.store.schedules import ScheduleStore

__all__ = ["router"]

router = APIRouter()

#: Preview occurrence count: enough to show a weekly pattern.
PREVIEW_COUNT = 3


class CreateScheduleRequest(BaseModel):
    space_id: str
    name: str = Field(min_length=1, max_length=MAX_NAME_LENGTH)
    goal: str = Field(min_length=1, max_length=MAX_GOAL_LENGTH)
    cadence: Cadence
    missed: MissedPolicy = "run_on_launch"
    enabled: bool = True
    #: Run time limit; ``None`` inherits the space limit.
    max_run_seconds: int | None = Field(default=None, ge=1)


class UpdateScheduleRequest(BaseModel):
    """Partial update; omitted fields remain unchanged."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=MAX_NAME_LENGTH)
    goal: str | None = Field(default=None, min_length=1, max_length=MAX_GOAL_LENGTH)
    cadence: Cadence | None = None
    missed: MissedPolicy | None = None
    enabled: bool | None = None
    max_run_seconds: int | None = Field(default=None, ge=1)


class ScheduleResponse(Schedule):
    """Schedule plus a shared human-readable cadence."""

    summary: str


class PreviewRequest(BaseModel):
    cadence: Cadence


class SchedulePreview(BaseModel):
    """Cadence preview before saving."""

    summary: str
    #: Upcoming UTC times; the UI converts them to local time.
    next: list[datetime]


def _schedules(request: Request) -> ScheduleStore:
    store: ScheduleStore = request.app.state.schedules
    return store


def _scheduler(request: Request) -> Scheduler:
    scheduler: Scheduler = request.app.state.scheduler
    return scheduler


def _reject(message: str, field: str | None) -> HTTPException:
    return HTTPException(status_code=400, detail={"message": message, "field": field})


def _respond(schedule: Schedule, names: dict[str, str]) -> ScheduleResponse:
    followed = (
        names.get(schedule.cadence.schedule_id)
        if isinstance(schedule.cadence, AfterCadence)
        else None
    )
    return ScheduleResponse(
        **schedule.model_dump(), summary=describe(schedule.cadence, followed)
    )


async def _named(request: Request, schedule: Schedule) -> ScheduleResponse:
    """One schedule's response, naming the schedule a stage follows."""
    names: dict[str, str] = {}
    if isinstance(schedule.cadence, AfterCadence):
        followed = await _schedules(request).get(schedule.cadence.schedule_id)
        if followed is not None:
            names[followed.id] = followed.name
    return _respond(schedule, names)


@router.get("/schedules")
async def list_schedules(
    request: Request, space_id: str | None = None
) -> list[ScheduleResponse]:
    """List every schedule or one space's schedules."""
    listed = await _schedules(request).list_all(space_id)
    # A stage follows a schedule in its own space, so the list names it.
    names = {schedule.id: schedule.name for schedule in listed}
    return [_respond(schedule, names) for schedule in listed]


@router.get("/schedules/{schedule_id}")
async def get_schedule(request: Request, schedule_id: str) -> ScheduleResponse:
    try:
        return await _named(request, await _schedules(request).require(schedule_id))
    except ScheduleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/schedules", status_code=201)
async def create_schedule(request: Request, body: CreateScheduleRequest) -> ScheduleResponse:
    try:
        schedule = await _schedules(request).create(body.model_dump())
    except ScheduleValidationError as exc:
        raise _reject(str(exc), exc.field) from exc
    _scheduler(request).wake()
    return await _named(request, schedule)


@router.patch("/schedules/{schedule_id}")
async def update_schedule(
    request: Request, schedule_id: str, body: UpdateScheduleRequest
) -> ScheduleResponse:
    changes: dict[str, Any] = {name: getattr(body, name) for name in body.model_fields_set}
    if not changes:
        raise _reject("no changes were supplied", None)
    try:
        schedule = await _schedules(request).update(schedule_id, changes)
    except ScheduleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ScheduleValidationError as exc:
        raise _reject(str(exc), exc.field) from exc
    _scheduler(request).wake()
    return await _named(request, schedule)


@router.delete("/schedules/{schedule_id}", status_code=204)
async def delete_schedule(request: Request, schedule_id: str) -> Response:
    try:
        await _schedules(request).delete(schedule_id)
    except ScheduleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    _scheduler(request).wake()
    return Response(status_code=204)


@router.post("/schedules/{schedule_id}/run", status_code=201)
async def run_schedule_now(request: Request, schedule_id: str) -> Run:
    """Start this schedule now without changing its next time.

    It goes through the scheduler, so a run started by hand gets the
    schedule's own time limit and the same guard against overlapping itself.
    """
    try:
        schedule = await _schedules(request).require(schedule_id)
    except ScheduleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    try:
        return await _scheduler(request).run_now(schedule)
    except SpaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (SpaceArchivedError, ScheduleBusyError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/schedules/preview")
async def preview_schedule(request: Request, body: PreviewRequest) -> SchedulePreview:
    """Preview a cadence's wording and upcoming times before saving.

    A stage that follows another schedule has no times of its own to show.
    """
    store = _schedules(request)
    followed: str | None = None
    if isinstance(body.cadence, AfterCadence):
        target = await store.get(body.cadence.schedule_id)
        followed = target.name if target is not None else None
    upcoming: list[datetime] = []
    after: datetime | None = store.now()
    for _ in range(PREVIEW_COUNT):
        after = next_occurrence(body.cadence, after, store.zone) if after is not None else None
        if after is None:
            break
        upcoming.append(after)
    return SchedulePreview(summary=describe(body.cadence, followed), next=upcoming)
