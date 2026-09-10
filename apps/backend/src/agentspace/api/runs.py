"""Run endpoints, and the scripted debug run.

`POST /runs` creates the row and hands it to the orchestrator. The debug
endpoint below predates the orchestrator and still earns its place: it exercises
the whole event spine and SSE path with no provider, no API key and no spend,
which is what makes it usable from a test, from `curl`, and from the Phase 7 UI
before a key has been configured.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Annotated, Any, Final

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from agentspace.api.stream import SSE_HEADERS, parse_last_event_id, run_stream
from agentspace.events.types import Event, EventType, Run, RunOrigin
from agentspace.orchestrator import execute_run

if TYPE_CHECKING:
    from collections.abc import Coroutine

    from agentspace.events.bus import EventBus
    from agentspace.events.store import EventStore

__all__ = ["router"]

logger = logging.getLogger("agentspace.api")

router = APIRouter()

#: The scripted debug sequence — 20 events, which at the default 500 ms step
#: is the "~20 events over 10 seconds" §5 Phase 2 asks for. Shaped like a real
#: run (spawn, think, call a tool, get it approved, hand off, finish) so the
#: Phase 7 graph has something meaningful to render before an orchestrator
#: exists to produce it.
_FAKE_RUN_SCRIPT: Final[tuple[tuple[EventType, str | None, dict[str, Any]], ...]] = (
    (EventType.RUN_STARTED, None, {"goal": "Summarise the quarterly report"}),
    (EventType.AGENT_SPAWNED, "supervisor", {"role": "Plans and delegates"}),
    (EventType.AGENT_THINKING, "supervisor", {"text": "Two subtasks: research, then write."}),
    (EventType.AGENT_SPAWNED, "researcher", {"role": "Gathers source material"}),
    (EventType.AGENT_HANDOFF, "supervisor", {"to": "researcher", "task": "Find the figures"}),
    (EventType.LLM_REQUEST, "researcher", {"model": "claude-sonnet-5", "input_tokens": 412}),
    (EventType.LLM_TOKEN, "researcher", {"text": "I will start by reading "}),
    (EventType.LLM_TOKEN, "researcher", {"text": "the report from disk."}),
    (EventType.LLM_RESPONSE, "researcher", {"output_tokens": 38, "stop_reason": "tool_use"}),
    (EventType.TOOL_REQUESTED, "researcher", {"tool": "read_file", "args": {"path": "q3.md"}}),
    (EventType.APPROVAL_REQUESTED, "researcher", {"prompt": 'Read "q3.md"?', "risk": "low"}),
    (EventType.APPROVAL_RESOLVED, "researcher", {"decision": "approved", "by": "user"}),
    (EventType.TOOL_APPROVED, "researcher", {"tool": "read_file"}),
    (EventType.TOOL_CALLED, "researcher", {"tool": "read_file", "args": {"path": "q3.md"}}),
    (EventType.TOOL_RESULT, "researcher", {"tool": "read_file", "bytes": 8214}),
    (EventType.AGENT_MESSAGE, "researcher", {"text": "Revenue up 12% QoQ; churn flat."}),
    (EventType.AGENT_COMPLETED, "researcher", {"steps": 4}),
    (EventType.AGENT_HANDOFF, "researcher", {"to": "supervisor", "task": "Summary ready"}),
    (EventType.AGENT_COMPLETED, "supervisor", {"steps": 6}),
    (EventType.RUN_COMPLETED, None, {"summary": "Quarterly report summarised."}),
)

#: Milliseconds between scripted events. 20 x 500 ms = the 10 seconds in §5.
DEFAULT_STEP_MS: Final[int] = 500


class CreateRunRequest(BaseModel):
    goal: str = Field(min_length=1, max_length=10_000)
    origin: RunOrigin = "ui"
    origin_ref: str | None = None


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
    """Create a run and start the orchestrator on it.

    Returns as soon as the row exists rather than waiting for the run to
    finish. A run takes minutes and the client watches it over SSE — holding
    the request open would make the event stream a second way to learn the same
    thing, and would put a proxy's idle timeout in charge of when a run ends.
    """
    run = await _store(request).create_run(
        goal=body.goal, origin=body.origin, origin_ref=body.origin_ref
    )

    _spawn(request, _drive_run(request, run.id, body.goal))
    return run


async def _drive_run(request: Request, run_id: str, goal: str) -> None:
    """Hand one run to the orchestrator.

    Every failure path inside `execute_run` writes its own terminal event, so
    nothing here needs to — and nothing here should, because a second opinion
    about how a run ended is exactly the drift §2 rules out.
    """
    state = request.app.state
    await execute_run(
        state.store,
        state.settings,
        state.agents,
        state.ledger,
        state.secrets,
        run_id,
        goal,
    )


def _spawn(request: Request, coroutine: Coroutine[Any, Any, None]) -> None:
    """Run a coroutine in the background, keeping a strong reference to it.

    `asyncio` holds only a weak reference to a bare task, so without this the
    loop may garbage-collect a run that is still going. The set is drained by
    the lifespan handler on shutdown.
    """
    task = asyncio.create_task(coroutine)
    tasks: set[asyncio.Task[None]] = request.app.state.background_tasks
    tasks.add(task)
    task.add_done_callback(tasks.discard)


@router.get("/runs/{run_id}")
async def get_run(request: Request, run_id: str) -> Run:
    return await _require_run(request, run_id)


@router.get("/runs/{run_id}/events/history")
async def get_run_events(request: Request, run_id: str, after_seq: int = 0) -> list[Event]:
    """The event log as a plain array.

    Replay in Phase 7 goes through the SSE path so that live and replay share
    one renderer (§5 Phase 7). This exists for tests and for `curl` inspection.
    """
    await _require_run(request, run_id)
    return await _store(request).read(run_id, after_seq=after_seq)


# --- the SSE stream ---------------------------------------------------------


@router.get("/runs/{run_id}/events")
async def stream_run_events(request: Request, run_id: str) -> StreamingResponse:
    """Server-sent events for one run, resumable via `Last-Event-ID`."""
    await _require_run(request, run_id)

    after_seq = parse_last_event_id(request.headers.get("last-event-id"))

    return StreamingResponse(
        run_stream(_store(request), _bus(request), run_id, after_seq),
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
        # App shutting down mid-run. The log keeps whatever was committed.
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
    """Start a scripted run so the event spine can be exercised without an LLM.

    ``step_ms`` exists so tests do not have to wait ten seconds; the default is
    the pace §5 Phase 2 specifies.
    """
    store = _store(request)
    run = await store.create_run(goal="Debug run — scripted event sequence", origin="ui")

    _spawn(request, _play_script(store, run.id, step_ms))
    return run
