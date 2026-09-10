"""Telegram, over `python-telegram-bot`.

§5 Phase 8: "long polling (not webhooks — no inbound port). Leave privacy mode
on. Respect 30 msg/s per chat."

**Long polling is not a preference here, it is §1 constraint 3.** A webhook
requires Telegram's servers to reach this machine, which means a port open to
the internet — the one thing the whole architecture is arranged to avoid. Long
polling is an outbound HTTPS connection this application opens, exactly like a
model API call, so the sidecar stays reachable from nowhere but loopback.

**Privacy mode is left on, and that is the same win as Discord's missing
`MessageContent` intent.** With privacy mode on, Telegram delivers a group
message to this bot only when it is a command addressed to it or an explicit
reply to it. §1 constraint 6 — never ingest ambient channel messages — therefore
holds because the messages never arrive, not because this code declines to read
them. It is the default for a new bot and nothing here turns it off.

**The 30 msg/s per chat figure is not the binding limit.** Editing one message
in one chat is limited far more tightly than that, and the design that keeps
this comfortable is one message per run, re-rendered — see
:mod:`agentspace.channels.throttle`.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Final

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from agentspace.channels.base import ChannelName, InboundMessage
from agentspace.channels.render import TELEGRAM_MESSAGE_LIMIT
from agentspace.channels.service import converse
from agentspace.tools.approval import ApprovalNotPendingError

if TYPE_CHECKING:
    from collections.abc import Callable

    from agentspace.channels.service import ChannelDeps

__all__ = ["TelegramAdapter"]

logger = logging.getLogger("agentspace.channels.telegram")

#: Prefix on the inline keyboard's callback data. Telegram caps callback data at
#: 64 bytes, which a prefix plus a uuid4 fits inside with room to spare.
_APPROVE: Final[str] = "ok:"
_DENY: Final[str] = "no:"

#: How long the poller waits for an update before asking again.
_POLL_TIMEOUT_SECONDS: Final[int] = 20


class TelegramAdapter:
    """One long-polling Telegram connection and the two triggers it answers."""

    name: ChannelName = "telegram"

    def __init__(
        self, deps: ChannelDeps, token: str, on_refusal: Callable[[str], None] | None = None
    ) -> None:
        self._deps = deps
        self._token = token
        self._on_refusal = on_refusal
        self._app: Application[Any, Any, Any, Any, Any, Any] | None = None

    # --- lifecycle -----------------------------------------------------------

    async def run(self) -> None:
        """Poll until cancelled.

        Built with the pieces rather than `run_polling`, which installs signal
        handlers and owns the event loop — both wrong inside a sidecar whose
        shutdown is Phase 1's stdin protocol and whose loop belongs to uvicorn.
        """
        app = ApplicationBuilder().token(self._token).build()
        self._app = app
        self._register(app)

        await app.initialize()
        await app.start()
        if app.updater is None:  # pragma: no cover - only when built without one
            msg = "telegram application was built without an updater"
            raise RuntimeError(msg)
        await app.updater.start_polling(timeout=_POLL_TIMEOUT_SECONDS)
        logger.info("telegram connected")

        try:
            # Serve until cancelled. `start_polling` returns as soon as the
            # poller is running, so without this the supervisor would read a
            # healthy connection as a clean exit and stop restarting it.
            await asyncio.Event().wait()
        finally:
            await self.close()

    async def close(self) -> None:
        app, self._app = self._app, None
        if app is None:
            return
        if app.updater is not None and app.updater.running:
            await app.updater.stop()
        if app.running:
            await app.stop()
        await app.shutdown()

    # --- triggers ------------------------------------------------------------

    def _register(self, app: Application[Any, Any, Any, Any, Any, Any]) -> None:
        app.add_handler(CommandHandler("agent", self._on_command))
        # Privacy mode means a group message reaches this handler only when it
        # is a reply to one of the bot's own messages, which is the Telegram
        # equivalent of an @mention. In a one-to-one chat every message
        # arrives, which is itself an explicit address to the bot.
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._on_mention))
        app.add_handler(CallbackQueryHandler(self._on_button))

    async def _on_command(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.effective_message
        user = update.effective_user
        if message is None or user is None:
            return

        goal = " ".join((message.text or "").split(" ")[1:]).strip()
        if not goal:
            await message.reply_text("Give me a task: /agent summarise q3.md")
            return

        await self._begin(update, goal, "command")

    async def _on_mention(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.effective_message
        if message is None or not (message.text or "").strip():
            return

        chat = update.effective_chat
        addressed = chat is not None and chat.type == "private"
        if not addressed:
            # In a group, only an explicit reply to this bot counts. Privacy
            # mode means nothing else is delivered anyway; this is the second
            # lock on the same door.
            replied = message.reply_to_message
            bot = self._app.bot if self._app is not None else None
            addressed = (
                replied is not None
                and bot is not None
                and replied.from_user is not None
                and replied.from_user.id == bot.id
            )

        if addressed:
            await self._begin(update, (message.text or "").strip(), "mention")

    async def _begin(self, update: Update, goal: str, trigger: str) -> None:
        message = update.effective_message
        user = update.effective_user
        if message is None or user is None:
            return

        inbound = InboundMessage(
            channel="telegram",
            external_user_id=str(user.id),
            text=goal,
            thread_ref=str(message.chat_id),
            ts=message.date,
            trigger="command" if trigger == "command" else "mention",
            display_name=user.full_name,
        )

        placeholder = await message.reply_text("Starting…")
        reply = _TelegramReply(self._deps, placeholder, user.id)

        # Backgrounded for the same reason as Discord's: a run takes minutes and
        # the handler must return so the poller keeps delivering updates —
        # including the button press this run is about to wait on.
        self._deps.launcher.spawn(self._guarded(inbound, reply))

    async def _guarded(self, inbound: InboundMessage, reply: _TelegramReply) -> None:
        try:
            await converse(self._deps, inbound, reply, on_refusal=self._on_refusal)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("telegram conversation failed")

    async def _on_button(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        """Resolve an approval from an inline keyboard press.

        **Not a privileged path** (§1 constraint 5): this calls the same
        :meth:`~agentspace.tools.approval.ApprovalService.resolve` that
        `POST /approvals/{id}` calls, and gets the same conflict when the row is
        already settled. The only channel-specific thing here is who is allowed
        to press the button.
        """
        query = update.callback_query
        if query is None or query.data is None:
            return
        await query.answer()

        approved = query.data.startswith(_APPROVE)
        approval_id = query.data[len(_APPROVE) :]

        owner = _OWNERS.get(approval_id)
        if owner is not None and query.from_user is not None and query.from_user.id != owner:
            await query.answer(
                "Only the person who started this run can answer it.", show_alert=True
            )
            return

        try:
            await self._deps.approvals.resolve(approval_id, approved=approved)
        except ApprovalNotPendingError:
            await _edit(query.edit_message_text, "Already answered elsewhere.")
            return
        finally:
            _OWNERS.pop(approval_id, None)

        await _edit(query.edit_message_text, "Allowed." if approved else "Denied.")


#: Which chat user may answer which approval. In memory only, and bounded by the
#: number of approvals a live process has raised — a restart expires every
#: pending approval anyway (Phase 6), so nothing here needs to survive one.
_OWNERS: dict[str, int] = {}


class _TelegramReply:
    """Edits the one message this run owns."""

    def __init__(self, deps: ChannelDeps, message: Any, owner_id: int) -> None:
        self._deps = deps
        self._message = message
        self._owner_id = owner_id
        self._last = ""

    async def update(self, text: str) -> None:
        clamped = text[:TELEGRAM_MESSAGE_LIMIT]
        if clamped == self._last:
            # Telegram answers an edit that changes nothing with a 400 rather
            # than a no-op, and the throttle can legitimately fire on a batch of
            # events none of which changed the rendering.
            return
        self._last = clamped
        await _edit(self._message.edit_text, clamped)

    async def ask(self, approval_id: str, prompt: str, risk: str) -> None:
        _OWNERS[approval_id] = self._owner_id
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("Allow", callback_data=f"{_APPROVE}{approval_id}"),
                    InlineKeyboardButton("Deny", callback_data=f"{_DENY}{approval_id}"),
                ]
            ]
        )
        await self._message.reply_text(
            f"Approval needed [{risk}]\n{prompt}"[:TELEGRAM_MESSAGE_LIMIT],
            reply_markup=keyboard,
        )

    async def close(self) -> None:
        return


async def _edit(edit: Any, text: str) -> None:
    """Apply an edit, tolerating Telegram's "message is not modified" 400.

    That specific error means the desired state is already on screen, which is
    success spelled as a failure. Letting it propagate would kill a run's
    reporting over a message that was already correct.
    """
    try:
        await edit(text)
    except BadRequest as exc:
        if "not modified" not in str(exc).lower():
            raise
