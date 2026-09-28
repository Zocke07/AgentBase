"""Platform-independent chat-channel behavior.

:func:`converse` handles identity, refusal, run launch, log folding, edit
throttling, and approvals for one conversation. :class:`ChannelService`
starts enabled adapters, restarts failures, and stops them at shutdown.

Adapters only edit already-sent messages via
:class:`~agentbase.channels.base.ChannelReply`; shared logic keeps channel
behavior consistent. They run in-process under supervision (a recorded §5
Phase 8 deviation), providing crash isolation without another frozen binary
or shutdown handshake. Channel origin grants no tool, sandbox, or approval
privilege: approval answers use the dashboard's same resolve path (§1 constraint 5).
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

#: Per-channel message ceiling and edit cadence used by ``converse``.
_LIMITS: Final[dict[str, tuple[int, float]]] = {
    "discord": (DISCORD_MESSAGE_LIMIT, DISCORD_EDIT_INTERVAL),
}

#: Keychain names delivered over stdin (§1 constraint 4); bot tokens are
#: credentials like API keys.
_TOKEN_SECRET: Final[dict[str, str]] = {
    "discord": "discord_bot_token",
}

#: Consecutive immediate failures before stopping an adapter. Retry dropped
#: gateways indefinitely, but stop bad tokens that fail immediately each time.
_MAX_CONSECUTIVE_FAILURES: Final[int] = 5

_BACKOFF_SECONDS: Final[tuple[float, ...]] = (1.0, 2.0, 5.0, 15.0, 30.0)

#: Events whose render is never throttled.
_FORCE_RENDER_ON: Final[frozenset[EventType]] = frozenset(
    {EventType.APPROVAL_REQUESTED, EventType.APPROVAL_RESOLVED, *TERMINAL_RUN_EVENTS}
)


@dataclass(frozen=True, slots=True)
class ChannelDeps:
    """Application dependencies for a channel.

    Each is already used by HTTP, so channels reach nothing unavailable to a
    dashboard user.
    """

    store: EventStore
    bus: EventBus
    settings: SettingsStore
    approvals: ApprovalService
    launcher: RunLauncher


@dataclass(slots=True)
class ChannelStatus:
    """One adapter's `GET /channels` status."""

    channel: ChannelName
    enabled: bool
    configured: bool
    running: bool = False
    failures: int = 0
    last_error: str | None = None
    #: Recent refused senders, newest first; bounded and not event-logged.
    refused: list[str] = field(default_factory=list)


# --- one conversation --------------------------------------------------------


async def converse(
    deps: ChannelDeps,
    inbound: InboundMessage,
    reply: ChannelReply,
    *,
    on_refusal: Callable[[str], None] | None = None,
) -> str | None:
    """Authorize, run, and report one command.

    Return its run ID, or ``None`` for a refusal. Do not event-log refusals:
    non-null ``events.run_id`` would require never-run rows in the user's list,
    unboundedly creatable by bot-visible strangers. Pass them to
    ``on_refusal`` for `GET /channels`' bounded list.
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
        # Record message arrival as the run's first event.
        await deps.store.append(run.id, EventType.CHANNEL_INBOUND, inbound.as_payload(identity))

    # Fall back when stored space no longer exists; chat users cannot repair it.
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

    Rerender the full log on each edit so reconnects/resends show durable state.
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
                    # Record first delivery, not last; see ``_record_outbound``.
                    delivered = True
                    await _record_outbound(deps, run_id, inbound, "report")

            if ask:
                await _offer_approvals(deps, run_id, inbound, reply, seen, asked)

            if ended:
                return

            # Batch arrivals during waits so chatty runs cost one edit per interval.
            await asyncio.sleep(throttle.seconds_until_due())
    finally:
        pump.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await pump
        await reply.close()


async def _pump(deps: ChannelDeps, run_id: str, queue: asyncio.Queue[Event | None]) -> None:
    """Feed run events to ``queue``, then ``None`` at end.

    Use the dashboard SSE endpoint's gap-free cursor so chat and browser agree.
    """
    async for event in run_events(deps.store, deps.bus, run_id):
        if event is not None:
            await queue.put(event)
    await queue.put(None)


async def _drain(queue: asyncio.Queue[Event | None]) -> tuple[list[Event], bool]:
    """Block for one item, then drain already queued items."""
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
    """Offer Allow/Deny controls for outstanding approvals.

    Derive from the fold, not arrivals, so reconnect-time questions still appear.
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
    """Record outbound conversation traffic.

    ``kind`` is ``"report"`` for the run message or ``"approval"`` for a chat
    question. Append while the run lives: SSE closes at a terminal event, so a
    later append reaches replay but not live watchers, causing a one-event split.
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

#: ``(deps, token, on_refusal) -> adapter``. Constructor injection lets tests
#: build adapters without :class:`ChannelService`. ``Callable`` must import at
#: runtime: postponed annotations do not apply to this assignment.
AdapterFactory = Callable[["ChannelDeps", str, Callable[[str], None]], "ChannelAdapter"]


class ChannelService:
    """Start, supervise, and stop enabled channel adapters."""

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
        """Start channels that are enabled and have a token."""
        await self.reconcile()

    async def reconcile(self) -> None:
        """Make running adapters match settings in both directions.

        Call at startup and after channel-setting PATCHes; otherwise
        ``discord_enabled`` would not take effect until unavailable restart.
        """
        settings = await self._deps.settings.get()
        enabled: dict[str, bool] = {
            "discord": settings.discord_enabled,
        }

        for channel in CHANNEL_NAMES:
            token = self._secrets.get(_TOKEN_SECRET[channel])
            # Preserve refusals: they are not event-logged.
            status = self._status.setdefault(
                channel, ChannelStatus(channel=channel, enabled=False, configured=False)
            )
            status.enabled = enabled[channel]
            status.configured = token is not None

            running = self._is_running(channel)
            # Keep inline so mypy narrows ``token`` in this branch.
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
        """Cancel an adapter supervisor and release its connection."""
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
        """Stop every adapter; safe when none started."""
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

        Bound it: unauthenticated senders could otherwise create a memory leak.
        """
        status = self._status.get(channel)
        if status is None:
            return
        if who not in status.refused:
            status.refused.insert(0, who)
            del status.refused[8:]

    async def _supervise(self, channel: ChannelName, token: str) -> None:
        """Run one adapter and restart failures.

        A failure ends only its task; the sidecar still serves the dashboard.
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
                # Clean return means requested stop.
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
    """Build real adapters, importing libraries only when needed.

    Late import turns a frozen ``discord.py`` failure into reported channel
    unavailability rather than a sidecar startup failure.
    """

    def discord_factory(
        deps: ChannelDeps, token: str, on_refusal: Callable[[str], None]
    ) -> ChannelAdapter:
        from agentbase.channels.discord_adapter import DiscordAdapter

        return DiscordAdapter(deps, token, on_refusal)

    return {"discord": discord_factory}
