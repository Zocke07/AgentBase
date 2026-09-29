"""Run endpoints and the scripted debug run.

The debug run exercises event storage and SSE without a provider, key, or
spend, so tests, `curl`, and an unconfigured window can use it.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Annotated, Any, Final

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from agentbase.api.stream import SSE_HEADERS, parse_last_event_id, run_stream
from agentbase.events.store import (
    DEFAULT_RUN_LIST_LIMIT,
    MAX_RUN_LIST_LIMIT,
    RunNotFoundError,
    RunUnfinishedError,
)
from agentbase.events.types import Event, EventType, Run, RunOrigin
from agentbase.store.spaces import SpaceArchivedError, SpaceNotFoundError

if TYPE_CHECKING:
    from collections.abc import Coroutine

    from agentbase.events.bus import EventBus
    from agentbase.events.store import EventStore
    from agentbase.orchestrator.launcher import RunLauncher

__all__ = ["router"]

logger = logging.getLogger("agentbase.api")

router = APIRouter()

#: Scripted debug sequence: 20 events over 10 seconds at the default step
#: (§5 Phase 2), shaped and keyed like a real run for identical rendering.
_FAKE_RUN_SCRIPT: Final[tuple[tuple[EventType, str | None, dict[str, Any]], ...]] = (
    (EventType.RUN_STARTED, None, {"goal": "Summarise the quarterly report"}),
    (
        EventType.AGENT_SPAWNED,
        "supervisor",
        {"role": "Plans and delegates", "allowed_tools": [], "max_steps": 6},
    ),
    (EventType.AGENT_THINKING, "supervisor", {"step": 1}),
    (
        EventType.AGENT_SPAWNED,
        "researcher",
        {"role": "Gathers source material", "allowed_tools": ["read_file"], "max_steps": 4},
    ),
    (EventType.AGENT_HANDOFF, "supervisor", {"to": "researcher", "task": "Find the figures"}),
    (
        EventType.LLM_REQUEST,
        "researcher",
        {"provider": "demo", "model": "scripted", "step": 1, "messages": []},
    ),
    (EventType.LLM_TOKEN, "researcher", {"text": "I will start by reading "}),
    (EventType.LLM_TOKEN, "researcher", {"text": "the report from disk."}),
    (
        EventType.LLM_RESPONSE,
        "researcher",
        {
            "text": "I will start by reading the report from disk.",
            "input_tokens": 412,
            "output_tokens": 38,
            "stop_reason": "tool_use",
        },
    ),
    (
        EventType.TOOL_REQUESTED,
        "researcher",
        {"tool": "read_file", "args": {"path": "q3.md"}, "call_id": "demo-1"},
    ),
    (
        EventType.APPROVAL_REQUESTED,
        "researcher",
        {
            "approval_id": "demo-approval-1",
            "tool": "read_file",
            "args": {"path": "q3.md"},
            "risk": "low",
            "prompt": 'Agent "researcher" wants to read q3.md: Allow / Deny',
            "summary": "read the file q3.md",
        },
    ),
    (
        EventType.APPROVAL_RESOLVED,
        "researcher",
        {
            "approval_id": "demo-approval-1",
            "tool": "read_file",
            "status": "approved",
            "automatic": False,
        },
    ),
    (
        EventType.TOOL_APPROVED,
        "researcher",
        {
            "tool": "read_file",
            "call_id": "demo-1",
            "approval_id": "demo-approval-1",
            "automatic": False,
        },
    ),
    (
        EventType.TOOL_CALLED,
        "researcher",
        {"tool": "read_file", "args": {"path": "q3.md"}, "call_id": "demo-1"},
    ),
    (
        EventType.TOOL_RESULT,
        "researcher",
        {
            "tool": "read_file",
            "call_id": "demo-1",
            "result": "Q3 revenue: $4.2M (+12% QoQ). Churn: 2.1% (flat).",
        },
    ),
    (
        EventType.AGENT_MESSAGE,
        "researcher",
        {"to": "supervisor", "text": "Revenue up 12% QoQ; churn flat."},
    ),
    (EventType.AGENT_COMPLETED, "researcher", {"reason": "finished", "steps": 1}),
    (EventType.AGENT_HANDOFF, "researcher", {"to": "supervisor", "task": "Summary ready"}),
    (EventType.AGENT_COMPLETED, "supervisor", {"reason": "finished", "steps": 1}),
    (EventType.RUN_COMPLETED, None, {"summary": "Quarterly report summarised."}),
)

#: Ended statuses; runs in these states cannot be cancelled.
_TERMINAL: Final[frozenset[str]] = frozenset({"completed", "failed", "cancelled"})

#: Milliseconds between scripted events; 20 x 500 ms = §5's 10 seconds.
DEFAULT_STEP_MS: Final[int] = 500


class CreateRunRequest(BaseModel):
    goal: str = Field(min_length=1, max_length=10_000)
    #: Run location; omitted selects the default space.
    space_id: str | None = None
    origin: RunOrigin = "ui"
    origin_ref: str | None = None
    excluded_citations: list[str] = Field(default_factory=list, max_length=20)
    #: Step through the run: every call asks, whatever the policy would answer.
    #: The manual fallback and debug mode; refusals the app gives stay.
    supervised: bool = False


def _store(request: Request) -> EventStore:
    store: EventStore = request.app.state.store
    return store


def _bus(request: Request) -> EventBus:
    bus: EventBus = request.app.state.bus
    return bus


async def _require_run(request: Request, run_id: str) -> Run:
    run = await _store(request).get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"no run with id {run_id!r}")
    return run


# --- runs -------------------------------------------------------------------


@router.post("/runs", status_code=201)
async def create_run(request: Request, body: CreateRunRequest) -> Run:
    """Create a run and start its orchestrator.

    Return after creating its row; clients follow it over SSE. The shared
    :class:`~agentbase.orchestrator.launcher.RunLauncher` also serves channels.
    """
    try:
        return await _launcher(request).launch(
            body.goal,
            space_id=body.space_id,
            origin=body.origin,
            origin_ref=body.origin_ref,
            excluded_citations=tuple(body.excluded_citations),
            supervised=body.supervised,
        )
    except SpaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SpaceArchivedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _launcher(request: Request) -> RunLauncher:
    launcher: RunLauncher = request.app.state.launcher
    return launcher


def _spawn(request: Request, coroutine: Coroutine[Any, Any, None]) -> None:
    """Run a coroutine in the background and retain a strong task reference.

    `asyncio` only weakly retains bare tasks; lifespan drains this set at shutdown.
    """
    task = asyncio.create_task(coroutine)
    tasks: set[asyncio.Task[None]] = request.app.state.background_tasks
    tasks.add(task)
    task.add_done_callback(tasks.discard)


@router.get("/runs")
async def list_runs(
    request: Request,
    limit: Annotated[int, Query(ge=1, le=MAX_RUN_LIST_LIMIT)] = DEFAULT_RUN_LIST_LIMIT,
    space_id: str | None = None,
    origin: RunOrigin | None = None,
) -> list[Run]:
    """List recent runs, newest first; ``origin`` filters UI, schedule, or Discord runs."""
    return await _store(request).list_runs(limit, space_id, origin)


@router.get("/runs/{run_id}")
async def get_run(request: Request, run_id: str) -> Run:
    return await _require_run(request, run_id)


@router.post("/runs/{run_id}/cancel", status_code=202)
async def cancel_run(request: Request, run_id: str) -> Run:
    """Ask a run to stop.

    202 means it stops at its next deadline check and writes `run.cancelled`,
    so its returned row may remain `running`. Finished or nonlocal runs return 409.
    """
    run = await _require_run(request, run_id)
    if run.status in _TERMINAL:
        raise HTTPException(status_code=409, detail=f"run {run_id} is already {run.status}")

    launcher: RunLauncher = request.app.state.launcher
    if not await launcher.cancel(run_id, "Cancelled by the user."):
        raise HTTPException(
            status_code=409,
            detail=f"run {run_id} is not being driven by this process and cannot be cancelled",
        )
    return run


@router.delete("/runs/{run_id}", status_code=204)
async def delete_run(request: Request, run_id: str) -> Response:
    """Remove a finished run, events, and approvals; retain its spend.

    Return 409 for unfinished runs so their orchestrator cannot lose its log.
    Also refuse a locally driven run that just turned terminal: the
    orchestrator releases it shortly after status write. See
    :meth:`~agentbase.events.store.EventStore.delete_run` for retained data.
    """
    launcher: RunLauncher = request.app.state.launcher
    if run_id in launcher.live:
        raise HTTPException(
            status_code=409,
            detail=f"run {run_id} is still running in this process; cancel it first",
        )
    try:
        await _store(request).delete_run(run_id)
    except RunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"no run with id {run_id!r}") from exc
    except RunUnfinishedError as exc:
        raise HTTPException(
            status_code=409,
            detail=f"run {run_id} is still {exc.status}; cancel it first, then delete it",
        ) from exc
    return Response(status_code=204)


@router.get("/runs/{run_id}/events/history")
async def get_run_events(request: Request, run_id: str, after_seq: int = 0) -> list[Event]:
    """Return the event log as an array for dashboard history, tests, and `curl`."""
    await _require_run(request, run_id)
    return await _store(request).read(run_id, after_seq=after_seq)


# --- the SSE stream ---------------------------------------------------------


@router.get("/runs/{run_id}/events")
async def stream_run_events(
    request: Request,
    run_id: str,
    after_seq: Annotated[int, Query(ge=0)] = 0,
) -> StreamingResponse:
    """Stream one run as resumable SSE via `Last-Event-ID`.

    ``after_seq`` is the first-connection cursor; on reconnect, the further
    header cursor wins.
    """
    await _require_run(request, run_id)

    resume_from = max(after_seq, parse_last_event_id(request.headers.get("last-event-id")))

    return StreamingResponse(
        run_stream(_store(request), _bus(request), run_id, resume_from),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


# --- debug ------------------------------------------------------------------


async def _play_script(store: EventStore, run_id: str, step_ms: int) -> None:
    """Emit the scripted sequence, one event every ``step_ms``."""
    try:
        await store.set_run_status(run_id, "running")

        for index, (event_type, agent_id, payload) in enumerate(_FAKE_RUN_SCRIPT):
            if index:
                await asyncio.sleep(step_ms / 1000)
            await store.append(run_id, event_type, payload, agent_id=agent_id)

        await store.set_run_status(run_id, "completed")
    except asyncio.CancelledError:
        # On shutdown mid-run, retain already committed log entries.
        raise
    except Exception:
        logger.exception("fake run %s failed", run_id)
        await store.append(run_id, EventType.RUN_FAILED, {"reason": "debug script error"})
        await store.set_run_status(run_id, "failed")


@router.post("/debug/fake_run", status_code=201)
async def fake_run(
    request: Request,
    step_ms: Annotated[int, Query(ge=0, le=5000)] = DEFAULT_STEP_MS,
) -> Run:
    """Start a scripted run that exercises events without a model."""
    store = _store(request)
    run = await store.create_run(goal="Debug run: scripted event sequence", origin="ui")

    _spawn(request, _play_script(store, run.id, step_ms))
    return run
