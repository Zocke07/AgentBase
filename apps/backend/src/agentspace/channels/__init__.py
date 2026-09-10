"""Chat channels — Discord and Telegram, reaching the same run the UI does.

§5 Phase 8's last requirement is that "a run started from Discord must appear
live in the dashboard, and vice versa. Same event log, no special-casing." The
way that is achieved here is by having the channel be a *second projection of
the event log* rather than a second path into the orchestrator:

- inbound, an adapter normalizes its platform's message into
  :class:`~agentspace.channels.base.InboundMessage`, and the run it starts goes
  through :class:`~agentspace.orchestrator.launcher.RunLauncher` — the same
  object `POST /runs` uses;
- outbound, the chat message is :func:`~agentspace.channels.render.render` of
  :func:`~agentspace.channels.render.fold`, which is a pure function of the
  events. The dashboard folds the same log into a graph. Neither is the truth
  and neither can drift from it.

**Nothing here is privileged.** §1 constraint 5 ends with "no privileged paths
for any channel", so a tool call from a Discord-originated run reaches
:class:`~agentspace.tools.approval.ApprovalService` by the identical route a UI
run does — it is the same run object, in the same process, holding the same
runtime. There is no channel branch in the gate to get wrong, because the gate
never learns where the run came from.
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

# `service` and the two adapters are deliberately NOT re-exported here.
# `agentspace.store.settings` imports `ChannelIdentity` from this package, and a
# package __init__ that reached the adapters would make loading the settings
# model import `discord.py` and `python-telegram-bot` — turning a freeze problem
# in either library into a sidecar that cannot read its own configuration.
# Import `agentspace.channels.service` explicitly instead.

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
