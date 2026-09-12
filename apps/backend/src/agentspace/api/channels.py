"""`GET /channels`: whether the chat adapters are actually connected.

§3's layout does not name this module, and it earns its place the same way
`tools/runtime.py` and `orchestrator/limits.py` did: without it, "Discord is
enabled" is a setting the user wrote and nothing anywhere says whether it
worked. A bot token that was never put in the keychain, a library that failed to
freeze, a gateway that has been refusing to connect for ten minutes, all three
present identically as a bot that says nothing, and all three are things the
user can fix once told.

This reports state the settings endpoint cannot: `PATCH /settings` knows what
was asked for, and only the running :class:`~agentspace.channels.service.ChannelService`
knows what happened.

**No token is ever returned, or confirmed by value.** `configured` says a
credential of that name arrived over the stdin handshake, exactly as
`GET /settings`'s `configured_secrets` does: the name, never the value.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Request
from pydantic import BaseModel

if TYPE_CHECKING:
    from agentspace.channels.service import ChannelService

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
    #: The last failure, if any: a bad token reads very differently from a
    #: dropped websocket, and the user can only act on one of them.
    last_error: str | None = None
    #: Senders this workspace refused, newest first. Deliberately not in the
    #: event log: a refused message started no run, and §4 gives every event a
    #: NOT NULL `run_id`. Bounded, because the people in it are by definition
    #: unauthenticated.
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
