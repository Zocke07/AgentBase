"""The approval gate, and §5 Phase 6's acceptance criterion.

> **Accept when:** an agent instructed to write outside the workspace root is
> blocked at the sandbox layer, and this is visible in the event log as
> `tool.denied`.

:func:`test_an_agent_told_to_write_outside_the_workspace_is_blocked` is that
sentence, end to end, through a real run. Everything else here covers the
machinery it depends on and the three ways a call can be stopped, which the log
has to be able to tell apart:

* the **allowlist** refused it — the agent's definition never permitted it
  (Phase 5's boundary, covered in `test_agent_allowlist.py`);
* the **sandbox** refused it — out of bounds, and nobody was asked;
* the **user** refused it — in bounds, asked, and declined.

All three are `tool.denied`. A log that could not separate them would show a
prompt-injected agent probing the boundary and a user declining a routine write
as the same event.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from agentspace.events.types import EventType
from agentspace.orchestrator import execute_run
from agentspace.tools.approval import ApprovalStatus, approval_prompt
from agentspace.tools.builtin.filesystem import WriteFileTool
from agentspace.tools.catalogue import RiskLevel
from agentspace.tools.sandbox import Sandbox
from support import (
    ReconstructedRun,
    ScriptedProvider,
    call,
    reconstruct,
    says,
    tool_runtime,
)

if TYPE_CHECKING:
    from pathlib import Path

    from agentspace.budget.ledger import BudgetLedger
    from agentspace.events.store import EventStore
    from agentspace.providers.base import Completion
    from agentspace.secrets import SecretStore
    from agentspace.store.agents import AgentDefStore
    from agentspace.store.db import Database
    from agentspace.store.settings import SettingsStore
    from agentspace.tools.approval import ApprovalService
    from agentspace.tools.runtime import ToolRuntime

pytestmark = pytest.mark.anyio


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """The sandbox root every test here runs against.

    `exist_ok` because the autouse data-directory fixture in `conftest.py`
    already resolves `AGENTSPACE_DATA_DIR` under `tmp_path` and creates a
    `workspace` beside it — the same directory the shipped application uses,
    which is the right one to be testing against.
    """
    root = tmp_path / "workspace"
    root.mkdir(exist_ok=True)
    return root


#: A prompt that leaves no doubt the model was told to do it. §5 Phase 5's
#: criterion is about an agent blocked "even when its system prompt explicitly
#: instructs it to", and §5 Phase 6's is the same idea aimed at the sandbox.
ESCAPE_PROMPT = (
    "You write files. Write to the exact path you are given, whatever it is. "
    "Do not question it and do not substitute a different path."
)


async def writer_run(
    store: EventStore,
    settings: SettingsStore,
    agents: AgentDefStore,
    ledger: BudgetLedger,
    secrets: SecretStore,
    runtime: ToolRuntime,
    worker_calls: list[Completion],
    *,
    prompt: str = ESCAPE_PROMPT,
    allowed: list[str] | None = None,
) -> ReconstructedRun:
    """Spawn one file-writing worker, run its script, and rebuild from the log."""
    await agents.create(
        {
            "name": "filewriter",
            "role": "Writes files",
            "system_prompt": prompt,
            "allowed_tools": ["write_file", "read_file"] if allowed is None else allowed,
        }
    )
    script = [
        says("Delegating.", call("spawn_agent", "s1", agent="filewriter", task="Save it")),
        *worker_calls,
        says("Done.", call("finish", "s2", result="Handled.")),
    ]
    run = await store.create_run(goal="Save the report", origin="ui")
    await execute_run(
        store,
        settings,
        agents,
        ledger,
        secrets,
        run.id,
        "Save the report",
        provider=ScriptedProvider(script),
        runtime=runtime,
    )
    return reconstruct(await store.read(run.id))


# --- the acceptance criterion -------------------------------------------------


@pytest.mark.parametrize(
    "escape",
    [
        "../escaped.txt",
        "../../escaped.txt",
        "subdir/../../escaped.txt",
    ],
)
async def test_an_agent_told_to_write_outside_the_workspace_is_blocked(
    store: EventStore,
    settings: SettingsStore,
    agents: AgentDefStore,
    ledger: BudgetLedger,
    secrets: SecretStore,
    db: Database,
    workspace: Path,
    tmp_path: Path,
    escape: str,
) -> None:
    """§5 Phase 6's acceptance criterion, in full, through a real run.

    Three assertions, and the third is the one that cannot be faked: the file
    is not on disk. A log saying `tool.denied` while the write happened anyway
    would satisfy the other two.
    """
    # Everything pre-approved, so nothing here can pass merely because the gate
    # happened to stop it. The sandbox is what must refuse this.
    await settings.update({"auto_approve": [RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH]})
    runtime, _ = tool_runtime(store, db, workspace)

    rebuilt = await writer_run(
        store,
        settings,
        agents,
        ledger,
        secrets,
        runtime,
        [
            says("Writing.", call("write_file", "w1", path=escape, content="escaped!")),
            says("Blocked.", call("finish", "w2", result="Could not write there.")),
        ],
    )

    writer = rebuilt.agent("filewriter")

    # 1. Blocked, and visible in the event log as `tool.denied`.
    assert writer.denied_tools == ["write_file"]

    # 2. Blocked *at the sandbox layer* — before anyone was asked. Everything
    #    was pre-approved, so an approval would have been granted instantly had
    #    the call ever reached the gate.
    assert writer.denied_by == ["sandbox"]
    assert writer.approvals_requested == []

    # 3. Nothing executed, and nothing is on disk outside the workspace.
    #    Through `to_thread` because these are blocking filesystem calls in an
    #    async test; the assertion is the point of the test, so it moves off
    #    the loop rather than being dropped.
    assert [name for name, _ in writer.tool_calls] == ["finish"]
    escaped = await asyncio.to_thread(lambda: list(tmp_path.rglob("escaped.txt")))
    assert escaped == []


async def test_the_attempt_is_logged_beside_the_refusal(
    store: EventStore,
    settings: SettingsStore,
    agents: AgentDefStore,
    ledger: BudgetLedger,
    secrets: SecretStore,
    db: Database,
    workspace: Path,
) -> None:
    """ "Blocked" is only observable if the attempt is in the log too.

    Same rule Phase 5 established for the allowlist: a denial that erased what
    was attempted would leave a replay unable to say what the agent tried to
    do, which for a traversal attempt is the single most interesting fact.
    """
    runtime, _ = tool_runtime(store, db, workspace)

    run = await store.create_run(goal="escape", origin="ui")
    await agents.create(
        {
            "name": "filewriter",
            "role": "Writes files",
            "system_prompt": ESCAPE_PROMPT,
            "allowed_tools": ["write_file"],
        }
    )
    await execute_run(
        store,
        settings,
        agents,
        ledger,
        secrets,
        run.id,
        "escape",
        provider=ScriptedProvider(
            [
                says("Go.", call("spawn_agent", "s1", agent="filewriter", task="Save")),
                says("Writing.", call("write_file", "w1", path="../out.txt", content="x")),
                says("Blocked.", call("finish", "w2", result="Refused.")),
                says("Done.", call("finish", "s2", result="Done.")),
            ]
        ),
        runtime=runtime,
    )

    events = [e for e in await store.read(run.id) if e.agent_id == "filewriter"]
    types = [event.type for event in events]
    assert types.index(EventType.TOOL_REQUESTED) < types.index(EventType.TOOL_DENIED)

    requested = next(e for e in events if e.type is EventType.TOOL_REQUESTED)
    assert requested.payload["args"]["path"] == "../out.txt"

    denied = next(e for e in events if e.type is EventType.TOOL_DENIED)
    assert "outside the workspace" in denied.payload["reason"]
    assert denied.payload["blocked_by"] == "sandbox"


# --- a call the user is actually asked about ----------------------------------


async def test_a_medium_risk_call_blocks_until_a_person_answers(
    store: EventStore,
    settings: SettingsStore,
    agents: AgentDefStore,
    ledger: BudgetLedger,
    secrets: SecretStore,
    db: Database,
    workspace: Path,
) -> None:
    """§5 Phase 6: a medium-risk call "blocks until resolved".

    The run is started as a task and deliberately *not* answered for a moment.
    The assertion that matters is the one taken while it is waiting: the file
    does not exist yet. A gate that emitted `approval.requested` and carried on
    would already have written it.
    """
    runtime, service = tool_runtime(store, db, workspace)

    task = asyncio.create_task(
        writer_run(
            store,
            settings,
            agents,
            ledger,
            secrets,
            runtime,
            [
                says("Writing.", call("write_file", "w1", path="notes.txt", content="hi")),
                says("Done.", call("finish", "w2", result="Written.")),
            ],
        )
    )

    approval_id = await _wait_for_approval(service)

    # Still blocked: asked, and not yet answered.
    assert not (workspace / "notes.txt").exists()
    assert task.done() is False

    await service.resolve(approval_id, approved=True)
    rebuilt = await task

    writer = rebuilt.agent("filewriter")
    assert writer.approvals_requested == [("write_file", "medium")]
    assert writer.approvals_resolved == [("write_file", "approved")]
    assert writer.approved_tools == [("write_file", False)]
    assert [name for name, _ in writer.tool_calls] == ["write_file", "finish"]
    assert (workspace / "notes.txt").read_text(encoding="utf-8") == "hi"


async def test_a_denied_call_does_not_happen(
    store: EventStore,
    settings: SettingsStore,
    agents: AgentDefStore,
    ledger: BudgetLedger,
    secrets: SecretStore,
    db: Database,
    workspace: Path,
) -> None:
    """The user says no, and the file is not written."""
    runtime, service = tool_runtime(store, db, workspace)

    task = asyncio.create_task(
        writer_run(
            store,
            settings,
            agents,
            ledger,
            secrets,
            runtime,
            [
                says("Writing.", call("write_file", "w1", path="notes.txt", content="hi")),
                says("Fine.", call("finish", "w2", result="Not written.")),
            ],
        )
    )

    approval_id = await _wait_for_approval(service)
    await service.resolve(approval_id, approved=False)
    rebuilt = await task

    writer = rebuilt.agent("filewriter")
    assert writer.approvals_resolved == [("write_file", "denied")]
    assert writer.denied_tools == ["write_file"]
    # A user's refusal is not a sandbox violation, and the log says so.
    assert writer.denied_by == [None]
    assert [name for name, _ in writer.tool_calls] == ["finish"]
    assert not (workspace / "notes.txt").exists()


async def test_a_call_the_user_already_denied_is_not_asked_again_in_that_run(
    store: EventStore,
    settings: SettingsStore,
    agents: AgentDefStore,
    ledger: BudgetLedger,
    secrets: SecretStore,
    db: Database,
    workspace: Path,
) -> None:
    """Phase 6 watched a denial stop a call and not a run: the worker gave up,
    the supervisor spawned a second copy of the same definition, and it asked
    for the same overwrite again. "Deny" meant "not this call", and the only
    things bounding a supervisor that re-asks were the step limit and the
    agent cap — a single no could become a war of attrition.

    Now a denial sticks for the run. The same tool with the same arguments,
    from any agent in the run, is denied by the earlier answer without the
    person being asked: a row is still written and both events still emitted,
    marked automatic and naming the decision they rest on, so the history
    says what happened and the dialog never shows a question nobody is asked.
    """
    runtime, service = tool_runtime(store, db, workspace)

    task = asyncio.create_task(
        writer_run(
            store,
            settings,
            agents,
            ledger,
            secrets,
            runtime,
            [
                says("Writing.", call("write_file", "w1", path="notes.txt", content="hi")),
                says("Once more.", call("write_file", "w2", path="notes.txt", content="hi")),
                says("Fine.", call("finish", "w3", result="Not written.")),
            ],
        )
    )

    first = await _wait_for_approval(service)
    await service.resolve(first, approved=False)
    # The second identical call must not wait on the gate; if it did, this
    # would hang until the test timeout, which is the old behaviour.
    rebuilt = await asyncio.wait_for(task, timeout=10)

    writer = rebuilt.agent("filewriter")
    assert writer.approvals_resolved == [("write_file", "denied"), ("write_file", "denied")]
    assert writer.denied_tools == ["write_file", "write_file"]
    assert [name for name, _ in writer.tool_calls] == ["finish"]
    assert not (workspace / "notes.txt").exists()

    (run,) = await store.list_runs()
    events = await store.read(run.id)
    requested = [e.payload for e in events if e.type is EventType.APPROVAL_REQUESTED]
    resolved = [e.payload for e in events if e.type is EventType.APPROVAL_RESOLVED]
    denied = [e.payload for e in events if e.type is EventType.TOOL_DENIED]
    assert [r.get("automatic", False) for r in requested] == [False, True]
    assert [r.get("automatic", False) for r in resolved] == [False, True]
    # The repeat names the decision it rests on.
    assert requested[1]["precedent"] == first
    assert resolved[1]["precedent"] == first
    assert "already" in denied[1]["reason"].lower()
    # The table agrees: two rows, both denied, and nothing left pending.
    assert await service.store.list_pending(run.id) == []


async def test_a_different_call_after_a_denial_is_still_asked(
    store: EventStore,
    settings: SettingsStore,
    agents: AgentDefStore,
    ledger: BudgetLedger,
    secrets: SecretStore,
    db: Database,
    workspace: Path,
) -> None:
    """Sticky means this exact call. Different content is a different
    question, and the person gets to answer it."""
    runtime, service = tool_runtime(store, db, workspace)

    task = asyncio.create_task(
        writer_run(
            store,
            settings,
            agents,
            ledger,
            secrets,
            runtime,
            [
                says("Writing.", call("write_file", "w1", path="notes.txt", content="hi")),
                says("Shorter.", call("write_file", "w2", path="notes.txt", content="hello")),
                says("Done.", call("finish", "w3", result="Written.")),
            ],
        )
    )

    first = await _wait_for_approval(service)
    await service.resolve(first, approved=False)
    second = await _wait_for_approval(service, after=first)
    await service.resolve(second, approved=True)
    rebuilt = await asyncio.wait_for(task, timeout=10)

    writer = rebuilt.agent("filewriter")
    assert writer.approvals_resolved == [("write_file", "denied"), ("write_file", "approved")]
    assert (workspace / "notes.txt").read_text(encoding="utf-8") == "hello"


async def test_the_prompt_a_user_sees_is_a_sentence_not_json(
    store: EventStore,
    settings: SettingsStore,
    agents: AgentDefStore,
    ledger: BudgetLedger,
    secrets: SecretStore,
    db: Database,
    workspace: Path,
) -> None:
    """§5 Phase 6: 'Approval prompts must be human-legible, not raw JSON.'

    The spec's own example is `Agent "researcher" wants to delete report.docx`,
    so the assertion is on the shape of that sentence: who, what, and the file
    named the way the user knows it — not an absolute path that leaks the
    account name, and not the argument dictionary.
    """
    runtime, service = tool_runtime(store, db, workspace)

    task = asyncio.create_task(
        writer_run(
            store,
            settings,
            agents,
            ledger,
            secrets,
            runtime,
            [
                says("Writing.", call("write_file", "w1", path="report.md", content="hello")),
                says("Done.", call("finish", "w2", result="Written.")),
            ],
        )
    )
    approval_id = await _wait_for_approval(service)
    await service.resolve(approval_id, approved=True)
    rebuilt = await task

    prompts = rebuilt.agent("filewriter").approval_prompts
    assert len(prompts) == 1
    prompt = prompts[0]

    assert prompt == 'Agent "filewriter" wants to create the file report.md (5 characters)'
    # Not raw JSON, and not an absolute path leaking the account name.
    assert "{" not in prompt
    assert str(workspace) not in prompt


def test_overwriting_says_overwrite_and_creating_says_create(workspace: Path) -> None:
    """Two decisions that are not the same decision.

    Creating a file is additive; overwriting one destroys work that may not be
    recoverable. §5 Phase 6's own example prompt is about a destructive call,
    and a prompt that read the same either way would hide the difference at the
    moment the user is deciding.
    """
    sandbox = Sandbox(workspace)
    tool = WriteFileTool()

    creating = tool.prepare({"path": "new.md", "content": "x"}, sandbox)
    assert approval_prompt("writer", creating).startswith(
        'Agent "writer" wants to create the file new.md'
    )

    (workspace / "existing.md").write_text("old", encoding="utf-8")
    overwriting = tool.prepare({"path": "existing.md", "content": "x"}, sandbox)
    assert approval_prompt("writer", overwriting).startswith(
        'Agent "writer" wants to overwrite the file existing.md'
    )


# --- policy -------------------------------------------------------------------


async def test_a_pre_approved_risk_level_runs_without_asking(
    store: EventStore,
    settings: SettingsStore,
    agents: AgentDefStore,
    ledger: BudgetLedger,
    secrets: SecretStore,
    db: Database,
    workspace: Path,
) -> None:
    """§5 Phase 6's unattended-operation policy, doing its job.

    Nothing answers the gate here — there is no `StandingAnswer` and no HTTP
    call. The run completes because the workspace pre-authorized the level, and
    it would block until `pytest-timeout` killed it if the policy were inert.
    """
    await settings.update({"auto_approve": [RiskLevel.MEDIUM]})
    runtime, _ = tool_runtime(store, db, workspace)

    rebuilt = await writer_run(
        store,
        settings,
        agents,
        ledger,
        secrets,
        runtime,
        [
            says("Writing.", call("write_file", "w1", path="notes.txt", content="auto")),
            says("Done.", call("finish", "w2", result="Written.")),
        ],
    )

    writer = rebuilt.agent("filewriter")
    # Recorded as an approval even though nobody was asked: the question "what
    # did this run do without asking me" has to be answerable from the log.
    assert writer.approvals_requested == [("write_file", "medium")]
    assert writer.approvals_resolved == [("write_file", "approved")]
    assert writer.approved_tools == [("write_file", True)]
    assert (workspace / "notes.txt").read_text(encoding="utf-8") == "auto"


async def test_the_default_workspace_asks_about_everything(
    store: EventStore,
    settings: SettingsStore,
    db: Database,
    workspace: Path,
) -> None:
    """§5 Phase 6: "Default is manual-approve-everything."

    Including `low`. §5 says low risk *may* be auto-approved by policy, which
    is permission to offer the setting, not permission to default it on.
    """
    resolved = await settings.get()
    assert resolved.auto_approve == []

    runtime, _ = tool_runtime(store, db, workspace, auto_approve=resolved.auto_approve)
    for level in RiskLevel:
        assert runtime.auto_approve_for(()) == frozenset()
        assert runtime.auto_approve_for((level,)) == frozenset()


async def test_a_definition_cannot_pre_approve_beyond_the_workspace(
    store: EventStore,
    db: Database,
    workspace: Path,
) -> None:
    """§5 Phase 5's security note, now that something consumes it.

    A definition asking for `high` against a workspace allowing only `low` gets
    `low` — never `high`, and never both. This is the rule that stops a
    user-authored row from escalating its own privileges, and it is the reason
    the empty-means-inherit decision above is safe: every branch returns a
    subset of the workspace policy.
    """
    runtime, _ = tool_runtime(store, db, workspace, auto_approve=[RiskLevel.LOW])

    assert runtime.auto_approve_for((RiskLevel.HIGH,)) == frozenset()
    assert runtime.auto_approve_for((RiskLevel.LOW, RiskLevel.HIGH)) == {RiskLevel.LOW}
    assert runtime.auto_approve_for((RiskLevel.MEDIUM,)) == frozenset()

    # And the inherit case is still bounded by the workspace.
    assert runtime.auto_approve_for(()) == {RiskLevel.LOW}


async def test_an_unset_definition_inherits_the_workspace_policy(
    store: EventStore,
    db: Database,
    workspace: Path,
) -> None:
    """The judgement call in `ToolRuntime.auto_approve_for`, pinned.

    §4 defaults `auto_approve` to `'[]'` and every seeded built-in carries it,
    so a strict intersection would make the workspace policy inert — a setting
    that reports success and changes nothing, which this project has shipped
    once already. A row nobody has edited has not declined anything.
    """
    runtime, _ = tool_runtime(
        store, db, workspace, auto_approve=[RiskLevel.LOW, RiskLevel.MEDIUM]
    )

    assert runtime.auto_approve_for(()) == {RiskLevel.LOW, RiskLevel.MEDIUM}


async def test_the_policy_is_snapshotted_at_run_start(
    store: EventStore,
    settings: SettingsStore,
    agents: AgentDefStore,
    ledger: BudgetLedger,
    secrets: SecretStore,
    db: Database,
    workspace: Path,
) -> None:
    """A policy widened mid-run does not loosen a run already in flight.

    Same rule as the roster and the run limits: a run must not be held to
    different rules at step 1 and step 12. The direction that matters is
    widening — a gate that silently stopped asking partway through a run would
    be the safety property evaporating while work was in progress.
    """
    runtime, service = tool_runtime(store, db, workspace)

    task = asyncio.create_task(
        writer_run(
            store,
            settings,
            agents,
            ledger,
            secrets,
            runtime,
            [
                says("Writing.", call("write_file", "w1", path="a.txt", content="one")),
                says("Done.", call("finish", "w2", result="Written.")),
            ],
        )
    )

    approval_id = await _wait_for_approval(service)

    # Widen the policy while the run is blocked on the gate.
    await settings.update({"auto_approve": [RiskLevel.MEDIUM]})

    # The run is still waiting, because it was started under the old policy.
    await asyncio.sleep(0.05)
    assert not task.done()

    await service.resolve(approval_id, approved=True)
    rebuilt = await task
    assert rebuilt.agent("filewriter").approved_tools == [("write_file", False)]


# --- expiry -------------------------------------------------------------------


async def test_an_unanswered_approval_expires_with_the_run_deadline(
    store: EventStore,
    settings: SettingsStore,
    agents: AgentDefStore,
    ledger: BudgetLedger,
    secrets: SecretStore,
    db: Database,
    workspace: Path,
) -> None:
    """Nobody answers, and the run does not wait forever.

    The gate borrows the run's wall-clock budget rather than keeping a deadline
    of its own — see `Run.remaining_seconds`. With a 1-second run limit the
    approval expires, the call is denied, and the run fails on the clock.
    """
    await settings.update({"max_run_seconds": 1})
    runtime, service = tool_runtime(store, db, workspace)

    rebuilt = await writer_run(
        store,
        settings,
        agents,
        ledger,
        secrets,
        runtime,
        [
            says("Writing.", call("write_file", "w1", path="notes.txt", content="hi")),
            says("Gave up.", call("finish", "w2", result="Nobody answered.")),
        ],
    )

    writer = rebuilt.agent("filewriter")
    assert writer.approvals_resolved == [("write_file", "expired")]
    assert writer.denied_tools == ["write_file"]
    assert not (workspace / "notes.txt").exists()

    # The row is settled, not left pending forever.
    assert await service.store.list_pending() == []


async def test_pending_approvals_from_a_previous_process_are_expired(
    store: EventStore, db: Database, workspace: Path
) -> None:
    """A restart makes every outstanding approval unanswerable.

    Its waiter was an `asyncio.Future` in a process that no longer exists, so
    resolving the row would update a database and unblock nothing. Left alone
    they surface in the Phase 7 dialog as live questions about runs that ended
    when the app last closed.
    """
    _, service = tool_runtime(store, db, workspace)
    run = await store.create_run(goal="orphan", origin="ui")

    await service.store.create(run.id, "write_file", {"path": "a.txt"}, RiskLevel.MEDIUM)
    await service.store.create(run.id, "run_shell", {"command": "ls"}, RiskLevel.HIGH)
    assert len(await service.store.list_pending()) == 2

    # A new process starts.
    expired = await service.store.expire_orphaned_pending()

    assert expired == 2
    assert await service.store.list_pending() == []


async def test_expiring_orphans_leaves_settled_rows_alone(
    store: EventStore, db: Database, workspace: Path
) -> None:
    """The sweep must not rewrite history it did not create."""
    _, service = tool_runtime(store, db, workspace)
    run = await store.create_run(goal="orphan", origin="ui")

    settled = await service.store.create(
        run.id, "write_file", {"path": "a.txt"}, RiskLevel.MEDIUM
    )
    await service.store.settle(settled.id, ApprovalStatus.APPROVED)

    assert await service.store.expire_orphaned_pending() == 0

    record = await service.store.get(settled.id)
    assert record is not None
    assert record.status is ApprovalStatus.APPROVED


# --- resolving twice ----------------------------------------------------------


async def test_an_approval_cannot_be_resolved_twice(
    store: EventStore, db: Database, workspace: Path
) -> None:
    """Two dialogs open on the same approval is ordinary, not a race to ignore.

    The `UPDATE ... WHERE status = 'pending'` is conditional in one statement,
    so the second resolution finds nothing to change and raises rather than
    quietly flipping an approval a user already denied into an approval.
    """
    from agentspace.tools.approval import ApprovalNotPendingError

    _, service = tool_runtime(store, db, workspace)
    run = await store.create_run(goal="twice", origin="ui")

    record = await service.store.create(
        run.id, "write_file", {"path": "a.txt"}, RiskLevel.MEDIUM
    )

    await service.resolve(record.id, approved=False)

    with pytest.raises(ApprovalNotPendingError) as caught:
        await service.resolve(record.id, approved=True)

    assert "already denied" in str(caught.value)

    settled = await service.store.get(record.id)
    assert settled is not None
    assert settled.status is ApprovalStatus.DENIED


# --- helpers ------------------------------------------------------------------


async def _wait_for_approval(
    service: ApprovalService, limit_seconds: float = 5.0, *, after: str | None = None
) -> str:
    """Block until the run under test is actually suspended on the gate.

    Waits on `waiting_on()` rather than on the table: a row exists a moment
    before the future does, and resolving in that window would set no waiter
    and hang the test for reasons that have nothing to do with what it asserts.
    ``after`` skips an approval just resolved, whose waiter is gone a moment
    after its future is set.
    """

    async def poll() -> str:
        while True:
            waiting = [
                approval_id for approval_id in service.waiting_on() if approval_id != after
            ]
            if waiting:
                return waiting[0]
            await asyncio.sleep(0.005)

    return await asyncio.wait_for(poll(), timeout=limit_seconds)
