"""Who is allowed to address this workspace, and as whom.

A bot in a server can be invoked by anybody in it, and §1 constraint 6 only
covers ambient chatter, not a stranger typing the command. This table is
what stops them: an id with no entry resolves to nobody, and a message from
nobody starts no run. Otherwise a stranger reaches the owner's API budget,
their desktop (every approval dialog) and, through `run_shell`, their user
account. An empty list therefore means nobody, unlike a definition's empty
`auto_approve`: in both places the empty case must not be the widening one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

from agentbase.channels.base import ChannelName

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

__all__ = [
    "ChannelIdentity",
    "IdentityDirectory",
    "refusal_text",
]

#: Whitespace stripped, since ids are pasted; nothing else normalised, since
#: case folding could merge two ids a platform considers distinct.
_Trimmed = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ChannelIdentity(BaseModel):
    """One allowlist entry: this person, on this channel, is that identity."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    channel: ChannelName
    external_user_id: _Trimmed
    identity: _Trimmed


class IdentityDirectory:
    """Resolution over a list of :class:`ChannelIdentity`.

    Built fresh on each inbound message, so a removed entry stops admitting at once.
    """

    __slots__ = ("_by_key",)

    def __init__(self, entries: Iterable[ChannelIdentity]) -> None:
        self._by_key: dict[tuple[str, str], str] = {}
        for entry in entries:
            self._by_key.setdefault((entry.channel, entry.external_user_id), entry.identity)

    @staticmethod
    def validated(entries: Sequence[ChannelIdentity]) -> list[ChannelIdentity]:
        """Check a proposed allowlist, refusing a duplicate on write rather than shadowing it on
        read.
        """
        seen: set[tuple[str, str]] = set()
        for entry in entries:
            key = (entry.channel, entry.external_user_id)
            if key in seen:
                msg = (
                    f"{entry.channel} user {entry.external_user_id!r} appears twice "
                    f"in the channel allowlist; each user may map to one identity."
                )
                raise ValueError(msg)
            seen.add(key)
        return list(entries)

    def resolve(self, channel: str, external_user_id: str) -> str | None:
        """The internal identity for this sender, or ``None`` to refuse them."""
        return self._by_key.get((channel, external_user_id.strip()))

    def __len__(self) -> int:
        return len(self._by_key)


def refusal_text(channel: ChannelName) -> str:
    """What an unrecognised sender is told: nothing about the workspace, only a refusal."""
    # One channel today; the parameter stays so a second one names itself.
    where = {"discord": "this Discord account"}[channel]
    return (
        f"This agent workspace is not configured to accept requests from {where}. "
        f"Nothing was run."
    )
