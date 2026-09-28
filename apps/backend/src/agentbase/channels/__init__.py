"""Chat channels, including Discord, use the UI's run path.

Channels project the event log; they do not bypass orchestration. Inbound
messages become :class:`~agentbase.channels.base.InboundMessage` instances and
start through the same :class:`~agentbase.orchestrator.launcher.RunLauncher`
as `POST /runs`; outbound text is ``render(fold(events))``. Channel origin
never grants privilege (§1 constraint 5).
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

# Do not re-export service/adapter: settings imports ``ChannelIdentity`` here,
# and reaching the adapter would import ``discord.py`` while loading settings.

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
