"""Discord, over `discord.py`.

Slash commands and @mentions only, and no `MessageContent` intent (§5 Phase
8): :data:`INTENTS` is `guilds` and nothing else, so the gateway does not
deliver the text of messages this bot was not addressed in, and §1 constraint
6 holds because the data never arrives. The interaction is deferred before any
slow work, since Discord closes one not acknowledged within three seconds. The
mention path takes the text after the mention and nothing else.
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

#: `guilds` only: enough to know which servers to sync commands into.
INTENTS: Final[discord.Intents] = discord.Intents.none()
INTENTS.guilds = True

#: How long an Allow/Deny button stays live; the approval itself is bounded by
#: the run's own deadline.
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

        `start`, not `run`: `run` would own the event loop.
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
            # Otherwise a guild joined after startup has no commands until a restart.
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

        Global commands are cached by Discord for up to an hour, which here
        means a bot that connects, reports healthy and answers nothing all
        afternoon. Guild-scoped commands appear immediately, and a bot that
        lives in one or two servers is exactly what they are for. The guild
        count is logged because "in no servers" and "synced" are otherwise
        indistinguishable from outside.
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
        """The @mention trigger. Bots are ignored so two instances cannot loop each other."""
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

        Not awaited inline: `discord.py` dispatches events on this task, and a
        run blocked here could not receive its own approval button.
        """
        self._deps.launcher.spawn(self._guarded(inbound, reply))

    async def _guarded(self, inbound: InboundMessage, reply: Any) -> None:
        try:
            await converse(self._deps, inbound, reply, on_refusal=self._on_refusal)
        except asyncio.CancelledError:
            raise
        except Exception:
            # One conversation failing must not take the shared gateway down.
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

    ``owner_id`` is passed in rather than read off the placeholder, whose
    author is this bot; deriving it there would let anyone approve anyone's call.
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

    Not a privileged path (§1 constraint 5): the buttons call the same
    :meth:`~agentspace.tools.approval.ApprovalService.resolve` as
    `POST /approvals/{id}`, 409 included. Only the person who started the run
    may press them, checked on the user id Discord asserts, because the
    buttons render for everyone who can see the message.
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
            # Answered from the dashboard first, or expired by the run's deadline.
            await interaction.response.edit_message(
                content="Already answered elsewhere.", view=None
            )
            return

        await interaction.response.edit_message(
            content=("Allowed." if approved else "Denied."), view=None
        )
        self.stop()
