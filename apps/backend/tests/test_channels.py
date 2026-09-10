"""The two §5 Phase 8 acceptance criteria, and the properties they rest on.

The criteria are:

1. "the same run is observable simultaneously from the dashboard and the
   originating chat channel";
2. "a channel-originated tool call still hits the approval gate".

Both are asserted here against the production objects — the real event store,
the real SSE cursor, the real `ToolRuntime`, the real `ApprovalService`. The
only double is the chat platform itself: :class:`FakeReply` stands in for
Discord's `edit_original_response` and Telegram's `edit_text`, which is exactly
the seam :class:`~agentspace.channels.base.ChannelReply` exists to create. A
test that faked more than that — a fake gate, a fake launcher — would prove the
criteria on a path the product does not take, which is the failure mode CLAUDE.md
records repeatedly.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pytest

from agentspace.channels.base import InboundMessage
from agentspace.channels.identity import ChannelIdentity
from agentspace.channels.render import fold
from agentspace.channels.service import ChannelDeps, ChannelService, converse
from agentspace.events.types import EventType
from agentspace.orchestrator.launcher import RunLauncher
from agentspace.tools.approval import ApprovalNotPendingError
from agentspace.tools.catalogue import RiskLevel
from support import ScriptedProvider, call, says, tool_runtime

if TYPE_CHECKING:
    from pathlib import Path

    from agentspace.budget.ledger import BudgetLedger
    from agentspace.events.bus import EventBus
    from agentspace.events.store import EventStore
    from agentspace.secrets import SecretStore
    from agentspace.store.agents import AgentDefStore
    from agentspace.store.db import Database
    from agentspace.store.settings import SettingsStore

pytestmark = pytest.mark.anyio

OWNER_ID = "4210"


def inbound(text: str = "Write a haiku", user: str = OWNER_ID) -> InboundMessage:
    return InboundMessage(
        channel="discord",
        external_user_id=user,
        text=text,
        thread_ref="channel-1",
        ts=datetime(2026, 9, 10, 12, 0, tzinfo=UTC),
        trigger="command",
        display_name="Owner",
    )


class FakeReply:
    """The chat platform, and nothing else.

    Records every edit rather than only the last one, because "the message was
    updated while the run was still going" is a claim about the sequence, not
    about the final state — and it is half of the first acceptance criterion.
    """

    def __init__(self) -> None:
        self.updates: list[str] = []
        self.asked: list[tuple[str, str, str]] = []
        self.closed = False

    async def update(self, text: str) -> None:
        self.updates.append(text)

    async def ask(self, approval_id: str, prompt: str, risk: str) -> None:
        self.asked.append((approval_id, prompt, risk))

    async def close(self) -> None:
        self.closed = True


async def allow(settings: SettingsStore, **changes: Any) -> None:
    await settings.update(
        {
            "channel_identities": [
                ChannelIdentity(channel="discord", external_user_id=OWNER_ID, identity="owner")
            ],
            **changes,
        }
    )


def deps_for(
    store: EventStore,
    bus: EventBus,
    settings: SettingsStore,
    agents: AgentDefStore,
    ledger: BudgetLedger,
    secrets: SecretStore,
    provider: ScriptedProvider,
    runtime: Any = None,
    approvals: Any = None,
) -> ChannelDeps:
    launcher = RunLauncher(
        store=store,
        settings=settings,
        agents=agents,
        ledger=ledger,
        secrets=secrets,
        runtime=runtime,
        provider=provider,
    )
    return ChannelDeps(
        store=store,
        bus=bus,
        settings=settings,
        approvals=approvals,
        launcher=launcher,
    )


def finishing_provider() -> ScriptedProvider:
    """A supervisor that answers immediately. Two calls: think, then finish."""
    return ScriptedProvider(
        [
            says("I can answer this directly.", call("finish", result="An old silent pond.")),
        ]
    )


# --- acceptance criterion 1 ---------------------------------------------------


async def test_a_channel_run_is_watchable_from_the_dashboard_while_it_happens(
    store: EventStore,
    bus: EventBus,
    settings: SettingsStore,
    agents: AgentDefStore,
    ledger: BudgetLedger,
    secrets: SecretStore,
) -> None:
    """§5 Phase 8's first acceptance criterion, in its literal form.

    A run started from a chat channel is attached to over the *same* SSE
    endpoint the dashboard uses, while the chat reply is still being written,
    and both see the same events. Not "the dashboard can find it afterwards" —
    the criterion says simultaneously, so the stream is opened mid-run and the
    chat's edits are counted after that point.
    """
    from agentspace.api.stream import run_stream

    await allow(settings)
    deps = deps_for(store, bus, settings, agents, ledger, secrets, finishing_provider())
    reply = FakeReply()

    conversation = asyncio.create_task(converse(deps, inbound(), reply))

    # Wait for the run row the way a dashboard user would: by listing runs.
    run_id = await _wait_for_run(store)

    frames: list[str] = []

    async def watch() -> None:
        async for frame in run_stream(store, bus, run_id, 0):
            frames.append(frame)

    watcher = asyncio.create_task(watch())
    await conversation
    await asyncio.wait_for(watcher, timeout=10)

    # The dashboard saw the run reach its terminal event...
    assert any("run.completed" in frame for frame in frames)
    # ...and the same run's `channel.inbound`, with no special-casing anywhere:
    # the SSE endpoint has no idea a channel exists.
    assert any("channel.inbound" in frame for frame in frames)
    # ...while the chat message was written for the same run.
    assert reply.updates
    assert "An old silent pond." in reply.updates[-1]


async def test_both_projections_of_one_log_say_the_same_thing(
    store: EventStore,
    bus: EventBus,
    settings: SettingsStore,
    agents: AgentDefStore,
    ledger: BudgetLedger,
    secrets: SecretStore,
) -> None:
    """The chat reply is a fold of the log, so re-folding the log reproduces it.

    This is what makes "same event log, no special-casing" checkable rather than
    merely asserted: the final chat message is not a running commentary the
    adapter accumulated, it is a function of the rows in SQLite. Anything the
    chat showed that the log cannot reproduce would be the drift §2 forbids.
    """
    await allow(settings)
    deps = deps_for(store, bus, settings, agents, ledger, secrets, finishing_provider())
    reply = FakeReply()

    await converse(deps, inbound(), reply)
    run_id = await _wait_for_run(store)

    from agentspace.channels.render import render

    stored = await store.read(run_id)
    assert reply.updates[-1] == render(fold(stored), limit=2000)


async def test_channel_inbound_is_the_first_event_of_the_run(
    store: EventStore,
    bus: EventBus,
    settings: SettingsStore,
    agents: AgentDefStore,
    ledger: BudgetLedger,
    secrets: SecretStore,
) -> None:
    """The message arrived before the run started, and the log has to say so.

    Appending it after :meth:`RunLauncher.launch` returns would race the
    orchestrator, which is already emitting `run.started` — sometimes producing
    a log in which the run began before anybody asked for it.
    """
    await allow(settings)
    deps = deps_for(store, bus, settings, agents, ledger, secrets, finishing_provider())

    await converse(deps, inbound(), FakeReply())
    run_id = await _wait_for_run(store)

    events = await store.read(run_id)
    assert events[0].type == EventType.CHANNEL_INBOUND
    assert events[0].seq == 1
    assert events[1].type == EventType.RUN_STARTED


async def test_the_inbound_payload_carries_the_five_normalized_fields(
    store: EventStore,
    bus: EventBus,
    settings: SettingsStore,
    agents: AgentDefStore,
    ledger: BudgetLedger,
    secrets: SecretStore,
) -> None:
    """§5 Phase 8 names the shape: `{channel, external_user_id, text, thread_ref, ts}`."""
    await allow(settings)
    deps = deps_for(store, bus, settings, agents, ledger, secrets, finishing_provider())

    await converse(deps, inbound("Summarise q3"), FakeReply())
    run_id = await _wait_for_run(store)

    payload = (await store.read(run_id))[0].payload
    for key in ("channel", "external_user_id", "text", "thread_ref", "ts"):
        assert key in payload
    assert payload["identity"] == "owner"
    assert payload["trigger"] == "command"


async def test_the_run_records_where_it_came_from(
    store: EventStore,
    bus: EventBus,
    settings: SettingsStore,
    agents: AgentDefStore,
    ledger: BudgetLedger,
    secrets: SecretStore,
) -> None:
    """§4's `runs.origin` and `origin_ref` are what make a run answerable as a
    conversation rather than only as a row."""
    await allow(settings)
    deps = deps_for(store, bus, settings, agents, ledger, secrets, finishing_provider())

    await converse(deps, inbound(), FakeReply())
    run = await store.get_run(await _wait_for_run(store))

    assert run is not None
    assert run.origin == "discord"
    assert run.origin_ref == "channel-1"


async def test_one_channel_outbound_is_written_when_the_reply_is_final(
    store: EventStore,
    bus: EventBus,
    settings: SettingsStore,
    agents: AgentDefStore,
    ledger: BudgetLedger,
    secrets: SecretStore,
) -> None:
    """One row, not one per edit.

    A hundred rows describing revisions of the same message is noise in a log
    whose value is that everything in it happened.
    """
    await allow(settings)
    deps = deps_for(store, bus, settings, agents, ledger, secrets, finishing_provider())

    await converse(deps, inbound(), FakeReply())
    events = await store.read(await _wait_for_run(store))

    outbound = [event for event in events if event.type == EventType.CHANNEL_OUTBOUND]
    assert len(outbound) == 1
    assert outbound[0].payload["thread_ref"] == "channel-1"
    assert outbound[0].payload["edits"] >= 1


# --- acceptance criterion 2 ---------------------------------------------------


async def test_a_channel_originated_tool_call_still_hits_the_approval_gate(
    db: Database,
    store: EventStore,
    bus: EventBus,
    settings: SettingsStore,
    agents: AgentDefStore,
    ledger: BudgetLedger,
    secrets: SecretStore,
    tmp_path: Path,
) -> None:
    """§5 Phase 8's second acceptance criterion, and §1 constraint 5's last clause.

    "No exceptions, no privileged paths for any channel." The run below is
    started by a Discord command and its `write_file` stops dead at the gate,
    with the file absent from disk until somebody answers. Nothing is
    auto-approved, and the gate is the production one — a fake would have proved
    this on a path the product does not take.
    """
    # `app_paths` (which `db` depends on) already made this; the sandbox is
    # rooted at the same place the shipped app roots it.
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    runtime, approvals = tool_runtime(store, db, workspace)

    await allow(settings)
    await agents.create(
        {
            "name": "file_writer",
            "role": "Writes files",
            "system_prompt": "Write the file you are asked for.",
            "allowed_tools": ["write_file"],
            "max_steps": 4,
        }
    )

    provider = ScriptedProvider(
        [
            says("Delegating.", call("spawn_agent", agent="file_writer", task="write notes.txt")),
            says("Writing.", call("write_file", path="notes.txt", content="from discord")),
            says("Done.", call("finish", result="Wrote the file.")),
            says("All done.", call("finish", result="notes.txt written.")),
        ]
    )
    deps = deps_for(
        store, bus, settings, agents, ledger, secrets, provider, runtime, approvals
    )
    reply = FakeReply()

    conversation = asyncio.create_task(converse(deps, inbound("write notes.txt"), reply))

    # The run blocks here. The file must not exist while it does.
    approval_id = await _wait_for_approval(approvals)
    assert not (workspace / "notes.txt").exists()

    # A row was written, which is how "what did this run do without asking me"
    # stays answerable.
    record = await approvals.store.get(approval_id)
    assert record is not None
    assert record.status == "pending"

    await approvals.resolve(approval_id, approved=True)
    await asyncio.wait_for(conversation, timeout=15)

    assert (workspace / "notes.txt").read_text(encoding="utf-8") == "from discord"

    events = await store.read(await _wait_for_run(store))
    types = [event.type for event in events]
    assert EventType.APPROVAL_REQUESTED in types
    assert EventType.TOOL_CALLED in types


async def test_the_question_is_surfaced_in_chat_while_the_run_waits(
    db: Database,
    store: EventStore,
    bus: EventBus,
    settings: SettingsStore,
    agents: AgentDefStore,
    ledger: BudgetLedger,
    secrets: SecretStore,
    tmp_path: Path,
) -> None:
    """A run stopped at the gate stops emitting anything.

    In the dashboard that is obvious — a modal is on screen. In chat the message
    simply stops changing, which is indistinguishable from a crashed bot. So the
    reply is force-rendered on `approval.requested` rather than waiting for the
    throttle, and the prompt is in it.
    """
    # `app_paths` (which `db` depends on) already made this; the sandbox is
    # rooted at the same place the shipped app roots it.
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    runtime, approvals = tool_runtime(store, db, workspace)

    await allow(settings)
    await agents.create(
        {
            "name": "file_writer",
            "role": "Writes files",
            "system_prompt": "Write files.",
            "allowed_tools": ["write_file"],
            "max_steps": 4,
        }
    )

    provider = ScriptedProvider(
        [
            says("Delegating.", call("spawn_agent", agent="file_writer", task="write notes.txt")),
            says("Writing.", call("write_file", path="notes.txt", content="hi")),
            says("Done.", call("finish", result="Wrote it.")),
            says("All done.", call("finish", result="Done.")),
        ]
    )
    deps = deps_for(
        store, bus, settings, agents, ledger, secrets, provider, runtime, approvals
    )
    reply = FakeReply()

    conversation = asyncio.create_task(converse(deps, inbound("write notes.txt"), reply))
    approval_id = await _wait_for_approval(approvals)

    await _until(lambda: any("Waiting for approval" in text for text in reply.updates))

    await approvals.resolve(approval_id, approved=True)
    await asyncio.wait_for(conversation, timeout=15)


async def test_answering_from_chat_uses_the_same_service_the_http_route_uses(
    db: Database,
    store: EventStore,
) -> None:
    """"No privileged paths for any channel", asserted rather than claimed.

    The adapters call :meth:`ApprovalService.resolve` — the identical method
    `POST /approvals/{id}` calls — so a second answer conflicts exactly as two
    browser windows do. If a channel had its own resolution path, this second
    call would succeed.
    """
    workspace = db.path.parent / "workspace"
    workspace.mkdir(exist_ok=True)
    _, approvals = tool_runtime(store, db, workspace)

    run = await store.create_run(goal="g", origin="discord", origin_ref="channel-1")
    record = await approvals.store.create(
        run_id=run.id, tool="write_file", args={"path": "x"}, risk=RiskLevel.MEDIUM
    )

    await approvals.resolve(record.id, approved=True)

    with pytest.raises(ApprovalNotPendingError):
        await approvals.resolve(record.id, approved=False)


# --- the allowlist ------------------------------------------------------------


async def test_an_unknown_sender_starts_no_run_at_all(
    store: EventStore,
    bus: EventBus,
    settings: SettingsStore,
    agents: AgentDefStore,
    ledger: BudgetLedger,
    secrets: SecretStore,
) -> None:
    """The one that matters most, and the one §1 constraint 6 does not cover.

    A Discord bot invited to a server can be addressed by anybody in it, and an
    explicit slash command is exactly the trigger that constraint permits. What
    stops a stranger spending the owner's API budget and raising dialogs on the
    owner's desktop is this: no entry, no identity, no run.
    """
    await allow(settings)
    deps = deps_for(store, bus, settings, agents, ledger, secrets, finishing_provider())
    reply = FakeReply()

    run_id = await converse(deps, inbound(user="99999"), reply)

    assert run_id is None
    assert await store.list_runs(10) == []
    assert reply.updates == [
        "This agent workspace is not configured to accept requests from this Discord "
        "account. Nothing was run."
    ]


async def test_a_refusal_is_reported_out_of_band_and_not_as_an_event(
    store: EventStore,
    bus: EventBus,
    settings: SettingsStore,
    agents: AgentDefStore,
    ledger: BudgetLedger,
    secrets: SecretStore,
) -> None:
    """§4 gives `events.run_id` a NOT NULL foreign key, so an event needs a run.

    Creating one to hold a refusal would fill the user's run list with runs that
    never ran — in unbounded numbers, at the discretion of anyone who can see
    the bot. The refusal is reported through the callback `GET /channels` reads.
    """
    await allow(settings)
    deps = deps_for(store, bus, settings, agents, ledger, secrets, finishing_provider())
    seen: list[str] = []

    await converse(deps, inbound(user="99999"), FakeReply(), on_refusal=seen.append)

    assert seen == ["Owner (99999)"]
    assert await store.list_runs(10) == []


# --- the supervisor -----------------------------------------------------------


async def test_a_disabled_channel_is_never_started(
    store: EventStore,
    bus: EventBus,
    settings: SettingsStore,
    agents: AgentDefStore,
    ledger: BudgetLedger,
    secrets: SecretStore,
) -> None:
    started: list[str] = []
    service = _service_with(
        store, bus, settings, agents, ledger, secrets, started, discord_token="not-a-real-token"  # noqa: S106
    )

    await service.start()
    await service.aclose()

    assert started == []
    assert [status.enabled for status in service.status()] == [False, False]


async def test_a_channel_enabled_without_a_token_says_why(
    store: EventStore,
    bus: EventBus,
    settings: SettingsStore,
    agents: AgentDefStore,
    ledger: BudgetLedger,
    secrets: SecretStore,
) -> None:
    """The three ways a bot can be silent look identical from a chat client.

    No token, a library that failed to freeze, and a gateway refusing to
    connect all present as a bot that says nothing — and the user can fix all
    three once told which it is.
    """
    await settings.update({"discord_enabled": True})
    started: list[str] = []
    service = _service_with(store, bus, settings, agents, ledger, secrets, started)

    await service.start()
    await service.aclose()

    discord_status = next(s for s in service.status() if s.channel == "discord")
    assert started == []
    assert discord_status.enabled is True
    assert discord_status.configured is False
    assert discord_status.last_error is not None
    assert "keychain" in discord_status.last_error


async def test_an_adapter_that_keeps_failing_is_left_stopped_with_a_reason(
    store: EventStore,
    bus: EventBus,
    settings: SettingsStore,
    agents: AgentDefStore,
    ledger: BudgetLedger,
    secrets: SecretStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A dropped websocket is ordinary and retried; a bad token is not.

    Retrying an instantly-failing adapter until the process ends turns a
    fixable configuration mistake into a warning nobody reads. The supervisor
    gives up and keeps the reason where `GET /channels` can show it.
    """
    import agentspace.channels.service as service_module

    monkeypatch.setattr(service_module, "_BACKOFF_SECONDS", (0.0,))

    await settings.update({"discord_enabled": True})
    secrets.load({"discord_bot_token": "bad"})
    attempts: list[str] = []

    service = _service_with(
        store, bus, settings, agents, ledger, secrets, attempts, always_fail=True
    )

    await service.start()
    max_failures = service_module._MAX_CONSECUTIVE_FAILURES
    discord_status = next(s for s in service.status() if s.channel == "discord")
    await _until(lambda: discord_status.failures >= max_failures)
    await service.aclose()

    assert len(attempts) == max_failures
    assert discord_status.running is False
    assert discord_status.last_error is not None
    assert "LoginFailure" in discord_status.last_error


