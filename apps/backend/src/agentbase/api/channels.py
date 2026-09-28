"""`GET /channels`: actual chat-adapter connectivity.

`PATCH /settings` records intent; only
:class:`~agentbase.channels.service.ChannelService` knows the outcome. Missing
tokens, frozen-library failures, and rejected gateways otherwise look like a
silent bot. Never return or confirm a token value.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Request
from pydantic import BaseModel

if TYPE_CHECKING:
    from agentbase.channels.service import ChannelService

__all__ = ["router"]

router = APIRouter()


class ChannelStatusResponse(BaseModel):
    """Adapter status rendered by the settings screen."""

    channel: str
    #: Whether workspace settings request it.
    enabled: bool
    #: Whether the matching bot token reached the sidecar.
    configured: bool
    #: Whether its gateway connection is up.
    running: bool
    #: Consecutive failures since its last successful connection.
    failures: int
    #: The last failure, if any.
    last_error: str | None = None
    #: Recent refused senders, newest first; not stored in the event log.
    refused: list[str] = []


def _service(request: Request) -> ChannelService | None:
    service: ChannelService | None = getattr(request.app.state, "channels", None)
    return service


@router.get("/channels")
async def list_channels(request: Request) -> list[ChannelStatusResponse]:
    service = _service(request)
    if service is None:
        return []

    return [
        ChannelStatusResponse(
            channel=status.channel,
            enabled=status.enabled,
            configured=status.configured,
            running=status.running,
            failures=status.failures,
            last_error=status.last_error,
            refused=list(status.refused),
        )
        for status in service.status()
    ]
