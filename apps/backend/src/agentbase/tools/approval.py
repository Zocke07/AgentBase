"""The human-in-the-loop gate between an agent and the disk (§1 constraint 5).

:meth:`ApprovalService.request` writes a row, emits `approval.requested`, and
suspends the calling agent on an `asyncio.Future` until somebody resolves it
over HTTP. Nothing polls and the agent never sees a "pending" reply it could
reason around: one code path from "the agent asked" to "the tool ran", with a
decision in the middle.

Approved and denied come from a person. An auto-approval from policy is
recorded all the same, so the log can say why a call proceeded without a
dialog. Expired covers a run that outlived its deadline while waiting, and a
restart, after which no waiter exists to be woken. A definition's
`auto_approve` can only narrow the workspace policy, never widen it.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from agentbase.events.types import EventType
from agentbase.tools.catalogue import RiskLevel, ToolPolicy

if TYPE_CHECKING:
    from collections.abc import Iterable

    from agentbase.events.store import EventStore
    from agentbase.store.db import Database
    from agentbase.tools.base import Prepared

__all__ = [
    "ApprovalDecision",
    "ApprovalNotPendingError",
    "ApprovalRecord",
    "ApprovalScope",
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


class ApprovalScope(StrEnum):
    """How far a person's answer reaches: this one call, or every call to
    the tool for the rest of the run."""

    CALL = "call"
    RUN = "run"


class ApprovalNotPendingError(Exception):
    """Resolving an approval that is already settled or unknown: a 409 on a row that exists."""


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
    scope: ApprovalScope = ApprovalScope.CALL


@dataclass(frozen=True, slots=True)
class ApprovalDecision:
    """What the gate concluded, and why. ``automatic`` marks a policy's yes, not a person's."""

    allowed: bool
    status: ApprovalStatus
    reason: str
    approval_id: str | None = None
    automatic: bool = False


def approval_prompt(agent: str, prepared: Prepared) -> str:
    """The sentence a human is asked to judge.

    Built from :attr:`~agentbase.tools.base.Prepared.summary`, the resolved
    call, so it describes the call that would run rather than the arguments
    the model typed.
    """
    return f'Agent "{agent}" wants to {prepared.summary}'


class ApprovalStore:
    """The `approvals` table: current state. The history is in the event log."""

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

        Matched on the tool and the arguments as the model sent them, compared
        as parsed objects so JSON key order does not decide it.
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

    async def find_allowed_for_run(self, run_id: str, tool: str) -> ApprovalRecord | None:
        """The earliest yes in this run that was given for the whole run, for this tool."""
        return await asyncio.to_thread(self._find_allowed_for_run_sync, run_id, tool)

    def _find_allowed_for_run_sync(self, run_id: str, tool: str) -> ApprovalRecord | None:
        with self._db.read() as connection:
            row = connection.execute(
                "SELECT * FROM approvals WHERE run_id = ? AND tool = ? AND status = ?"
                " AND scope = ? ORDER BY created_at, rowid LIMIT 1",
                (run_id, tool, str(ApprovalStatus.APPROVED), str(ApprovalScope.RUN)),
            ).fetchone()
        return _record(row) if row is not None else None

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

    async def settle(
        self,
        approval_id: str,
        status: ApprovalStatus,
        scope: ApprovalScope = ApprovalScope.CALL,
    ) -> ApprovalRecord:
        """Move a pending approval to a terminal status.

        Conditional on the row still being pending, in one statement, so two
        concurrent resolutions cannot both succeed. ``scope`` is recorded with
        a yes so the gate can find it again for the rest of the run.

        :raises ApprovalNotPendingError: unknown, or already settled.
        """
        return await asyncio.to_thread(self._settle_sync, approval_id, status, scope)

    def _settle_sync(
        self, approval_id: str, status: ApprovalStatus, scope: ApprovalScope
    ) -> ApprovalRecord:
        resolved_at = datetime.now(UTC).isoformat()
        with self._db.write() as connection:
            cursor = connection.execute(
                "UPDATE approvals SET status = ?, resolved_at = ?, scope = ?"
                " WHERE id = ? AND status = ?",
                (
                    str(status),
                    resolved_at,
                    str(scope),
                    approval_id,
                    str(ApprovalStatus.PENDING),
                ),
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

        Called once at startup: a pending row's waiter died with the process
        that created it, so nothing can answer it now. Returns how many closed.
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
        scope=ApprovalScope(row["scope"]),
    )


class ApprovalService:
    """Creates approvals, blocks on them, and resolves them.

    One instance per application: the agent awaits the future inside a run
    and a separate HTTP request (`POST /approvals/{id}`) sets it.
    """

    def __init__(self, store: ApprovalStore, events: EventStore) -> None:
        self._store = store
        self._events = events
        self._waiters: dict[str, asyncio.Future[ApprovalStatus]] = {}
        #: Runs whose pending questions a cancel released, so the denial can say so.
        self._released: set[str] = set()

    @property
    def store(self) -> ApprovalStore:
        return self._store

    @property
    def pending_count(self) -> int:
        """How many approvals this process is currently blocked on."""
        return len(self._waiters)

    def waiting_on(self) -> tuple[str, ...]:
        """The ids this process is currently suspended on (what it can still answer)."""
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
        policy: ToolPolicy = ToolPolicy.ASK,
    ) -> ApprovalDecision:
        """Obtain a decision for one prepared call, blocking if a human is needed.

        :param auto_approve: the already-intersected policy (see
            :func:`~agentbase.tools.catalogue.effective_auto_approve`); the
            narrowing rule has one implementation and it is not here.
        :param deadline: seconds this may block before expiring, normally the
            run's remaining wall-clock budget. ``None`` waits indefinitely.
        :param policy: the per-tool answer, already narrowed by the definition
            (:meth:`~agentbase.tools.runtime.ToolRuntime.policy_for`). It is
            read before the risk level: a refusal is a refusal whatever the
            level, and an allowance runs the call unasked.
        """
        if policy is ToolPolicy.DENY:
            return await self._deny_by_policy(run_id, agent, prepared, risk)
        if policy is ToolPolicy.ALLOW or risk in frozenset(auto_approve):
            return await self._auto_approve(run_id, agent, prepared, risk)

        # A denial sticks for the run: the same call from any agent is denied
        # by the earlier answer, so a person is not asked the same question
        # for as long as the step limit and the agent cap allow.
        precedent = await self._store.find_denied(
            run_id, prepared.tool_name, prepared.raw_arguments
        )
        if precedent is not None:
            return await self._deny_by_precedent(run_id, agent, prepared, risk, precedent)

        # A yes given for the run sticks too, for every call to that tool:
        # the person said not to ask again about it, and is not asked.
        allowance = await self._store.find_allowed_for_run(run_id, prepared.tool_name)
        if allowance is not None:
            return await self._allow_by_precedent(run_id, agent, prepared, risk, allowance)

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
                # The sentence travels in the log so no client composes its own.
                "prompt": approval_prompt(agent, prepared),
                "summary": prepared.summary,
            },
            agent_id=agent,
        )

        status = await self._wait(record.id, deadline)

        # The settled row carries how far the answer reaches; the log says so.
        settled = await self._store.get(record.id)
        scope = settled.scope if settled is not None else ApprovalScope.CALL
        await self._events.append(
            run_id,
            EventType.APPROVAL_RESOLVED,
            {
                "approval_id": record.id,
                "tool": prepared.tool_name,
                "status": str(status),
                "automatic": False,
                **({"scope": str(scope)} if scope is ApprovalScope.RUN else {}),
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

        A row is still written and both events still emitted: "what did this
        run do without asking me" is answered from exactly these rows.
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

    async def _deny_by_policy(
        self, run_id: str, agent: str, prepared: Prepared, risk: RiskLevel
    ) -> ApprovalDecision:
        """Refuse a call to a tool the policy never allows, and say so.

        Recorded like an automatic approval, so "what did the policy refuse"
        is answered from the same rows, and marked as the policy's doing.
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
                "policy": str(ToolPolicy.DENY),
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
                "policy": str(ToolPolicy.DENY),
            },
            agent_id=agent,
        )
        return ApprovalDecision(
            allowed=False,
            status=ApprovalStatus.DENIED,
            reason=(
                f"The app's policy never allows {prepared.tool_name}, so the request "
                f"to {prepared.summary} was refused without asking. Do not try this "
                f"tool again: continue without it, or finish and say what you could "
                f"not do."
            ),
            approval_id=record.id,
        )

    async def _allow_by_precedent(
        self,
        run_id: str,
        agent: str,
        prepared: Prepared,
        risk: RiskLevel,
        precedent: ApprovalRecord,
    ) -> ApprovalDecision:
        """Allow a call to a tool the user allowed for the rest of this run."""
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
        settled = await self._store.settle(record.id, ApprovalStatus.APPROVED)
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
            allowed=True,
            status=ApprovalStatus.APPROVED,
            reason=(
                f"The user allowed {prepared.tool_name} for the rest of this run, "
                f"so this call ran without asking again."
            ),
            approval_id=record.id,
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

        Recorded like an automatic approval, marked with the ``precedent`` it
        rests on, so the history shows the question came up again.
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

        Otherwise an agent blocked on the gate notices a cancel only when the
        approval expires. `expired` because §4 has no `cancelled` status; the
        denial that follows says the run was cancelled. Tolerates a person
        answering in the last instant.
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

            # `shield` so the timeout cancels this wait and not the future:
            # `resolve` may set a result at the instant the deadline lands.
            try:
                return await asyncio.wait_for(asyncio.shield(future), timeout=deadline)
            except TimeoutError:
                pass

            # Out of time. Settle the row, tolerating a last-instant answer.
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

    async def resolve(
        self,
        approval_id: str,
        *,
        approved: bool,
        scope: ApprovalScope = ApprovalScope.CALL,
    ) -> ApprovalRecord:
        """Settle an approval and wake whatever is waiting on it.

        The row is updated first; the durable state decides and the in-memory
        waiter follows it. A yes with ``scope`` ``RUN`` also answers every
        later call to the tool in this run; a no is for this call and its
        arguments, as before, and a no cannot be given for a run.

        :raises ApprovalNotPendingError: unknown, or already settled.
        """
        status = ApprovalStatus.APPROVED if approved else ApprovalStatus.DENIED
        record = await self._store.settle(
            approval_id, status, scope if approved else ApprovalScope.CALL
        )

        waiter = self._waiters.get(approval_id)
        if waiter is not None and not waiter.done():
            waiter.set_result(status)

        return record
