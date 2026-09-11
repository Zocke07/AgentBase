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
from agentspace.events.store import DEFAULT_RUN_LIST_LIMIT, MAX_RUN_LIST_LIMIT
from agentspace.events.types import Event, EventType, Run, RunOrigin

if TYPE_CHECKING:
    from collections.abc import Coroutine

    from agentspace.events.bus import EventBus
    from agentspace.events.store import EventStore
    from agentspace.orchestrator.launcher import RunLauncher

__all__ = ["router"]

logger = logging.getLogger("agentspace.api")

router = APIRouter()

#: The scripted debug sequence — 20 events, which at the default 500 ms step
#: is the "~20 events over 10 seconds" §5 Phase 2 asks for. Shaped like a real
#: run (spawn, think, call a tool, get it approved, hand off, finish) so the
#: Phase 7 graph has something meaningful to render before an orchestrator
#: exists to produce it — and, since it is what the dashboard shows before any
#: key is configured, shaped *exactly* like one: each payload carries the keys
#: the real emitters write and the reducer reads. It once said ``decision``
#: where the reducer reads ``status`` and ``bytes`` where it reads ``result``,
#: and the demo run rendered an expired approval with an empty result.
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
            "prompt": 'Agent "researcher" wants to read q3.md — Allow / Deny',
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

    **The work of starting a run is not done here.** Phase 8 gave the chat
    channels the same job, and assembling `execute_run`'s arguments at three
    call sites would be the eighth instance of this project's recurring bug: one
    list duplicated, correct everywhere on the day it was written, silently
    divergent afterwards. :class:`~agentspace.orchestrator.launcher.RunLauncher`
    is the single copy.
    """
    return await _launcher(request).launch(
        body.goal, origin=body.origin, origin_ref=body.origin_ref
    )


def _launcher(request: Request) -> RunLauncher:
    launcher: RunLauncher = request.app.state.launcher
    return launcher


def _spawn(request: Request, coroutine: Coroutine[Any, Any, None]) -> None:
    """Run a coroutine in the background, keeping a strong reference to it.

    `asyncio` holds only a weak reference to a bare task, so without this the
    loop may garbage-collect work that is still going. The set is drained by
    the lifespan handler on shutdown. Only the debug script uses this now; a
    real run goes through the launcher, which keeps the same references.
    """
    task = asyncio.create_task(coroutine)
    tasks: set[asyncio.Task[None]] = request.app.state.background_tasks
    tasks.add(task)
    task.add_done_callback(tasks.discard)


@router.get("/runs")
async def list_runs(
    request: Request,
    limit: Annotated[int, Query(ge=1, le=MAX_RUN_LIST_LIMIT)] = DEFAULT_RUN_LIST_LIMIT,
) -> list[Run]:
    """Recent runs, newest first — what the Phase 7 replay picker reads.

    §5 Phase 7 requires "Replay: scrub any past run from the event log", and a
    user cannot scrub a run they cannot find. The alternative — a UI keeping
    its own list of the runs it happens to have seen — would make the client an
    authority on something the database already knows, which is the drift §2
    exists to prevent.
    """
    return await _store(request).list_runs(limit)


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
async def stream_run_events(
    request: Request,
    run_id: str,
    after_seq: Annotated[int, Query(ge=0)] = 0,
) -> StreamingResponse:
    """Server-sent events for one run, resumable via `Last-Event-ID`.

    ``after_seq`` is the same cursor by another route. A browser's
    ``EventSource`` cannot send ``Last-Event-ID`` on its *first* connection,
    so a client that had already loaded the history had no way to say so and
    received the whole log a second time. When both are present the header
    wins if it is further along: a browser reconnecting keeps the original
    URL, query included, and adds the header for the last frame it saw.
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
