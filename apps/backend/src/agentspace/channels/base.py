"""The `ChannelAdapter` protocol and the one normalized message shape.

:class:`InboundMessage` is the only shape the rest of the application sees; a
`discord.Interaction` stops here. :class:`ChannelAdapter` is the long-lived
connection and :class:`ChannelReply` a single conversation's reply handle,
which is the one thing platforms implement differently. `display_name` is
for reading, never for deciding: a user controls their own, and the allowlist
looks only at `external_user_id`.
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

#: The channels this application speaks: the same strings as `runs.origin`, minus `ui`.
ChannelName = Literal["discord"]

CHANNEL_NAMES: Final[tuple[ChannelName, ...]] = ("discord",)

#: What caused this message to reach us: the two triggers §1 constraint 6
#: permits, recorded so the constraint is auditable from the log.
TriggerKind = Literal["command", "mention"]


@dataclass(frozen=True, slots=True)
class InboundMessage:
    """One normalized message from a chat channel.

    :param thread_ref: where a reply belongs (a Discord channel id); stored as
        `runs.origin_ref`.
    """

    channel: ChannelName
    external_user_id: str
    text: str
    thread_ref: str
    ts: datetime
    trigger: TriggerKind = "command"
    display_name: str | None = None

    def as_payload(self, identity: str | None) -> dict[str, Any]:
        """The `channel.inbound` payload.

        ``identity`` is the resolved internal name, or ``None`` if refused.
        """
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
    """One conversation's reply handle: the platform-specific half.

    :meth:`update` edits the one message a run owns (one edited message is
    what keeps a run inside the rate limits); :meth:`ask` offers an approval
    affordance and may do nothing; :meth:`close` releases the platform's resources.
    """

    async def update(self, text: str) -> None:
        """Replace the run's message with ``text``."""
        ...

    async def ask(self, approval_id: str, prompt: str, risk: str) -> None:
        """Offer an Allow/Deny affordance for one pending approval."""
        ...

    async def close(self) -> None:
        """Finish this conversation. Called exactly once."""
        ...


@runtime_checkable
class ChannelAdapter(Protocol):
    """A long-lived connection to one chat platform, supervised by `ChannelService`.

    An adapter raises on a fatal error rather than looping; the supervisor
    decides whether to retry.
    """

    name: ChannelName

    async def run(self) -> None:
        """Connect and serve until cancelled. Returns only on a clean stop."""
        ...

    async def close(self) -> None:
        """Tear the connection down. Safe to call when never started."""
        ...
