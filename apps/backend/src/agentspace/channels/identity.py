"""Who is allowed to address this workspace, and as whom.

§5 Phase 8: "Map external user IDs to an internal identity so budget and
permissions apply uniformly regardless of origin." The mapping does two jobs,
and the second one is the load-bearing one.

*Attribution.* A run's log says which internal identity asked for it, so
`channel.inbound` is answerable a month later.

*Authorization.* A Discord bot invited to a server can be invoked by anybody in
that server. §1 constraint 6 stops
the bot ingesting ambient chatter; it does not stop a stranger typing the
command deliberately, which is an *explicit* trigger and therefore permitted by
that constraint. What stops them is this table: an external id with no entry
resolves to nobody, and a message from nobody starts no run.

That is not a hypothetical hardening. The three things a stranger's command
would otherwise reach are the owner's monthly API budget, the owner's desktop
(every `medium`/`high` tool call raises a dialog on it), and — through
`run_shell` — the owner's user account.

**Deny by default, which is the opposite of the Phase 6 decision about an empty
`auto_approve`, and deliberately so.** There an empty list means "inherit the
workspace policy", because a strict reading made the workspace setting inert.
Here there is no wider policy to inherit and the two candidate readings are
"nobody" and "everybody". The shapes look inconsistent; the reasoning is the
same in both places, which is that the empty case must not be the widening one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

from agentspace.channels.base import ChannelName

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

__all__ = [
    "ChannelIdentity",
    "IdentityDirectory",
    "refusal_text",
]

#: Configuration is typed by hand and pasted out of a chat client, so surrounding
#: whitespace is stripped. Nothing else is normalised: case folding would merge
#: two ids a platform considers distinct, and merging entries in an allowlist is
#: a widening. Narrowing-safe transformations only.
_Trimmed = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ChannelIdentity(BaseModel):
    """One allowlist entry: this person, on this channel, is that identity."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    channel: ChannelName
    external_user_id: _Trimmed
    identity: _Trimmed


class IdentityDirectory:
    """Resolution over a list of :class:`ChannelIdentity`.

    Built fresh from the workspace settings on each inbound message rather than
    cached. The list is a handful of entries and the lookup happens once per
    chat command, so the cost is nothing — and the alternative is a directory
    that keeps admitting somebody the owner has just removed.
    """

    __slots__ = ("_by_key",)

    def __init__(self, entries: Iterable[ChannelIdentity]) -> None:
        self._by_key: dict[tuple[str, str], str] = {}
        for entry in entries:
            self._by_key.setdefault((entry.channel, entry.external_user_id), entry.identity)

    @staticmethod
    def validated(entries: Sequence[ChannelIdentity]) -> list[ChannelIdentity]:
        """Check a proposed allowlist, raising on anything ambiguous.

        Called from the settings model, so a duplicate is refused when it is
        written rather than silently shadowed when it is read. Whichever entry
        resolution happened to pick, the other would be a rule the owner wrote
        and the product ignored.
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
    """What an unrecognised sender is told.

    Addressed to somebody who is by definition not trusted, so it names nothing
    about the workspace: not the owner, not the other allowlisted identities,
    not the goal they tried to run, not where the allowlist lives. A stranger
    probing a bot learns only that it declined.

    The corresponding `channel.inbound` event records the full detail, because
    the owner is the one who needs to be able to add them.
    """
    # One channel today; the parameter stays so a second one names itself.
    where = {"discord": "this Discord account"}[channel]
    return (
        f"This agent workspace is not configured to accept requests from {where}. "
        f"Nothing was run."
    )
