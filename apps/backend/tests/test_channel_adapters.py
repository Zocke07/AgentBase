"""What the adapters ask their platforms for, asserted without a network.

Two of §5 Phase 8's requirements are not behaviours that show up in a run — they
are things the adapter must never *request*, and the only way they fail is
silently, by working perfectly while listening to far more than they should.

- "Do **not** request the `MessageContent` privileged intent." Without it,
  Discord does not deliver the text of messages this bot was not mentioned in,
  so §1 constraint 6 ("never ingest ambient channel messages into agent
  context") holds because the data never arrives rather than because this code
  declines to read it. A future edit that flips `message_content = True` to fix
  some unrelated annoyance would quietly convert a structural guarantee into a
  code-review one.
- "Slash commands and @mentions only." There must be exactly those two
  triggers and no third.

These are cheap to assert and expensive to notice by hand, which is the whole
argument for pinning them.
"""

from __future__ import annotations

import discord

from agentspace.channels.discord_adapter import INTENTS


def test_the_message_content_intent_is_not_requested() -> None:
    """§5 Phase 8, verbatim, and the reason the mention path is safe."""
    assert INTENTS.message_content is False


def test_no_privileged_intent_is_requested_at_all() -> None:
    """The other two privileged intents cost a review requirement as well.

    `members` and `presences` are not needed to answer a command, and each one
    is a Discord verification step and a larger attack surface for no gain.
    """
    assert INTENTS.members is False
    assert INTENTS.presences is False


def test_the_only_intent_requested_is_guilds() -> None:
    """Everything else off, so a new default in `discord.py` cannot widen this.

    `Intents.none()` plus one flag means an upgrade that adds a
    newly-non-privileged intent to `Intents.default()` does not silently arrive
    here.
    """
    enabled = {name for name, value in INTENTS if value}

    assert enabled == {"guilds"}


def test_the_baseline_is_narrower_than_discord_pys_own_default() -> None:
    """A regression guard with teeth: `Intents.default()` is the tempting fix.

    It is what most examples use, it is not privileged, and swapping it in
    would turn every flag below on at once.
    """
    default_enabled = {name for name, value in discord.Intents.default() if value}
    ours = {name for name, value in INTENTS if value}

    assert ours < default_enabled


def test_commands_are_registered_per_guild_rather_than_globally() -> None:
    """A global `tree.sync()` is cached by Discord for up to an hour.

    That is what the documentation and nearly every example show, and it is
    wrong for this product in a way that is invisible from the inside: the
    first live run against a real server connected, reported `running: true`
    through `GET /channels`, logged nothing further, and produced no
    interaction when the command was typed — because the command did not exist
    in the client yet. There is no error anywhere in that sequence.

    Guild-scoped commands take effect immediately, and this is a local-first
    personal application whose bot lives in one or two servers. So this asserts
    the *shape* of the call rather than the behaviour: `_sync_one` takes a
    guild and passes it to both `copy_global_to` and `sync`, and a regression
    to the global form would have to change that signature.
    """
    import inspect

    from agentspace.channels.discord_adapter import DiscordAdapter

    source = inspect.getsource(DiscordAdapter._sync_one)

    assert "copy_global_to(guild=guild)" in source
    assert "sync(guild=guild)" in source

    # And the bare global form is gone from the whole adapter.
    module = inspect.getsource(DiscordAdapter)
    assert "self._tree.sync()" not in module


def test_a_guild_joined_after_startup_also_gets_the_commands() -> None:
    """Otherwise a server added while the app is running has no `/agent` until
    the next restart, which is the same invisible failure one step later."""
    import inspect

    from agentspace.channels.discord_adapter import DiscordAdapter

    assert "on_guild_join" in inspect.getsource(DiscordAdapter._register)
