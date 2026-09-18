"""Schedule endpoints: CRUD over `schedules`, a run-now, and a cadence preview.

The rules live in :mod:`agentspace.store.schedules`; this maps each refusal
to a status code and a `{message, field}` body, and nudges the scheduler
after every write so a new time is honoured without waiting for its poll.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from agentspace.events.types import Run
from agentspace.store.schedules import (
    MAX_GOAL_LENGTH,
    MAX_NAME_LENGTH,
    Cadence,
    MissedPolicy,
    Schedule,
    ScheduleNotFoundError,
    ScheduleValidationError,
    describe,
    next_occurrence,
)
from agentspace.store.spaces import SpaceArchivedError, SpaceNotFoundError

if TYPE_CHECKING:
    from agentspace.orchestrator.launcher import RunLauncher
    from agentspace.orchestrator.scheduler import Scheduler
    from agentspace.store.schedules import ScheduleStore

__all__ = ["router"]

router = APIRouter()

#: How many coming times a preview lists: enough to show a weekly pattern.
PREVIEW_COUNT = 3


class CreateScheduleRequest(BaseModel):
    space_id: str
    name: str = Field(min_length=1, max_length=MAX_NAME_LENGTH)
    goal: str = Field(min_length=1, max_length=MAX_GOAL_LENGTH)
    cadence: Cadence
    missed: MissedPolicy = "run_on_launch"
    enabled: bool = True


class UpdateScheduleRequest(BaseModel):
    """A partial update; fields left out are untouched."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=MAX_NAME_LENGTH)
    goal: str | None = Field(default=None, min_length=1, max_length=MAX_GOAL_LENGTH)
    cadence: Cadence | None = None
    missed: MissedPolicy | None = None
    enabled: bool | None = None


class ScheduleResponse(Schedule):
    """A schedule, plus its cadence in words so every screen says the same thing."""

    summary: str


class PreviewRequest(BaseModel):
    cadence: Cadence


class SchedulePreview(BaseModel):
    """What a cadence means, before it is saved."""

    summary: str
    #: The next few times it names, in UTC; the UI shows them in local time.
    next: list[datetime]


def _schedules(request: Request) -> ScheduleStore:
    store: ScheduleStore = request.app.state.schedules
    return store


def _scheduler(request: Request) -> Scheduler:
    scheduler: Scheduler = request.app.state.scheduler
    return scheduler


def _launcher(request: Request) -> RunLauncher:
    launcher: RunLauncher = request.app.state.launcher
    return launcher


def _reject(message: str, field: str | None) -> HTTPException:
    return HTTPException(status_code=400, detail={"message": message, "field": field})


def _respond(schedule: Schedule) -> ScheduleResponse:
    return ScheduleResponse(**schedule.model_dump(), summary=describe(schedule.cadence))


@router.get("/schedules")
async def list_schedules(
    request: Request, space_id: str | None = None
) -> list[ScheduleResponse]:
    """Every schedule, or one space's."""
    return [_respond(schedule) for schedule in await _schedules(request).list_all(space_id)]


@router.get("/schedules/{schedule_id}")
async def get_schedule(request: Request, schedule_id: str) -> ScheduleResponse:
    try:
        return _respond(await _schedules(request).require(schedule_id))
    except ScheduleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/schedules", status_code=201)
async def create_schedule(request: Request, body: CreateScheduleRequest) -> ScheduleResponse:
    try:
        schedule = await _schedules(request).create(body.model_dump())
    except ScheduleValidationError as exc:
        raise _reject(str(exc), exc.field) from exc
    _scheduler(request).wake()
    return _respond(schedule)


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
    return _respond(schedule)


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
    """Start this schedule's run right now, leaving its next time as it was."""
    store = _schedules(request)
    try:
        schedule = await store.require(schedule_id)
    except ScheduleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    try:
        run = await _launcher(request).launch(
            schedule.goal,
            space_id=schedule.space_id,
            origin="schedule",
            origin_ref=schedule.id,
        )
    except SpaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SpaceArchivedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await store.note_run(
        schedule.id, now=store.now(), run_id=run.id, outcome="Started by hand."
    )
    return run


@router.post("/schedules/preview")
async def preview_schedule(request: Request, body: PreviewRequest) -> SchedulePreview:
    """The cadence in words and its next few times, for the editor before a save."""
    store = _schedules(request)
    upcoming: list[datetime] = []
    after = store.now()
    for _ in range(PREVIEW_COUNT):
        after = next_occurrence(body.cadence, after, store.zone)
        upcoming.append(after)
    return SchedulePreview(summary=describe(body.cadence), next=upcoming)
