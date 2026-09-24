"""Chat channels: Discord, reaching the same run the UI does.

A channel is a second projection of the event log, not a second path into
the orchestrator: inbound, an adapter's message becomes an
:class:`~agentbase.channels.base.InboundMessage` and the run starts through
the same :class:`~agentbase.orchestrator.launcher.RunLauncher` as
`POST /runs`; outbound, the chat message is `render(fold(events))`. Nothing
here is privileged (§1 constraint 5): the gate never learns where a run came from.
"""

from __future__ import annotations

from agentbase.channels.base import (
    CHANNEL_NAMES,
    ChannelAdapter,
    ChannelName,
    ChannelReply,
    InboundMessage,
    TriggerKind,
)
from agentbase.channels.identity import (
    ChannelIdentity,
    IdentityDirectory,
    refusal_text,
)
from agentbase.channels.render import ChatView, fold, render
from agentbase.channels.throttle import Throttle

# `service` and the adapter are deliberately not re-exported: the settings
# model imports `ChannelIdentity` from here, and reaching the adapter would
# make loading settings import `discord.py`.

__all__ = [
    "CHANNEL_NAMES",
    "ChannelAdapter",
    "ChannelIdentity",
    "ChannelName",
    "ChannelReply",
    "ChatView",
    "IdentityDirectory",
    "InboundMessage",
    "Throttle",
    "TriggerKind",
    "fold",
    "refusal_text",
    "render",
]
