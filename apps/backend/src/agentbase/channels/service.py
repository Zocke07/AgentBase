"""Everything a channel does that is not platform-specific.

:func:`converse` is one chat conversation from the command arriving to the run
ending: identity, refusal, starting the run, folding the log, throttling the
edits, surfacing the approval gate. :class:`ChannelService` owns the adapters:
starts the enabled ones, restarts them when they fall over, stops them on
shutdown.

Chat platforms differ in exactly one thing that matters, how you edit a message
you already sent, so that is all an adapter implements
(:class:`~agentbase.channels.base.ChannelReply`); the rest is shared here so a
bug fixed once is fixed for every channel.

Adapters run in-process, supervised, rather than in their own OS process (a
recorded deviation from §5 Phase 8): :meth:`ChannelService._supervise` gives
the crash isolation a process would, without a second frozen binary and a
second shutdown handshake. Nothing here touches a tool, a sandbox or an
approval on an agent's behalf; a chat-originated run is the same `Run` in the
same process, and a chat answer to an approval goes through the same
:meth:`~agentbase.tools.approval.ApprovalService.resolve` the dashboard uses
(§1 constraint 5).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable  # runtime: see `AdapterFactory` below
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final

from agentbase.api.stream import run_events
from agentbase.channels.base import CHANNEL_NAMES, ChannelName, InboundMessage
from agentbase.channels.identity import IdentityDirectory, refusal_text
from agentbase.channels.render import DISCORD_MESSAGE_LIMIT, fold, render
from agentbase.channels.throttle import DISCORD_EDIT_INTERVAL, Throttle
from agentbase.events.types import TERMINAL_RUN_EVENTS, EventType

if TYPE_CHECKING:
    from collections.abc import Mapping

    from agentbase.channels.base import ChannelAdapter, ChannelReply
    from agentbase.events.bus import EventBus
    from agentbase.events.store import EventStore
    from agentbase.events.types import Event
    from agentbase.orchestrator.launcher import RunLauncher
    from agentbase.secrets import SecretStore
    from agentbase.store.settings import SettingsStore
    from agentbase.tools.approval import ApprovalService

__all__ = [
    "ChannelDeps",
    "ChannelService",
    "ChannelStatus",
    "converse",
]

logger = logging.getLogger("agentbase.channels")

#: Per-channel message ceiling and edit cadence: the two numbers `converse` needs.
_LIMITS: Final[dict[str, tuple[int, float]]] = {
    "discord": (DISCORD_MESSAGE_LIMIT, DISCORD_EDIT_INTERVAL),
}

#: The keychain names the shell delivers over stdin (§1 constraint 4). A bot
#: token is a credential in exactly the sense an API key is.
_TOKEN_SECRET: Final[dict[str, str]] = {
    "discord": "discord_bot_token",
}

#: Consecutive immediate failures before an adapter is left stopped. A dropped
#: gateway connection is retried forever; a bad token fails instantly every
#: time, and retrying that until shutdown hides a fixable mistake.
_MAX_CONSECUTIVE_FAILURES: Final[int] = 5

_BACKOFF_SECONDS: Final[tuple[float, ...]] = (1.0, 2.0, 5.0, 15.0, 30.0)

#: Events whose render is never throttled.
_FORCE_RENDER_ON: Final[frozenset[EventType]] = frozenset(
    {EventType.APPROVAL_REQUESTED, EventType.APPROVAL_RESOLVED, *TERMINAL_RUN_EVENTS}
)


@dataclass(frozen=True, slots=True)
class ChannelDeps:
    """What a channel needs from the rest of the application.

    Every object here is one the HTTP API already uses, so a channel cannot
    reach anything a dashboard user could not.
    """

    store: EventStore
    bus: EventBus
    settings: SettingsStore
    approvals: ApprovalService
    launcher: RunLauncher


@dataclass(slots=True)
class ChannelStatus:
    """What `GET /channels` reports about one adapter."""

    channel: ChannelName
    enabled: bool
    configured: bool
    running: bool = False
    failures: int = 0
    last_error: str | None = None
    #: Recent refused senders, newest first. Bounded, and not in the event log.
    refused: list[str] = field(default_factory=list)


# --- one conversation --------------------------------------------------------


async def converse(
    deps: ChannelDeps,
    inbound: InboundMessage,
    reply: ChannelReply,
    *,
    on_refusal: Callable[[str], None] | None = None,
) -> str | None:
    """Handle one command: authorize it, run it, and report it as it goes.

    Returns the run id, or ``None`` if the sender was refused.

    A refusal is not written to the event log. `events.run_id` is NOT NULL, so
    it would need a run row that never ran, in the user's run list, creatable
    without bound by any stranger who can see the bot. It goes to
    ``on_refusal``, which `GET /channels` renders from a bounded list.
    """
    settings = await deps.settings.get()
    directory = IdentityDirectory(settings.channel_identities)
    identity = directory.resolve(inbound.channel, inbound.external_user_id)

    if identity is None:
        who = f"{inbound.display_name or '?'} ({inbound.external_user_id})"
        logger.warning("refused a %s command from %s", inbound.channel, who)
        if on_refusal is not None:
            on_refusal(who)
        await reply.update(refusal_text(inbound.channel))
        return None

    goal = inbound.text.strip()

    async def prologue(run: Any) -> None:
        # First event of the run: the message did arrive before the run started.
        await deps.store.append(run.id, EventType.CHANNEL_INBOUND, inbound.as_payload(identity))

    # A stored space id that no longer exists falls back to the default rather
    # than turning every command into an error nobody in the channel can fix.
    space_id = settings.channel_space_id
    if space_id is not None and await deps.launcher.space_exists(space_id) is False:
        logger.warning("channel_space_id %r is not a space; using the default", space_id)
        space_id = None

    run = await deps.launcher.launch(
        goal,
        space_id=space_id,
        origin=inbound.channel,
        origin_ref=inbound.thread_ref,
        prologue=prologue,
    )

    await _report(deps, run.id, inbound, reply, ask=settings.channel_approvals == "originator")
    return run.id


async def _report(
    deps: ChannelDeps,
    run_id: str,
    inbound: InboundMessage,
    reply: ChannelReply,
    *,
    ask: bool,
) -> None:
    """Keep the chat message current until the run ends.

    The message is re-rendered from the whole log on every edit, never
    appended to, so a reconnect or a resend shows what the log says rather
    than what this process happened to witness.
    """
    limit, interval = _LIMITS.get(inbound.channel, (DISCORD_MESSAGE_LIMIT, 2.0))
    throttle = Throttle(interval)

    queue: asyncio.Queue[Event | None] = asyncio.Queue()
    pump = asyncio.create_task(_pump(deps, run_id, queue))

    seen: list[Event] = []
    delivered = False
    asked: set[str] = set()

    try:
        while True:
            batch, ended = await _drain(queue)
            seen.extend(batch)

            forced = ended or any(event.type in _FORCE_RENDER_ON for event in batch)
            if batch and throttle.due(force=forced):
                await reply.update(render(fold(seen), limit=limit))
                if not delivered:
                    # On the first delivery, not the last: see `_record_outbound`.
                    delivered = True
                    await _record_outbound(deps, run_id, inbound, "report")

            if ask:
                await _offer_approvals(deps, run_id, inbound, reply, seen, asked)

            if ended:
                return

            # Events arriving during the wait are drained as one batch, so a
            # talkative run costs one edit per interval, not one per event.
            await asyncio.sleep(throttle.seconds_until_due())
    finally:
        pump.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await pump
        await reply.close()


async def _pump(deps: ChannelDeps, run_id: str, queue: asyncio.Queue[Event | None]) -> None:
    """Feed the run's events into ``queue``, then a ``None`` to say it ended.

    Consumes :func:`~agentbase.api.stream.run_events`, the same gap-free
    cursor the dashboard's SSE endpoint uses, so chat and browser cannot
    disagree about which events happened.
    """
    async for event in run_events(deps.store, deps.bus, run_id):
        if event is not None:
            await queue.put(event)
    await queue.put(None)


async def _drain(queue: asyncio.Queue[Event | None]) -> tuple[list[Event], bool]:
    """Block for one item, then take everything else already waiting."""
    batch: list[Event] = []
    ended = False

    first = await queue.get()
    if first is None:
        return batch, True
    batch.append(first)

    while True:
        try:
            item = queue.get_nowait()
        except asyncio.QueueEmpty:
            return batch, ended
        if item is None:
            return batch, True
        batch.append(item)


async def _offer_approvals(
    deps: ChannelDeps,
    run_id: str,
    inbound: InboundMessage,
    reply: ChannelReply,
    seen: list[Event],
    asked: set[str],
) -> None:
    """Offer an Allow/Deny affordance for anything still outstanding.

    Derived from the fold, not from the event that just arrived, so a question
    raised while the adapter was reconnecting is still offered.
    """
    for pending in fold(seen).approvals:
        if pending.approval_id in asked:
            continue
        asked.add(pending.approval_id)
        await reply.ask(pending.approval_id, pending.prompt, pending.risk)
        await _record_outbound(deps, run_id, inbound, "approval")


async def _record_outbound(
    deps: ChannelDeps, run_id: str, inbound: InboundMessage, kind: str
) -> None:
    """Record that something was sent to the conversation.

    ``kind`` is ``"report"`` for the run's own message and ``"approval"`` for a
    question pushed to the chat.

    Written while the run is alive, never as a tally after it ends: the SSE
    stream closes on a terminal event, so an append after `run.completed`
    reaches no live watcher while a replay finds it, and live and replay
    disagree by one event. That was measured on a real run (38 in the table,
    37 delivered) before the placement moved.
    """
    with contextlib.suppress(Exception):
        await deps.store.append(
            run_id,
            EventType.CHANNEL_OUTBOUND,
            {
                "channel": inbound.channel,
                "thread_ref": inbound.thread_ref,
                "kind": kind,
                "ts": datetime.now(UTC).isoformat(),
            },
        )


# --- the adapters, supervised ------------------------------------------------

#: ``(deps, token, on_refusal) -> adapter``. The refusal sink is a constructor
#: argument so a test can build an adapter without a :class:`ChannelService`.
#:
#: `Callable` is a runtime import: `from __future__ import annotations`
#: postpones annotations and does nothing for this assignment, so a
#: TYPE_CHECKING-only import typechecks and raises `NameError` on import.
AdapterFactory = Callable[["ChannelDeps", str, Callable[[str], None]], "ChannelAdapter"]


class ChannelService:
    """Starts, supervises and stops the enabled channel adapters."""

    def __init__(
        self,
        deps: ChannelDeps,
        secrets: SecretStore,
        factories: Mapping[ChannelName, AdapterFactory] | None = None,
    ) -> None:
        self._deps = deps
        self._secrets = secrets
        self._factories = dict(factories) if factories is not None else _default_factories()
        self._tasks: dict[ChannelName, asyncio.Task[None]] = {}
        self._adapters: dict[ChannelName, ChannelAdapter] = {}
        self._status: dict[ChannelName, ChannelStatus] = {}

    async def start(self) -> None:
        """Start every channel that is both enabled and has a token."""
        await self.reconcile()

    async def reconcile(self) -> None:
        """Make the running adapters match the settings, in both directions.

        Called at startup and whenever `PATCH /settings` touches a channel
        field. Without the second call `discord_enabled` reports success and
        changes nothing until a restart, and this product has no restart button.
        """
        settings = await self._deps.settings.get()
        enabled: dict[str, bool] = {
            "discord": settings.discord_enabled,
        }

        for channel in CHANNEL_NAMES:
            token = self._secrets.get(_TOKEN_SECRET[channel])
            # Preserved across a reconcile: `refused` is the only trace of a
            # refusal, since one writes no event.
            status = self._status.setdefault(
                channel, ChannelStatus(channel=channel, enabled=False, configured=False)
            )
            status.enabled = enabled[channel]
            status.configured = token is not None

            running = self._is_running(channel)
            # `token is not None` stays inline so mypy's narrowing reaches the branch.
            should_run = status.enabled and token is not None and channel in self._factories

            if should_run and not running and token is not None:
                status.failures = 0
                status.last_error = None
                self._tasks[channel] = asyncio.create_task(
                    self._supervise(channel, token), name=f"channel-{channel}"
                )
                logger.info("%s channel starting", channel)
            elif not should_run and running:
                await self._stop(channel)
                logger.info("%s channel stopped", channel)
            elif status.enabled and token is None:
                status.last_error = (
                    f"No {_TOKEN_SECRET[channel]} was delivered from the OS keychain, "
                    f"so this channel cannot connect."
                )
                logger.warning("%s is enabled but has no token", channel)
            elif status.enabled and channel not in self._factories:
                status.last_error = f"No adapter is registered for {channel}."

    def _is_running(self, channel: ChannelName) -> bool:
        task = self._tasks.get(channel)
        return task is not None and not task.done()

    async def _stop(self, channel: ChannelName) -> None:
        """Cancel one adapter's supervisor and release its connection."""
        task = self._tasks.pop(channel, None)
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task

        adapter = self._adapters.pop(channel, None)
        if adapter is not None:
            with contextlib.suppress(Exception):
                await adapter.close()

        status = self._status.get(channel)
        if status is not None:
            status.running = False

    async def aclose(self) -> None:
        """Stop every adapter. Safe to call when none were started."""
        for task in self._tasks.values():
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        self._tasks.clear()

        for adapter in self._adapters.values():
            with contextlib.suppress(Exception):
                await adapter.close()
        self._adapters.clear()

        for status in self._status.values():
            status.running = False

    def status(self) -> list[ChannelStatus]:
        return [self._status[channel] for channel in CHANNEL_NAMES if channel in self._status]

    def note_refusal(self, channel: ChannelName, who: str) -> None:
        """Record a refused sender for `GET /channels`.

        Bounded: the people in it are unauthenticated by definition, and an
        unbounded list they can append to is a memory leak.
        """
        status = self._status.get(channel)
        if status is None:
            return
        if who not in status.refused:
            status.refused.insert(0, who)
            del status.refused[8:]

    async def _supervise(self, channel: ChannelName, token: str) -> None:
        """Run one adapter, restarting it when it falls over.

        An adapter that raises takes down its own task and nothing else; the
        sidecar keeps serving the dashboard either way.
        """
        status = self._status[channel]
        failures = 0

        def note(who: str) -> None:
            self.note_refusal(channel, who)

        while True:
            adapter = self._factories[channel](self._deps, token, note)
            self._adapters[channel] = adapter
            try:
                status.running = True
                await adapter.run()
            except asyncio.CancelledError:
                status.running = False
                with contextlib.suppress(Exception):
                    await adapter.close()
                raise
            except Exception as exc:
                failures += 1
                status.running = False
                status.failures = failures
                status.last_error = f"{type(exc).__name__}: {exc}"
                logger.warning("%s adapter failed (%d): %s", channel, failures, exc)
                with contextlib.suppress(Exception):
                    await adapter.close()
            else:
                # A clean return means the adapter was asked to stop.
                status.running = False
                return

            if failures >= _MAX_CONSECUTIVE_FAILURES:
                logger.error(
                    "%s adapter failed %d times in a row; leaving it stopped. Last error: %s",
                    channel,
                    failures,
                    status.last_error,
                )
                return

            await asyncio.sleep(_BACKOFF_SECONDS[min(failures - 1, len(_BACKOFF_SECONDS) - 1)])


def _default_factories() -> dict[ChannelName, AdapterFactory]:
    """Build the real adapters, importing their libraries only if asked.

    A late import, so a build in which `discord.py` failed to freeze degrades
    to the channel being unavailable (with the reason in `GET /channels`)
    instead of a sidecar that will not start.
    """

    def discord_factory(
        deps: ChannelDeps, token: str, on_refusal: Callable[[str], None]
    ) -> ChannelAdapter:
        from agentbase.channels.discord_adapter import DiscordAdapter

        return DiscordAdapter(deps, token, on_refusal)

    return {"discord": discord_factory}