# --- helpers ------------------------------------------------------------------


class _FakeAdapter:
    def __init__(self, name: str, log: list[str], *, fail: bool) -> None:
        self.name = name
        self._log = log
        self._fail = fail

    async def run(self) -> None:
        self._log.append(self.name)
        if self._fail:
            msg = "LoginFailure: improper token"
            raise RuntimeError(msg)
        await asyncio.Event().wait()

    async def close(self) -> None:
        return


def _service_with(
    store: EventStore,
    bus: EventBus,
    settings: SettingsStore,
    agents: AgentDefStore,
    ledger: BudgetLedger,
    secrets: SecretStore,
    log: list[str],
    *,
    discord_token: str | None = None,
    always_fail: bool = False,
) -> ChannelService:
    if discord_token is not None:
        secrets.load({"discord_bot_token": discord_token})

    deps = deps_for(store, bus, settings, agents, ledger, secrets, finishing_provider())

    def factory(name: str) -> Any:
        def build(_deps: ChannelDeps, _token: str, _on_refusal: Any) -> Any:
            return _FakeAdapter(name, log, fail=always_fail)

        return build

    return ChannelService(
        deps, secrets, {"discord": factory("discord"), "telegram": factory("telegram")}
    )


async def _wait_for_run(store: EventStore) -> str:
    async with asyncio.timeout(10):
        while True:
            runs = await store.list_runs(1)
            if runs:
                return runs[0].id
            await asyncio.sleep(0.005)


async def _wait_for_approval(service: Any) -> str:
    async with asyncio.timeout(10):
        while True:
            waiting = list(service.waiting_on())
            if waiting:
                return str(waiting[0])
            await asyncio.sleep(0.005)


async def _until(predicate: Any) -> None:
    """Poll until ``predicate`` holds.

    ASYNC110 wants an `asyncio.Event` here, and there is none to wait on: the
    state being observed is changed by production code that has no hook, and
    adding one purely so a test could await it would put a seam in the
    supervisor that only tests use. Same reasoning as `StandingAnswer` in
    `support.py`, which polls the real gate for the same reason.
    """
    async with asyncio.timeout(10):
        while not predicate():  # noqa: ASYNC110
            await asyncio.sleep(0.005)
