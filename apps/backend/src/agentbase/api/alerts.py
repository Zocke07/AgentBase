"""Market watch endpoints (BUILD_SPEC Phase 18).

Alerts across spaces for the window's badge and notifications, marking them
seen, and each space's watch status and on/off switch. The thresholds stay
in the space's ``config/monitor.json``, which Knowledge edits like any file.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict

from agentbase.orchestrator.monitor import MonitorConfigError, MonitorStatus
from agentbase.store.alerts import MarketAlert
from agentbase.tools.sandbox import SandboxViolationError

if TYPE_CHECKING:
    from agentbase.orchestrator.monitor import MarketMonitor
    from agentbase.store.alerts import AlertStore
    from agentbase.store.spaces import Space, SpaceStore

__all__ = ["router"]

router = APIRouter()


class AlertsResponse(BaseModel):
    alerts: list[MarketAlert]
    unseen: int


class SeenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: ``None`` marks every space's alerts seen.
    space_id: str | None = None


class SeenResponse(BaseModel):
    marked: int


class MonitorSwitchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool


@router.get("/alerts")
async def list_alerts(
    request: Request,
    space_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> AlertsResponse:
    """Newest alerts first, in one space or all of them, and how many are unseen."""
    alerts = _alerts(request)
    return AlertsResponse(
        alerts=await alerts.recent(space_id, limit), unseen=await alerts.unseen(space_id)
    )


@router.post("/alerts/seen")
async def mark_alerts_seen(request: Request, body: SeenRequest) -> SeenResponse:
    marked = await _alerts(request).mark_seen(body.space_id, datetime.now(UTC))
    return SeenResponse(marked=marked)


@router.get("/spaces/{space_id}/monitor")
async def monitor_status(request: Request, space_id: str) -> MonitorStatus:
    return await _monitor(request).read_status(await _space(request, space_id))


@router.put("/spaces/{space_id}/monitor")
async def switch_monitor(
    request: Request, space_id: str, body: MonitorSwitchRequest
) -> MonitorStatus:
    """Turn the watch on or off by its file, writing the starter file the first time."""
    space = await _space(request, space_id)
    if space.archived:
        raise HTTPException(
            status_code=409,
            detail={"message": f"{space.name!r} is archived.", "field": None},
        )
    monitor = _monitor(request)
    try:
        monitor.set_enabled(space, enabled=body.enabled)
    except (MonitorConfigError, SandboxViolationError) as exc:
        raise HTTPException(
            status_code=422, detail={"message": str(exc), "field": "enabled"}
        ) from exc
    return await monitor.read_status(space)


async def _space(request: Request, space_id: str) -> Space:
    spaces: SpaceStore = request.app.state.spaces
    space = await spaces.get(space_id)
    if space is None:
        raise HTTPException(
            status_code=404,
            detail={"message": f"No space with id {space_id!r}.", "field": None},
        )
    return space


def _alerts(request: Request) -> AlertStore:
    store: AlertStore = request.app.state.alerts
    return store


def _monitor(request: Request) -> MarketMonitor:
    monitor: MarketMonitor = request.app.state.monitor
    return monitor
