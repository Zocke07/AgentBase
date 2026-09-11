"""The `ChannelAdapter` protocol and the one normalized message shape.

§5 Phase 8: "Both adapters normalize to `{channel, external_user_id, text,
thread_ref, ts}` and emit `channel.inbound`." :class:`InboundMessage` is that
tuple, and it is the *only* shape the rest of the application ever sees — a
`discord.Interaction` stops here.

**Two protocols, not one, because a platform differs in one place only.**
:class:`ChannelAdapter` is the long-lived connection: start it, close it, ask
whether it is healthy. :class:`ChannelReply` is a single conversation's reply
handle, and it exists because "edit the message you already sent" is the one
operation chat platforms genuinely implement differently. Everything between
those two — identity, refusal, starting the run, folding the log, throttling,
emitting `channel.outbound` — is shared, so a second channel would inherit
all of it and implement only the edit. There was a second one, Telegram, and
it was removed on 2026-09-11 having never held a session (CLAUDE.md records
the decision); the seam stays, because it is what made removing it a matter
of deleting one file.

**`display_name` is for reading, never for deciding.** A chat user controls
their own display name, so authorizing on it would let anyone impersonate an
allowlisted user by renaming themselves. It rides in the payload because a log
saying `421...` is unreadable a week later, and `external_user_id` is the only
field :mod:`agentspace.channels.identity` will look at.
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

#: The channels this application speaks. Deliberately the same strings §4 gives
#: `runs.origin`, minus `ui`, so a run's origin column and its adapter name are
#: never two spellings of one fact.
ChannelName = Literal["discord"]

CHANNEL_NAMES: Final[tuple[ChannelName, ...]] = ("discord",)

#: What caused this message to reach us. §1 constraint 6 permits exactly two
#: triggers — "explicit commands/mentions only" — and recording which one fired
#: is what makes that constraint auditable from the log rather than merely
#: claimed in a docstring. There is no member for an ambient channel message,
#: because there is no code path that produces one.
TriggerKind = Literal["command", "mention"]


@dataclass(frozen=True, slots=True)
class InboundMessage:
    """One normalized message from a chat channel.

    :param thread_ref: where a reply belongs — a Discord channel id. Stored
        as `runs.origin_ref` (§4), which is what makes a run resumable as a
        conversation rather than only as a row.
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

        ``identity`` is the internal name this external user resolved to, or
        ``None`` when the message was refused. Recording a refusal in the log
        is the point: "somebody who is not on the allowlist asked this
        workspace to do something" is exactly the event an owner wants to be
        able to find afterwards, and a refusal that wrote nothing would leave
        no trace of it at all.
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

    An adapter creates one of these per inbound message and the shared driver
    in :mod:`agentspace.channels.service` calls it. Three methods, because
    three things genuinely differ between platforms:

    - :meth:`update` edits the *one* message a run owns. One edited message
      rather than a new message per event is what keeps a run inside both
      platforms' rate limits without the throttle having to be clever, and it
      is also the better reading experience: a run's status stays in one place
      instead of scrolling away.
    - :meth:`ask` offers an approval affordance — buttons, on Discord. It is
      allowed to do nothing, and does when the workspace policy keeps approvals
      in the dashboard.
    - :meth:`close` releases whatever the platform needs releasing.
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
    """A long-lived connection to one chat platform.

    Started and stopped by :class:`~agentspace.channels.service.ChannelService`,
    which supervises it. An adapter is expected to raise rather than to loop
    forever on a fatal error — the supervisor is what decides whether to retry,
    so an adapter that swallowed its own failures would make the channel appear
    healthy while receiving nothing.
    """

    name: ChannelName

    async def run(self) -> None:
        """Connect and serve until cancelled. Returns only on a clean stop."""
        ...

    async def close(self) -> None:
        """Tear the connection down. Safe to call when never started."""
        ...
