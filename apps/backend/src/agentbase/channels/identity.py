"""Workspace chat allowlist and identity mapping.

§1 constraint 6 limits ambient chatter, not strangers issuing commands. An
unlisted ID resolves to nobody and starts no run; otherwise strangers reach
the owner's API budget, approval dialogs, and potentially their account via
``run_shell``. An empty list therefore admits nobody, unlike a definition's
empty ``auto_approve``; neither empty case may widen access.
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

#: Strip pasted whitespace only; case folding could merge platform-distinct IDs.
_Trimmed = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ChannelIdentity(BaseModel):
    """Allowlist entry mapping one channel user to one identity."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    channel: ChannelName
    external_user_id: _Trimmed
    identity: _Trimmed


class IdentityDirectory:
    """Resolve :class:`ChannelIdentity` entries.

    Rebuild per inbound message so removals take effect immediately.
    """

    __slots__ = ("_by_key",)

    def __init__(self, entries: Iterable[ChannelIdentity]) -> None:
        self._by_key: dict[tuple[str, str], str] = {}
        for entry in entries:
            self._by_key.setdefault((entry.channel, entry.external_user_id), entry.identity)

    @staticmethod
    def validated(entries: Sequence[ChannelIdentity]) -> list[ChannelIdentity]:
        """Reject duplicate entries on write instead of shadowing them on read."""
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
        """Return sender's internal identity, or ``None`` to refuse them."""
        return self._by_key.get((channel, external_user_id.strip()))

    def __len__(self) -> int:
        return len(self._by_key)


def refusal_text(channel: ChannelName) -> str:
    """Return an unrecognized-sender refusal without workspace details."""
    # Keep parameter so future channels identify themselves.
    where = {"discord": "this Discord account"}[channel]
    return (
        f"This agent workspace is not configured to accept requests from {where}. "
        f"Nothing was run."
    )
