"""`ChannelAdapter` protocol and normalized message shape.

The application sees only :class:`InboundMessage`, never a
``discord.Interaction``. :class:`ChannelAdapter` owns a long-lived connection;
:class:`ChannelReply` is the platform-specific reply handle. Use
``external_user_id`` for allowlists, never user-controlled ``display_name``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, Literal, Protocol, runtime_checkable

if TYPE_CHECKING:
    from datetime import datetime

__all__ = [
    "CHANNEL_NAMES",
    "ChannelAdapter",
    "ChannelName",
    "ChannelReply",
    "InboundMessage",
    "TriggerKind",
]

#: Supported channels: ``runs.origin`` values excluding ``ui``.
ChannelName = Literal["discord"]

CHANNEL_NAMES: Final[tuple[ChannelName, ...]] = ("discord",)

#: §1 constraint 6's permitted triggers, recorded for log auditability.
TriggerKind = Literal["command", "mention"]


@dataclass(frozen=True, slots=True)
class InboundMessage:
    """Normalized chat message.

    :param thread_ref: reply location (a Discord channel ID), stored as
        ``runs.origin_ref``.
    """

    channel: ChannelName
    external_user_id: str
    text: str
    thread_ref: str
    ts: datetime
    trigger: TriggerKind = "command"
    display_name: str | None = None

    def as_payload(self, identity: str | None) -> dict[str, Any]:
        """Build the ``channel.inbound`` payload; identity is resolved or ``None``."""
        return {
            "channel": self.channel,
            "external_user_id": self.external_user_id,
            "text": self.text,
            "thread_ref": self.thread_ref,
            "ts": self.ts.isoformat(),
            "trigger": self.trigger,
            "display_name": self.display_name,
            "identity": identity,
        }


@runtime_checkable
class ChannelReply(Protocol):
    """Platform-specific reply handle for one conversation.

    :meth:`update` edits the run's one rate-limited message; :meth:`ask` may
    offer approval controls; :meth:`close` releases platform resources.
    """

    async def update(self, text: str) -> None:
        """Replace the run message with ``text``."""
        ...

    async def ask(self, approval_id: str, prompt: str, risk: str) -> None:
        """Offer an Allow/Deny affordance for one pending approval."""
        ...

    async def close(self) -> None:
        """Finish this conversation; called exactly once."""
        ...


@runtime_checkable
class ChannelAdapter(Protocol):
    """Long-lived chat-platform connection supervised by ``ChannelService``.

    Raise fatal errors; the supervisor decides retries.
    """

    name: ChannelName

    async def run(self) -> None:
        """Connect and serve until cancellation; return only after a clean stop."""
        ...

    async def close(self) -> None:
        """Tear down the connection; safe before start."""
        ...
