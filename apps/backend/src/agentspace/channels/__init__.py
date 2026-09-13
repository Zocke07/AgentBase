"""Chat channels: Discord, reaching the same run the UI does.

A channel is a second projection of the event log, not a second path into
the orchestrator: inbound, an adapter's message becomes an
:class:`~agentspace.channels.base.InboundMessage` and the run starts through
the same :class:`~agentspace.orchestrator.launcher.RunLauncher` as
`POST /runs`; outbound, the chat message is `render(fold(events))`. Nothing
here is privileged (§1 constraint 5): the gate never learns where a run came from.
"""

from __future__ import annotations

from agentspace.channels.base import (
    CHANNEL_NAMES,
    ChannelAdapter,
    ChannelName,
    ChannelReply,
    InboundMessage,
    TriggerKind,
)
from agentspace.channels.identity import (
    ChannelIdentity,
    IdentityDirectory,
    refusal_text,
)
from agentspace.channels.render import ChatView, fold, render
from agentspace.channels.throttle import Throttle

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
