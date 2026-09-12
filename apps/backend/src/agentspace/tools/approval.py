"""The human-in-the-loop gate: the one thing standing between an agent and the disk.

§1 constraint 5: "Every filesystem/shell/network tool call passes an approval
gate before execution. No exceptions, no privileged paths for any channel", is
the constraint this module exists to make structural. §5 Phase 6 sets the
policy: "any `medium`/`high` risk call emits `approval.requested` and blocks
until resolved. `low` risk (read within workspace) may be auto-approved by
policy", with a default of manual-approve-everything.

**What "blocks" means.** :meth:`ApprovalService.request` writes a row, emits
`approval.requested`, and then genuinely suspends the calling agent on an
`asyncio.Future` until somebody resolves it over HTTP. Nothing polls, nothing
times out on a private clock, and, importantly, the agent does not get a
"pending" reply it might reason its way around. There is one code path from
"the agent asked" to "the tool ran", and a decision sits in the middle of it.

**Three states, and a fourth that is about the process rather than the user.**
Approved and denied come from a person. Auto-approved comes from policy and is
recorded as `approval.resolved` all the same, because a projection of the event
log must be able to say why a call proceeded without a dialog: a silent
auto-approval would make the log claim the user agreed to something they never
saw. Expired is the fourth: a pending approval's waiter is an in-process
future, so a sidecar restart makes every outstanding row permanently
unresolvable, and a run outliving its wall-clock deadline while waiting has to
stop waiting.

**The policy can only narrow.** :func:`~agentspace.tools.catalogue.effective_auto_approve`
intersects a definition's `auto_approve` with the workspace's, which is §5
Phase 5's security note in one line: "may only *narrow* what the global policy
already permits; it can never grant a risk level the workspace policy has not
enabled". Written in Phase 5, consumed here for the first time.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from agentspace.events.types import EventType
from agentspace.tools.catalogue import RiskLevel

if TYPE_CHECKING:
    from collections.abc import Iterable

    from agentspace.events.store import EventStore
    from agentspace.store.db import Database
    from agentspace.tools.base import Prepared

__all__ = [
    "ApprovalDecision",
    "ApprovalNotPendingError",
    "ApprovalRecord",
    "ApprovalService",
    "ApprovalStatus",
    "ApprovalStore",
    "approval_prompt",
]


class ApprovalStatus(StrEnum):
    """§4 `approvals.status`, verbatim."""

    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"


class ApprovalNotPendingError(Exception):
    """An attempt to resolve an approval that is already settled or unknown.

    A 409 rather than a 404 at the API layer when the row exists: resolving the
    same approval twice is a conflict with state, most often two clicks on a
    dialog that two windows are both showing.
    """


@dataclass(frozen=True, slots=True)
class ApprovalRecord:
    """One row of `approvals` (§4)."""

    id: str
    run_id: str
    tool: str
    args: dict[str, Any]
    risk: RiskLevel
    status: ApprovalStatus
    created_at: datetime
    resolved_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ApprovalDecision:
    """What the gate concluded, and why.

    ``automatic`` separates "the user said yes" from "policy said yes without
    asking". Both allow the call; only one of them is a person, and an audit of
    what a run did needs to tell them apart.
    """

    allowed: bool
    status: ApprovalStatus
    reason: str
    approval_id: str | None = None
    automatic: bool = False


def approval_prompt(agent: str, prepared: Prepared) -> str:
    """The sentence a human is asked to judge.

    §5 Phase 6: "Approval prompts must be **human-legible**, not raw JSON:
    `Agent "researcher" wants to delete report.docx: Allow / Deny`." The
    Allow/Deny half is the UI's; the sentence is this function's, and it is
    built from :attr:`agentspace.tools.base.Prepared.summary` (the *resolved*
    call) rather than the arguments the model sent. Rendering the raw arguments
    would describe a different call from the one that would run, which is
    precisely the gap a traversal attempt lives in.
    """
    return f'Agent "{agent}" wants to {prepared.summary}'


class ApprovalStore:
    """The `approvals` table.

    Current state, not history: the history is `approval.requested` and
    `approval.resolved` in the event log, which §2 makes the authority. This
    exists because "what is outstanding right now" is a question about state,
    and answering it by folding the whole event log would be the wrong shape for
    a dialog that has to appear immediately.
    """

    def __init__(self, db: Database) -> None:
        self._db = db

    async def create(
        self, run_id: str, tool: str, args: dict[str, Any], risk: RiskLevel
    ) -> ApprovalRecord:
        return await asyncio.to_thread(self._create_sync, run_id, tool, args, risk)

    def _create_sync(
        self, run_id: str, tool: str, args: dict[str, Any], risk: RiskLevel
    ) -> ApprovalRecord:
        record = ApprovalRecord(
            id=str(uuid.uuid4()),
            run_id=run_id,
            tool=tool,
            args=args,
            risk=risk,
            status=ApprovalStatus.PENDING,
            created_at=datetime.now(UTC),
        )
        with self._db.write() as connection:
            connection.execute(
                "INSERT INTO approvals (id, run_id, tool, args, risk, status, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    record.id,
                    record.run_id,
                    record.tool,
                    json.dumps(record.args, separators=(",", ":"), default=str),
                    str(record.risk),
                    str(record.status),
                    record.created_at.isoformat(),
                ),
            )
        return record

    async def get(self, approval_id: str) -> ApprovalRecord | None:
        return await asyncio.to_thread(self._get_sync, approval_id)

    def _get_sync(self, approval_id: str) -> ApprovalRecord | None:
        with self._db.read() as connection:
            row = connection.execute(
                "SELECT * FROM approvals WHERE id = ?", (approval_id,)
            ).fetchone()
        return _record(row) if row is not None else None

    async def list_pending(self, run_id: str | None = None) -> list[ApprovalRecord]:
        return await asyncio.to_thread(self._list_pending_sync, run_id)

    async def find_denied(
        self, run_id: str, tool: str, args: dict[str, Any]
    ) -> ApprovalRecord | None:
        """The earliest denial in this run of exactly this call, if any.

        "Exactly" is the tool and the arguments as the model sent them: the
        same question, not a similar one. Different content in the same file
        is a different question and is asked. Compared as parsed objects, so
        key order in the stored JSON does not decide it.
        """
        return await asyncio.to_thread(self._find_denied_sync, run_id, tool, args)

    def _find_denied_sync(
        self, run_id: str, tool: str, args: dict[str, Any]
    ) -> ApprovalRecord | None:
        with self._db.read() as connection:
            rows = connection.execute(
                "SELECT * FROM approvals WHERE run_id = ? AND tool = ? AND status = ?"
                " ORDER BY created_at, rowid",
                (run_id, tool, str(ApprovalStatus.DENIED)),
            ).fetchall()
        for row in rows:
            record = _record(row)
            if record.args == args:
                return record
        return None

    def _list_pending_sync(self, run_id: str | None) -> list[ApprovalRecord]:
        with self._db.read() as connection:
            if run_id is None:
                rows = connection.execute(
                    "SELECT * FROM approvals WHERE status = ? ORDER BY created_at",
                    (str(ApprovalStatus.PENDING),),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM approvals WHERE run_id = ? AND status = ?"
                    " ORDER BY created_at",
                    (run_id, str(ApprovalStatus.PENDING)),
                ).fetchall()
        return [_record(row) for row in rows]

    async def settle(self, approval_id: str, status: ApprovalStatus) -> ApprovalRecord:
        """Move a pending approval to a terminal status.

        Conditional on the row still being pending, in one statement, so two
        concurrent resolutions cannot both succeed, the second finds nothing
        to update and raises. Two dialogs open on the same approval is an
        ordinary thing, not a race worth ignoring.

        :raises ApprovalNotPendingError: unknown, or already settled.
        """
        return await asyncio.to_thread(self._settle_sync, approval_id, status)

    def _settle_sync(self, approval_id: str, status: ApprovalStatus) -> ApprovalRecord:
        resolved_at = datetime.now(UTC).isoformat()
        with self._db.write() as connection:
            cursor = connection.execute(
                "UPDATE approvals SET status = ?, resolved_at = ? WHERE id = ? AND status = ?",
                (str(status), resolved_at, approval_id, str(ApprovalStatus.PENDING)),
            )
            if cursor.rowcount == 0:
                existing = connection.execute(
                    "SELECT status FROM approvals WHERE id = ?", (approval_id,)
                ).fetchone()
                if existing is None:
                    msg = f"There is no approval with id {approval_id!r}."
                else:
                    msg = (
                        f"Approval {approval_id!r} was already "
                        f"{existing['status']} and cannot be changed."
                    )
                raise ApprovalNotPendingError(msg)

            row = connection.execute(
                "SELECT * FROM approvals WHERE id = ?", (approval_id,)
            ).fetchone()
        return _record(row)

    async def expire_orphaned_pending(self) -> int:
        """Settle every pending approval left over from a previous process.

        Called once at startup. A pending row's waiter is an `asyncio.Future`
        in the process that created it, so after a restart nobody is listening:
        resolving one would update a row and unblock nothing, and the Phase 7
        dialog would show approvals for runs that ended days ago. Returns how
        many were closed, so the caller can log a number rather than a guess.
        """
        return await asyncio.to_thread(self._expire_orphaned_sync)

    def _expire_orphaned_sync(self) -> int:
        with self._db.write() as connection:
            cursor = connection.execute(
                "UPDATE approvals SET status = ?, resolved_at = ? WHERE status = ?",
                (
                    str(ApprovalStatus.EXPIRED),
                    datetime.now(UTC).isoformat(),
                    str(ApprovalStatus.PENDING),
                ),
            )
            return int(cursor.rowcount)


def _record(row: Any) -> ApprovalRecord:
    return ApprovalRecord(
        id=row["id"],
        run_id=row["run_id"],
        tool=row["tool"],
        args=json.loads(row["args"]),
        risk=RiskLevel(row["risk"]),
        status=ApprovalStatus(row["status"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        resolved_at=(
            datetime.fromisoformat(row["resolved_at"])
            if row["resolved_at"] is not None
            else None
        ),
    )


class ApprovalService:
    """Creates approvals, blocks on them, and resolves them.

    One instance per application, held on `app.state`, because the two halves
    live in different requests: an agent inside a run creates and awaits the
    future, and `POST /approvals/{id}` (a completely separate HTTP request)
    is what sets it. A per-run service would have nowhere to put the waiter that
    the API handler could reach.
    """

    def __init__(self, store: ApprovalStore, events: EventStore) -> None:
        self._store = store
        self._events = events
        self._waiters: dict[str, asyncio.Future[ApprovalStatus]] = {}
        #: Runs whose pending questions were released by a cancel, so the
        #: denial that follows can say why rather than blaming the clock.
        self._released: set[str] = set()

    @property
    def store(self) -> ApprovalStore:
        return self._store

    @property
    def pending_count(self) -> int:
        """How many approvals this process is currently blocked on."""
        return len(self._waiters)

    def waiting_on(self) -> tuple[str, ...]:
        """The ids this process is currently suspended on.

        Distinct from :meth:`ApprovalStore.list_pending`, which reads the
        table: this is what *this process* can actually still answer. After a
        restart the table can hold pending rows that no future backs, and the
        difference between the two is exactly what
        :meth:`ApprovalStore.expire_orphaned_pending` cleans up.
        """
        return tuple(self._waiters)

    async def request(
        self,
        *,
        run_id: str,
        agent: str,
        prepared: Prepared,
        risk: RiskLevel,
        auto_approve: Iterable[RiskLevel],
        deadline: float | None = None,
    ) -> ApprovalDecision:
        """Obtain a decision for one prepared call, blocking if a human is needed.

        :param auto_approve: the *already-intersected* policy; see
            :func:`agentspace.tools.catalogue.effective_auto_approve`. This
            method does not intersect anything itself, so that the narrowing
            rule has exactly one implementation.
        :param deadline: seconds this may block before expiring, normally the
            run's remaining wall-clock budget. ``None`` waits indefinitely.
        """
        if risk in frozenset(auto_approve):
            return await self._auto_approve(run_id, agent, prepared, risk)

        # A denial sticks for the run. Phase 6 watched a worker give up after
        # a "no", the supervisor spawn a second copy of it, and the copy ask
        # for the same overwrite: a person could be asked the same question
        # for as long as the step limit and the agent cap allowed. The same
        # call, from any agent in this run, is now denied by the earlier
        # answer without asking again.
        precedent = await self._store.find_denied(
            run_id, prepared.tool_name, prepared.raw_arguments
        )
        if precedent is not None:
            return await self._deny_by_precedent(run_id, agent, prepared, risk, precedent)

        record = await self._store.create(
            run_id, prepared.tool_name, prepared.raw_arguments, risk
        )

        await self._events.append(
            run_id,
            EventType.APPROVAL_REQUESTED,
            {
                "approval_id": record.id,
                "tool": prepared.tool_name,
                "args": prepared.raw_arguments,
                "risk": str(risk),
                # The rendered sentence, in the payload rather than composed by
                # the client. §2 makes the UI a projection of the log, and a
                # client that built its own wording could show one thing while
                # the log recorded another.
                "prompt": approval_prompt(agent, prepared),
                "summary": prepared.summary,
            },
            agent_id=agent,
        )

        status = await self._wait(record.id, deadline)

        await self._events.append(
            run_id,
            EventType.APPROVAL_RESOLVED,
            {
                "approval_id": record.id,
                "tool": prepared.tool_name,
                "status": str(status),
                "automatic": False,
            },
            agent_id=agent,
        )

        if status is ApprovalStatus.APPROVED:
            return ApprovalDecision(
                allowed=True,
                status=status,
                reason=f"The user approved this {prepared.tool_name} call.",
                approval_id=record.id,
            )

        if status is ApprovalStatus.EXPIRED:
            why = (
                "this run was cancelled"
                if run_id in self._released
                else "this run ran out of time"
            )
            return ApprovalDecision(
                allowed=False,
                status=status,
                reason=(
                    f"The request to {prepared.summary} was not answered before "
                    f"{why}, so it did not happen."
                ),
                approval_id=record.id,
            )

        return ApprovalDecision(
            allowed=False,
            status=status,
            reason=(
                f"The user denied permission to {prepared.summary}. Do not try "
                f"this call again: continue without it, or finish and say what "
                f"you could not do."
            ),
            approval_id=record.id,
        )

    async def _auto_approve(
        self, run_id: str, agent: str, prepared: Prepared, risk: RiskLevel
    ) -> ApprovalDecision:
        """Allow a call the policy pre-authorized, and say so in the log.

        A row is still written and both events are still emitted. The temptation
        is to skip all of it (nobody was asked, so what is there to record),
        and that is exactly backwards: the question a user asks afterwards is
        "what did this run do without asking me", and it is only answerable if
        the automatic decisions are in the log beside the manual ones.
        """
        record = await self._store.create(
            run_id, prepared.tool_name, prepared.raw_arguments, risk
        )
        await self._events.append(
            run_id,
            EventType.APPROVAL_REQUESTED,
            {
                "approval_id": record.id,
                "tool": prepared.tool_name,
                "args": prepared.raw_arguments,
                "risk": str(risk),
                "prompt": approval_prompt(agent, prepared),
                "summary": prepared.summary,
                "automatic": True,
            },
            agent_id=agent,
        )
        settled = await self._store.settle(record.id, ApprovalStatus.APPROVED)
        await self._events.append(
            run_id,
            EventType.APPROVAL_RESOLVED,
            {
                "approval_id": settled.id,
                "tool": prepared.tool_name,
                "status": str(settled.status),
                "automatic": True,
            },
            agent_id=agent,
        )
        return ApprovalDecision(
            allowed=True,
            status=ApprovalStatus.APPROVED,
            reason=(
                f"{risk} risk calls are pre-approved in this workspace, so this "
                f"ran without asking."
            ),
            approval_id=settled.id,
            automatic=True,
        )

    async def _deny_by_precedent(
        self,
        run_id: str,
        agent: str,
        prepared: Prepared,
        risk: RiskLevel,
        precedent: ApprovalRecord,
    ) -> ApprovalDecision:
        """Deny a call the user already denied in this run, and say so.

        Written and emitted like an automatic approval, for the same reason:
        the history has to show that the question came up again and how it
        was settled, and the dialog must never show a question nobody is
        being asked. ``precedent`` names the decision this one rests on.
        """
        record = await self._store.create(
            run_id, prepared.tool_name, prepared.raw_arguments, risk
        )
        await self._events.append(
            run_id,
            EventType.APPROVAL_REQUESTED,
            {
                "approval_id": record.id,
                "tool": prepared.tool_name,
                "args": prepared.raw_arguments,
                "risk": str(risk),
                "prompt": approval_prompt(agent, prepared),
                "summary": prepared.summary,
                "automatic": True,
                "precedent": precedent.id,
            },
            agent_id=agent,
        )
        settled = await self._store.settle(record.id, ApprovalStatus.DENIED)
        await self._events.append(
            run_id,
            EventType.APPROVAL_RESOLVED,
            {
                "approval_id": settled.id,
                "tool": prepared.tool_name,
                "status": str(settled.status),
                "automatic": True,
                "precedent": precedent.id,
            },
            agent_id=agent,
        )
        return ApprovalDecision(
            allowed=False,
            status=ApprovalStatus.DENIED,
            reason=(
                f"The user already denied permission to {prepared.summary} "
                f"earlier in this run, so it was not asked again. Do not try "
                f"this call again: continue without it, or finish and say what "
                f"you could not do."
            ),
            approval_id=settled.id,
            automatic=True,
        )

    async def release_run(self, run_id: str) -> int:
        """Settle every pending question of a cancelled run as expired.

        The gate borrows the run's wall clock, so an agent blocked on it would
        otherwise notice a cancel only when the approval expired, ten minutes
        by default. The rows are settled as `expired` (§4's `approvals.status`
        has no `cancelled`, and a fifth value would be a migration for no
        reader) and the waiters are woken with that answer; the denial that
        follows says the run was cancelled rather than blaming the clock.
        Tolerates the race where a person answered in the last instant.
        """
        self._released.add(run_id)
        released = 0
        for record in await self._store.list_pending(run_id):
            try:
                await self._store.settle(record.id, ApprovalStatus.EXPIRED)
            except ApprovalNotPendingError:
                continue
            waiter = self._waiters.get(record.id)
            if waiter is not None and not waiter.done():
                waiter.set_result(ApprovalStatus.EXPIRED)
            released += 1
        return released

    async def _wait(self, approval_id: str, deadline: float | None) -> ApprovalStatus:
        """Block until resolved, or until the run's deadline passes."""
        loop = asyncio.get_running_loop()
        future: asyncio.Future[ApprovalStatus] = loop.create_future()
        self._waiters[approval_id] = future

        try:
            if deadline is None:
                return await future

            # One wait, not a poll loop. `deadline` is the run's remaining
            # budget measured once by the caller, so slicing it into intervals
            # would wake the loop hundreds of times to arrive at the same
            # instant. Nothing is being watched for in between: the future is
            # set by `resolve`, from an HTTP handler, not by a clock.
            #
            # `shield` so that the timeout cancels *this* wait and not the
            # future itself: `resolve` may be setting a result at the very
            # moment the deadline lands, and a cancelled future would turn that
            # into a `CancelledError` instead of the decision a person made.
            try:
                return await asyncio.wait_for(asyncio.shield(future), timeout=deadline)
            except TimeoutError:
                pass

            # Out of time. Settle the row so it does not sit pending forever,
            # tolerating the race where a human resolved it in the last instant.
            try:
                await self._store.settle(approval_id, ApprovalStatus.EXPIRED)
            except ApprovalNotPendingError:
                if future.done():
                    return future.result()
                record = await self._store.get(approval_id)
                if record is not None:
                    return record.status
            return ApprovalStatus.EXPIRED
        finally:
            self._waiters.pop(approval_id, None)

    async def resolve(self, approval_id: str, *, approved: bool) -> ApprovalRecord:
        """Settle an approval and wake whatever is waiting on it.

        The row is updated first. If the write fails because somebody already
        resolved it, no future is woken and the caller gets the conflict, which
        is the right order: the durable state decides, and the in-memory waiter
        follows it.

        :raises ApprovalNotPendingError: unknown, or already settled.
        """
        status = ApprovalStatus.APPROVED if approved else ApprovalStatus.DENIED
        record = await self._store.settle(approval_id, status)

        waiter = self._waiters.get(approval_id)
        if waiter is not None and not waiter.done():
            waiter.set_result(status)

        return record
