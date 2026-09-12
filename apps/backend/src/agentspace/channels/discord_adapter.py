"""Discord, over `discord.py`.

§5 Phase 8 in full: "Slash commands and @mentions only. Do **not** request the
`MessageContent` privileged intent: the non-privileged baseline is sufficient
and keeps the review requirement and the attack surface off the table. Defer the
interaction immediately (3s ack limit) and edit the deferred reply as events
stream. Throttle outbound through the adapter."

Each of those is load-bearing, so each is implemented literally.

**No `MessageContent` intent.** :data:`INTENTS` is `discord.Intents.none()` plus
`guilds`, and nothing else. That is not merely declining a checkbox: without
that intent Discord sends this bot the text of a message *only* when the bot is
mentioned in it, which makes §1 constraint 6: "never ingest ambient channel
messages into agent context", a property of what the gateway will send rather
than a rule this code has to keep. The strongest version of a rule about not
reading something is not being given it.

**Defer within three seconds.** Discord closes an interaction that is not
acknowledged in three seconds, and starting a run means reading settings,
resolving an identity and writing to SQLite before the orchestrator is even
spawned. :meth:`_on_agent` defers first and does everything else afterwards, so
a slow disk cannot turn a working run into "the application did not respond".

**The mention path takes the text after the mention, and nothing else.** A
mention arrives as an ordinary message with the bot's id in it. Everything
before and including the mention is stripped, and if what remains is empty the
bot asks for a goal rather than guessing one. There is no branch in which the
surrounding conversation becomes agent context.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import TYPE_CHECKING, Any, Final

import discord
from discord import app_commands

from agentspace.channels.base import ChannelName, InboundMessage
from agentspace.channels.render import DISCORD_MESSAGE_LIMIT
from agentspace.channels.service import converse
from agentspace.tools.approval import ApprovalNotPendingError

if TYPE_CHECKING:
    from collections.abc import Callable

    from agentspace.channels.service import ChannelDeps

__all__ = ["INTENTS", "DiscordAdapter"]

logger = logging.getLogger("agentspace.channels.discord")

#: The non-privileged baseline, and deliberately nothing more. `guilds` is what
#: lets the client know which servers it is in so slash commands can sync;
#: `message_content` is absent, so the gateway simply does not deliver the text
#: of messages this bot was not addressed in.
INTENTS: Final[discord.Intents] = discord.Intents.none()
INTENTS.guilds = True

#: How long an Allow/Deny button stays live. The approval itself is bounded by
#: the run's own wall-clock budget (Phase 6's borrowed deadline), so this is
#: only about not leaving dead buttons in a channel forever.
_BUTTON_TIMEOUT_SECONDS: Final[float] = 900.0

_MENTION = re.compile(r"<@!?(\d+)>")


class DiscordAdapter:
    """One Discord gateway connection, and the two triggers it answers."""

    name: ChannelName = "discord"

    def __init__(
        self, deps: ChannelDeps, token: str, on_refusal: Callable[[str], None] | None = None
    ) -> None:
        self._deps = deps
        self._token = token
        self._on_refusal = on_refusal
        self._client = discord.Client(intents=INTENTS)
        self._tree = app_commands.CommandTree(self._client)
        self._register()

    # --- lifecycle -----------------------------------------------------------

    async def run(self) -> None:
        """Connect and serve until cancelled.

        `start` rather than `run`: `discord.Client.run` creates and owns an
        event loop, which would be wrong inside a sidecar that already has one.
        This is the whole of the "needs its own process" argument, and it is
        answered by one method name.
        """
        await self._client.start(self._token)

    async def close(self) -> None:
        if not self._client.is_closed():
            await self._client.close()

    # --- triggers ------------------------------------------------------------

    def _register(self) -> None:
        @self._client.event
        async def on_ready() -> None:
            await self._sync_commands()

        @self._client.event
        async def on_guild_join(guild: discord.Guild) -> None:
            # A guild joined after startup would otherwise have no commands
            # until the next restart.
            await self._sync_one(guild)

        @self._tree.command(name="agent", description="Give the agent workspace a task.")
        @app_commands.describe(goal="What you want the agents to do.")
        async def agent(interaction: discord.Interaction, goal: str) -> None:
            await self._on_agent(interaction, goal)

        @self._client.event
        async def on_message(message: discord.Message) -> None:
            await self._on_mention(message)

    async def _sync_commands(self) -> None:
        """Register `/agent` in every guild this bot is in, not globally.

        **Global commands are cached by Discord for up to an hour.** `sync()`
        with no guild is what the documentation and most examples show, and for
        this product it means a bot that connects, reports itself healthy, and
        does nothing at all for the rest of the afternoon, which is exactly
        what happened the first time this was run against a real server: the
        gateway connected, `GET /channels` said `running: true`, and typing the
        command produced no interaction, no event and no log line, because the
        command did not yet exist in the client.

        Guild-scoped commands appear immediately. This is a local-first
        personal application whose bot lives in one or two servers, so syncing
        per guild is not a development shortcut here: it is the correct
        registration for the deployment. The global path is what a public bot
        with thousands of installs needs, and this is not that.

        The guild count is logged because "connected but in no servers" and
        "connected and synced" are otherwise indistinguishable from outside,
        and the fix for each is completely different.
        """
        guilds = list(self._client.guilds)
        logger.info("discord connected as %s, in %d guild(s)", self._client.user, len(guilds))

        if not guilds:
            logger.warning(
                "this bot is in no servers, so no command can be registered. "
                "Invite it with the bot and applications.commands scopes."
            )
            return

        for guild in guilds:
            await self._sync_one(guild)

    async def _sync_one(self, guild: discord.Guild) -> None:
        self._tree.copy_global_to(guild=guild)
        synced = await self._tree.sync(guild=guild)
        logger.info(
            "synced %d command(s) to %s: %s",
            len(synced),
            guild.name,
            ", ".join(command.name for command in synced),
        )

    async def _on_agent(self, interaction: discord.Interaction, goal: str) -> None:
        """The slash command. Defers first, then does the slow work."""
        await interaction.response.defer(thinking=True)

        inbound = InboundMessage(
            channel="discord",
            external_user_id=str(interaction.user.id),
            text=goal,
            thread_ref=str(interaction.channel_id),
            ts=interaction.created_at,
            trigger="command",
            display_name=interaction.user.display_name,
        )
        await self._converse(inbound, _InteractionReply(self._deps, interaction))

    async def _on_mention(self, message: discord.Message) -> None:
        """The @mention trigger.

        Without `MessageContent`, `message.content` is empty unless this bot was
        mentioned, so the guard below is belt and braces over a gateway that is
        already not sending us anything else. Bots are ignored so two instances
        of this application cannot talk each other into a loop.
        """
        user = self._client.user
        if user is None or message.author.bot or user not in message.mentions:
            return

        goal = _MENTION.sub("", message.content).strip()
        if not goal:
            await message.reply("Tell me what to do, for example: @agent summarise q3.md")
            return

        inbound = InboundMessage(
            channel="discord",
            external_user_id=str(message.author.id),
            text=goal,
            thread_ref=str(message.channel.id),
            ts=message.created_at,
            trigger="mention",
            display_name=message.author.display_name,
        )
        placeholder = await message.reply("Starting…")
        await self._converse(inbound, _MessageReply(self._deps, placeholder, message.author.id))

    async def _converse(self, inbound: InboundMessage, reply: Any) -> None:
        """Hand one conversation to the shared driver, in the background.

        Not awaited inline: a run takes minutes and `discord.py` dispatches
        events on the same task that called us, so blocking here would stop the
        client answering anything else, including the very approval button this
        run is about to be waiting on.
        """
        self._deps.launcher.spawn(self._guarded(inbound, reply))

    async def _guarded(self, inbound: InboundMessage, reply: Any) -> None:
        try:
            await converse(self._deps, inbound, reply, on_refusal=self._on_refusal)
        except asyncio.CancelledError:
            raise
        except Exception:
            # One conversation failing must not take the gateway down with it -
            # the client is shared by every other conversation and by the
            # approval buttons a run in flight is waiting on.
            logger.exception("discord conversation failed")


# --- the two reply handles ----------------------------------------------------


class _InteractionReply:
    """Edits the deferred reply of a slash command."""

    def __init__(self, deps: ChannelDeps, interaction: discord.Interaction) -> None:
        self._deps = deps
        self._interaction = interaction

    async def update(self, text: str) -> None:
        await self._interaction.edit_original_response(content=text[:DISCORD_MESSAGE_LIMIT])

    async def ask(self, approval_id: str, prompt: str, risk: str) -> None:
        await _send_approval(
            self._deps,
            approval_id,
            prompt,
            risk,
            self._interaction.user.id,
            self._interaction.followup.send,
        )

    async def close(self) -> None:
        return


class _MessageReply:
    """Edits the placeholder message posted in reply to a mention.

    ``owner_id`` is passed in rather than read back off the placeholder, whose
    author is this bot. Deriving it from the message would have been the
    plausible-looking mistake that lets anyone approve anyone's tool call.
    """

    def __init__(self, deps: ChannelDeps, message: discord.Message, owner_id: int) -> None:
        self._deps = deps
        self._message = message
        self._owner_id = owner_id

    async def update(self, text: str) -> None:
        await self._message.edit(content=text[:DISCORD_MESSAGE_LIMIT])

    async def ask(self, approval_id: str, prompt: str, risk: str) -> None:
        await _send_approval(
            self._deps, approval_id, prompt, risk, self._owner_id, self._message.channel.send
        )

    async def close(self) -> None:
        return


async def _send_approval(
    deps: ChannelDeps,
    approval_id: str,
    prompt: str,
    risk: str,
    owner_id: int,
    send: Any,
) -> None:
    view = _ApprovalView(deps, approval_id, owner_id)
    await send(content=f"Approval needed [{risk}]\n{prompt}", view=view)


class _ApprovalView(discord.ui.View):
    """Allow / Deny buttons for one pending approval.

    **This is not a privileged path** (§1 constraint 5). The buttons call
    :meth:`~agentspace.tools.approval.ApprovalService.resolve` (the identical
    method `POST /approvals/{id}` calls), including its 409 on an already-settled
    row, which is what a second click or a race with the dashboard produces.
    There is no channel-specific approval code inside the gate, because the gate
    never learns a channel exists.

    **Only the person who started the run may press them.** Discord renders
    buttons to everyone who can see the message, so without this check any
    guild member could approve a shell command on the owner's machine. The
    check is on the interaction's user id, which Discord asserts, rather than on
    anything carried in the message.
    """

    def __init__(self, deps: ChannelDeps, approval_id: str, owner_id: int) -> None:
        super().__init__(timeout=_BUTTON_TIMEOUT_SECONDS)
        self._deps = deps
        self._approval_id = approval_id
        self._owner_id = owner_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self._owner_id:
            return True
        await interaction.response.send_message(
            "Only the person who started this run can answer it.", ephemeral=True
        )
        return False

    @discord.ui.button(label="Allow", style=discord.ButtonStyle.success)
    async def allow(
        self, interaction: discord.Interaction, button: discord.ui.Button[Any]
    ) -> None:
        await self._resolve(interaction, approved=True)

    @discord.ui.button(label="Deny", style=discord.ButtonStyle.danger)
    async def deny(
        self, interaction: discord.Interaction, button: discord.ui.Button[Any]
    ) -> None:
        await self._resolve(interaction, approved=False)

    async def _resolve(self, interaction: discord.Interaction, *, approved: bool) -> None:
        try:
            await self._deps.approvals.resolve(self._approval_id, approved=approved)
        except ApprovalNotPendingError:
            # Somebody answered from the dashboard first, or the run's own
            # wall-clock budget expired it. Both are ordinary (this is the
            # same 409 two browser windows produce), and the honest thing is to
            # say so rather than to pretend the click did something.
            await interaction.response.edit_message(
                content="Already answered elsewhere.", view=None
            )
            return

        await interaction.response.edit_message(
            content=("Allowed." if approved else "Denied."), view=None
        )
        self.stop()
