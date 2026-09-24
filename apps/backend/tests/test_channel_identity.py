"""The allowlist that decides whose message this workspace will act on, written
before the module existed (§6). A bot in a server can be invoked by anybody in
it, so these tests are mostly about the ways an allowlist can be accidentally
widened.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agentbase.channels.identity import (
    ChannelIdentity,
    IdentityDirectory,
    refusal_text,
)

OWNER = ChannelIdentity(channel="discord", external_user_id="4210", identity="owner")


def test_an_allowlisted_user_resolves_to_its_internal_identity() -> None:
    directory = IdentityDirectory([OWNER])

    assert directory.resolve("discord", "4210") == "owner"


def test_an_unknown_external_id_resolves_to_nobody() -> None:
    directory = IdentityDirectory([OWNER])

    assert directory.resolve("discord", "9999") is None


def test_an_empty_allowlist_admits_nobody() -> None:
    """Deny by default, and note that this is the *opposite* default from the
    one Phase 6 chose for an agent definition's empty `auto_approve`.

    There the empty list means "inherit the workspace policy", because a
    strict reading made the workspace setting inert. Here there is no wider
    policy to fall back to, and the only two readings are "nobody" and
    "everybody": so the fallback directions are opposite and both are the
    safe one for their own case. A later reader tempted to make these
    consistent should make them consistent in *reasoning*, not in shape.
    """
    assert IdentityDirectory([]).resolve("discord", "4210") is None


def test_surrounding_whitespace_in_configuration_still_matches() -> None:
    """Narrowing-safe normalisation only.

    An id pasted out of Discord's "Copy User ID" with a trailing space would
    otherwise fail to match, and the symptom ("the bot ignores me") gives the
    owner nothing to go on.
    """
    directory = IdentityDirectory(
        [
            ChannelIdentity.model_validate(
                {"channel": "discord", "external_user_id": "  4210 ", "identity": "owner"}
            )
        ]
    )

    assert directory.resolve("discord", "4210") == "owner"


def test_matching_is_case_sensitive() -> None:
    """Case folding would merge two ids that the platform considers distinct.

    Every platform id in use here is numeric, so folding case looks free. It is
    not: it is a widening, and a widening of an allowlist is the one direction
    that costs something.
    """
    directory = IdentityDirectory(
        [ChannelIdentity(channel="discord", external_user_id="AbC", identity="owner")]
    )

    assert directory.resolve("discord", "abc") is None


def test_a_duplicate_entry_is_refused_rather_than_silently_shadowed() -> None:
    """Two rows for one user is a question with no good answer at read time.

    Whichever one resolution picks, the other is a rule the owner wrote and the
    product ignored. Rejecting on write means the ambiguity never reaches the
    lookup.
    """
    with pytest.raises(ValueError, match="appears twice"):
        IdentityDirectory.validated(
            [
                ChannelIdentity(channel="discord", external_user_id="1", identity="owner"),
                ChannelIdentity(channel="discord", external_user_id="1", identity="someone"),
            ]
        )


@pytest.mark.parametrize("blank", ["", "   "])
def test_an_empty_external_id_is_refused(blank: str) -> None:
    """Otherwise a blank row admits any caller whose id also normalises to
    empty, which is the one input an adapter can produce for "I could not
    determine the sender"."""
    with pytest.raises(ValidationError):
        ChannelIdentity(channel="discord", external_user_id=blank, identity="owner")


@pytest.mark.parametrize("blank", ["", "   "])
def test_an_empty_internal_identity_is_refused(blank: str) -> None:
    with pytest.raises(ValidationError):
        ChannelIdentity(channel="discord", external_user_id="1", identity=blank)


def test_the_refusal_shown_to_a_stranger_reveals_nothing_about_the_workspace() -> None:
    """The message goes to somebody who is, by definition, not trusted.

    It must not name the workspace, the owner, the allowlisted identities, or
    the goal they tried to run: all of which are things a stranger probing a
    bot would like to learn. The *log* records all of it; the reply does not.
    """
    message = refusal_text("discord")

    for leak in ("owner", "4210", "allowlist", "identity", "settings"):
        assert leak not in message.lower()
