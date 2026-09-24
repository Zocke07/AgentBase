"""`GET /channels`: whether the chat adapters are actually connected.

`PATCH /settings` knows what was asked for; only the running
:class:`~agentbase.channels.service.ChannelService` knows what happened. A
missing token, a library that failed to freeze and a gateway that will not
connect all look like a silent bot otherwise. No token is ever returned or
confirmed by value.
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
    """One adapter, as the settings screen renders it."""

    channel: str
    #: What the workspace settings ask for.
    enabled: bool
    #: Whether a bot token of the matching name reached the sidecar.
    configured: bool
    #: Whether the gateway connection is currently up.
    running: bool
    #: Consecutive failures since the last successful connection.
    failures: int
    #: The last failure, if any.
    last_error: str | None = None
    #: Senders this workspace refused, newest first, bounded; not in the event log.
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
