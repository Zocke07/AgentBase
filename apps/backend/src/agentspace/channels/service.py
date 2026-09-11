"""Everything a channel does that is not platform-specific.

Two things live here. :func:`converse` is one chat conversation from the moment
a command arrives to the moment the run ends — identity, refusal, starting the
run, folding the log, throttling the edits, surfacing the approval gate.
:class:`ChannelService` owns the adapters: it starts the enabled ones, restarts
them when they fall over, and stops them on shutdown.

**Why this is not in the adapters.** Chat platforms differ in exactly one
thing that matters: how you edit a message you already sent. Everything else —
who is allowed to ask, what a refusal says, which object starts the run, what
the reply says at any moment, when it is worth spending an edit — is identical,
and a bug fixed in one copy of it would live on in the other. So the adapters
implement :class:`~agentspace.channels.base.ChannelReply` and call this.

**In-process, supervised, rather than a separate OS process.** §5 Phase 8 says
Discord runs in its "own process", and this is a deliberate deviation recorded
in CLAUDE.md. The benefit of a separate process is crash isolation, which
:meth:`ChannelService._supervise` provides. The costs of a literal reading are
Phase 1's orphan-process trap re-run twice (with ``--onefile``, the PID a parent
holds is the bootloader's, not the server's), a second frozen binary, a second
extraction on every launch, and a duplicated shutdown handshake. `discord.py`
does not need its own event loop — `Client.start()` runs as a task on an
existing one — so the reason usually given for the separate process does not
apply here.

**The gate is reached by the identical path a dashboard run uses.** §1 constraint
5 ends "no privileged paths for any channel", and the way that is made
structural is that nothing in this module touches a tool, a sandbox or an
approval decision on behalf of an agent. A channel-originated run is the same
`Run` object, in the same process, holding the same `ToolRuntime`. When the
policy lets a chat answer an approval, the answer goes through
:meth:`~agentspace.tools.approval.ApprovalService.resolve` — the same method
`POST /approvals/{id}` calls, with the same 409 on a settled row.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable  # runtime: see `AdapterFactory` below
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final

from agentspace.api.stream import run_events
from agentspace.channels.base import CHANNEL_NAMES, ChannelName, InboundMessage
from agentspace.channels.identity import IdentityDirectory, refusal_text
from agentspace.channels.render import DISCORD_MESSAGE_LIMIT, fold, render
from agentspace.channels.throttle import DISCORD_EDIT_INTERVAL, Throttle
from agentspace.events.types import TERMINAL_RUN_EVENTS, EventType

if TYPE_CHECKING:
    from collections.abc import Mapping

    from agentspace.channels.base import ChannelAdapter, ChannelReply
    from agentspace.events.bus import EventBus
    from agentspace.events.store import EventStore
    from agentspace.events.types import Event
    from agentspace.orchestrator.launcher import RunLauncher
    from agentspace.secrets import SecretStore
    from agentspace.store.settings import SettingsStore
    from agentspace.tools.approval import ApprovalService

__all__ = [
    "ChannelDeps",
    "ChannelService",
    "ChannelStatus",
    "converse",
]

logger = logging.getLogger("agentspace.channels")

#: Per-channel message ceiling and edit cadence. Kept together because they are
#: the only two numbers `converse` needs from a platform.
_LIMITS: Final[dict[str, tuple[int, float]]] = {
    "discord": (DISCORD_MESSAGE_LIMIT, DISCORD_EDIT_INTERVAL),
}

#: The keychain names the shell delivers over stdin (§1 constraint 4). A bot
#: token is a credential in exactly the sense an API key is: it authenticates
#: this application to a third party and is replayable by anyone who reads it.
_TOKEN_SECRET: Final[dict[str, str]] = {
    "discord": "discord_bot_token",
}

#: How many consecutive immediate failures before an adapter is left stopped.
#: A dropped gateway connection is ordinary and retried forever; a bad token
#: fails instantly every time, and retrying that until the process ends turns a
#: fixable configuration mistake into a log nobody reads.
_MAX_CONSECUTIVE_FAILURES: Final[int] = 5

_BACKOFF_SECONDS: Final[tuple[float, ...]] = (1.0, 2.0, 5.0, 15.0, 30.0)

#: A run that fails before the adapter ever renders leaves the user with an
#: empty message, so the first render is never throttled.
_FORCE_RENDER_ON: Final[frozenset[EventType]] = frozenset(
    {EventType.APPROVAL_REQUESTED, EventType.APPROVAL_RESOLVED, *TERMINAL_RUN_EVENTS}
)


@dataclass(frozen=True, slots=True)
class ChannelDeps:
    """What a channel needs from the rest of the application.

    Deliberately small and deliberately not `app.state`: everything here is an
    object the HTTP API already uses, so a channel cannot reach anything a
    dashboard user could not. `launcher` in particular is the same
    :class:`~agentspace.orchestrator.launcher.RunLauncher` `POST /runs` holds.
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
    #: Recent senders this workspace refused, newest first. Bounded, and
    #: deliberately *not* in the event log — see :func:`converse`.
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

    **A refusal is not written to the event log**, which is a decision rather
    than an omission. §4 gives `events.run_id` a NOT NULL foreign key, so a
    `channel.inbound` for a refused message would need a run row to hang off —
    a run that never ran, in the user's run list, creatable in unbounded numbers
    by any stranger who can see the bot. The refusal is reported through
    ``on_refusal`` instead, which `GET /channels` renders from a bounded list.
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
        # First event of the run, before the orchestrator emits anything. The
        # message genuinely did arrive before the run started, and a log that
        # recorded it afterwards would be saying something untrue about order.
        await deps.store.append(run.id, EventType.CHANNEL_INBOUND, inbound.as_payload(identity))

    run = await deps.launcher.launch(
        goal,
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

    The message is re-rendered from the whole log every time rather than
    appended to. That is the Phase 7 reasoning about live versus replay, applied
    to a second projection: a renderer that accumulates and a renderer that
    rebuilds agree until one of them gains a feature, so there is only the
    rebuilding one. It also means a reconnect or a resend shows what the log
    says rather than what this process happened to witness.
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
                    # Written on the *first* delivery, not the last. See
                    # `_record_outbound` for why the obvious placement — a
                    # tally in the `finally` below — is a bug.
                    delivered = True
                    await _record_outbound(deps, run_id, inbound, "report")

            if ask:
                await _offer_approvals(deps, run_id, inbound, reply, seen, asked)

            if ended:
                return

            # Events arriving during this wait accumulate in the queue and are
            # drained as one batch, so a talkative run costs one edit per
            # interval rather than one edit per event. Sleeping here rather
            # than skipping the render is what bounds how stale the message can
            # get to the interval itself.
            await asyncio.sleep(throttle.seconds_until_due())
    finally:
        pump.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await pump
        await reply.close()


async def _pump(deps: ChannelDeps, run_id: str, queue: asyncio.Queue[Event | None]) -> None:
    """Feed the run's events into ``queue``, then a ``None`` to say it ended.

    Consuming :func:`~agentspace.api.stream.run_events` rather than the bus
    directly is the point: that is the same gap-free cursor the dashboard's SSE
    endpoint uses, so a chat reply and a browser watching the same run cannot
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

    Derived from the fold rather than from the event that just arrived, so a
    question raised while the adapter was reconnecting is still offered.
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

    **Both are written while the run is still alive, and that is the whole
    point of this function's shape.** The obvious implementation is a tally
    written once at the end — "this run was reported to Discord, in 9 edits" —
    and it is wrong for a reason that no unit test reading the database would
    ever show: §4's terminal events are defined as the events "after which no
    further event can appear for that run", and the SSE stream closes on them.
    An append after `run.completed` is therefore delivered to nobody watching
    live, while a replay reading the table finds it — so the two disagree, and
    §5 Phase 7's pixel-identical criterion quietly stops holding for every run
    that came from a channel.

    Found by running it: a real `qwen3:4b` run put 38 events in the table and
    handed a simultaneous SSE watcher 37. The test that was supposed to cover
    this asserted on `store.read()`, which is the database, not the stream —
    the same shape as every other bug this project has found, which is a check
    that is correct everywhere except where the product actually consumes it.

    A per-edit row was never on the table for a different reason: a hundred
    rows describing revisions of one message is noise in a log whose value is
    that everything in it happened.
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
#: argument rather than something the adapter reaches for, so a test can build
#: an adapter without a :class:`ChannelService` in front of it.
#:
#: `Callable` is imported at runtime for this line rather than under
#: TYPE_CHECKING. `from __future__ import annotations` postpones *annotations*
#: and does nothing for an assignment, so a TYPE_CHECKING-only import
#: typechecks perfectly and raises `NameError` the moment anything imports this
#: module. mypy was green; ten test modules failed to collect. Same shape as
#: every other bug this project has found — correct everywhere except where it
#: actually runs.
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

        Called at startup and again whenever `PATCH /settings` touches a
        channel field. Without the second call, `discord_enabled` would be a
        setting that reports success and changes nothing until the application
        is restarted — and this product has no restart button, so for a user it
        would simply not work.

        That is the shape this project has now hit seven times: Phase 1's CORS
        origins, Phase 2's named SSE events, Phase 3's `*.sql` glob, Phase 4's
        silently-dropped settings fields, Phase 5's `max_steps` default, Phase
        6's unsettable `auto_approve`, Phase 7's `qualified_model`. Every one
        was a setting or a value that looked configured and was not, and every
        one was found by running the thing rather than by reading it. This one
        was found the same way — by enabling Discord over HTTP and watching
        nothing connect.
        """
        settings = await self._deps.settings.get()
        enabled: dict[str, bool] = {
            "discord": settings.discord_enabled,
        }

        for channel in CHANNEL_NAMES:
            token = self._secrets.get(_TOKEN_SECRET[channel])
            # Preserved across a reconcile rather than rebuilt: `refused` is a
            # record of who this workspace turned away, and losing it because
            # somebody toggled an unrelated setting would throw away the only
            # trace of it (a refusal writes no event — see `converse`).
            status = self._status.setdefault(
                channel, ChannelStatus(channel=channel, enabled=False, configured=False)
            )
            status.enabled = enabled[channel]
            status.configured = token is not None

            running = self._is_running(channel)
            # `token is not None` is written inline rather than folded into a
            # `should_run` boolean so the narrowing survives into the branch;
            # mypy cannot see through the indirection, and silencing it would
            # have thrown away a real check for a cosmetic one.
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
        """Record a refused sender for `GET /channels`, keeping the list bounded.

        Bounded because the people who end up in it are by definition
        unauthenticated, and an unbounded list they can append to is a memory
        leak with a stranger's hand on the tap.
        """
        status = self._status.get(channel)
        if status is None:
            return
        if who not in status.refused:
            status.refused.insert(0, who)
            del status.refused[8:]

    async def _supervise(self, channel: ChannelName, token: str) -> None:
        """Run one adapter, restarting it when it falls over.

        This is the crash isolation that a separate OS process would have
        provided, and it is why the deviation from §5 Phase 8's "own process"
        costs nothing: an adapter that raises takes down its own task and
        nothing else, and the sidecar keeps serving the dashboard either way.
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

    A late import rather than a module-level one so that a build in which
    `discord.py` failed to freeze degrades to the channel being unavailable —
    with the reason in `GET /channels` — instead of a sidecar that will not
    start. That is the shape of the Phase 3 `*.sql` bug inverted: an import
    that is fine everywhere except in the bundle.
    """

    def discord_factory(
        deps: ChannelDeps, token: str, on_refusal: Callable[[str], None]
    ) -> ChannelAdapter:
        from agentspace.channels.discord_adapter import DiscordAdapter

        return DiscordAdapter(deps, token, on_refusal)

    return {"discord": discord_factory}
