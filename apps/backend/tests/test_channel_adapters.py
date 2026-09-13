"""What the adapters ask their platforms for, asserted without a network.

Two §5 Phase 8 requirements fail only silently, by working while listening to
more than they should: no `MessageContent` intent (so ambient messages never
arrive, and §1 constraint 6 holds structurally), and exactly two triggers,
slash commands and mentions.
"""

from __future__ import annotations

import discord
import pytest

from agentspace.channels.discord_adapter import INTENTS

pytestmark = pytest.mark.anyio


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
    interaction when the command was typed: because the command did not exist
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


# --- the mention trigger ------------------------------------------------------


def _adapter_with_bot_user(bot_id: int) -> tuple[object, list[object]]:
    """A `DiscordAdapter` whose client believes it is `bot_id`, with `_converse`
    replaced by a recorder. Nothing connects: the client is constructed, never
    started, and the one attribute the handler reads off it is stubbed."""
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from agentspace.channels.discord_adapter import DiscordAdapter

    adapter = DiscordAdapter(MagicMock(), token="")  # never started, so never sent
    started: list[object] = []

    async def record(inbound: object, _reply: object) -> None:
        started.append(inbound)

    adapter._converse = record  # type: ignore[method-assign, assignment]
    adapter._client = SimpleNamespace(user=SimpleNamespace(id=bot_id))  # type: ignore[assignment]
    return adapter, started


def _message(text: str, *, mentions: list[object], author_is_bot: bool = False) -> object:
    """Enough of a `discord.Message` for `_on_mention`, with `reply` recorded."""
    from datetime import UTC, datetime
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    return SimpleNamespace(
        content=text,
        mentions=mentions,
        author=SimpleNamespace(id=4242, bot=author_is_bot, display_name="Zocke"),
        channel=SimpleNamespace(id=777),
        created_at=datetime(2026, 9, 12, 12, 0, tzinfo=UTC),
        reply=AsyncMock(return_value=SimpleNamespace(edit=AsyncMock())),
    )


async def test_a_mention_with_a_goal_starts_a_conversation_with_the_goal_alone() -> None:
    """The second of the two triggers, which the live runs never used: both
    typed the slash command. The goal handed on is the message with the
    mention stripped, and the message's own author, channel and time."""
    from datetime import datetime

    adapter, started = _adapter_with_bot_user(99)
    bot = adapter._client.user  # type: ignore[attr-defined]
    message = _message("<@99> summarise q3.md", mentions=[bot])

    await adapter._on_mention(message)  # type: ignore[attr-defined]

    (inbound,) = started
    assert inbound.channel == "discord"  # type: ignore[attr-defined]
    assert inbound.trigger == "mention"  # type: ignore[attr-defined]
    assert inbound.text == "summarise q3.md"  # type: ignore[attr-defined]
    assert inbound.external_user_id == "4242"  # type: ignore[attr-defined]
    assert inbound.thread_ref == "777"  # type: ignore[attr-defined]
    assert inbound.display_name == "Zocke"  # type: ignore[attr-defined]
    assert isinstance(inbound.ts, datetime)  # type: ignore[attr-defined]
    message.reply.assert_awaited_once_with("Starting…")  # type: ignore[attr-defined]


async def test_the_nickname_form_of_a_mention_is_stripped_too() -> None:
    adapter, started = _adapter_with_bot_user(99)
    bot = adapter._client.user  # type: ignore[attr-defined]

    await adapter._on_mention(_message("<@!99>   write hello.txt", mentions=[bot]))  # type: ignore[attr-defined]

    assert started[0].text == "write hello.txt"  # type: ignore[attr-defined]


async def test_a_message_that_does_not_mention_the_bot_starts_nothing() -> None:
    """§1 constraint 6, at the code level: the gateway already withholds the
    text of such messages, and if one arrived anyway it would still be
    ignored. Neither a run nor a reply."""
    adapter, started = _adapter_with_bot_user(99)
    from types import SimpleNamespace

    message = _message("<@123> hello", mentions=[SimpleNamespace(id=123)])

    await adapter._on_mention(message)  # type: ignore[attr-defined]

    assert started == []
    message.reply.assert_not_awaited()  # type: ignore[attr-defined]


async def test_a_bot_mentioning_the_bot_is_ignored() -> None:
    """Two instances of this application must not talk each other into a loop."""
    adapter, started = _adapter_with_bot_user(99)
    bot = adapter._client.user  # type: ignore[attr-defined]
    message = _message("<@99> do it", mentions=[bot], author_is_bot=True)

    await adapter._on_mention(message)  # type: ignore[attr-defined]

    assert started == []
    message.reply.assert_not_awaited()  # type: ignore[attr-defined]


async def test_a_bare_mention_gets_usage_and_starts_nothing() -> None:
    adapter, started = _adapter_with_bot_user(99)
    bot = adapter._client.user  # type: ignore[attr-defined]
    message = _message("<@99>", mentions=[bot])

    await adapter._on_mention(message)  # type: ignore[attr-defined]

    assert started == []
    message.reply.assert_awaited_once()  # type: ignore[attr-defined]
    assert "Tell me what to do" in message.reply.await_args.args[0]  # type: ignore[attr-defined]
