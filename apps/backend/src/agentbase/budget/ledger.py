"""Monthly spending cap: check before calls, record afterward (§5 Phase 3).

:class:`BudgetedProvider` enforces the check structurally by matching its
wrapped provider protocol, so a call site cannot bypass it. The pre-flight
estimate assumes ``max_tokens`` to refuse early; recorded spend uses provider-
reported usage.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from dataclasses import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final

from agentbase.events.types import EventType
from agentbase.providers.base import Completion, TokenUsage
from agentbase.providers.pricing import (
    UnknownModelError,
    cost_micros,
    format_micros,
    is_priced,
)

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import AsyncIterator

    from agentbase.events.store import EventStore
    from agentbase.providers.base import Message, Provider, StreamEvent, ToolSpec
    from agentbase.store.db import Database
    from agentbase.store.settings import SettingsStore

__all__ = [
    "WARNING_THRESHOLD_PERCENT",
    "BudgetExceededError",
    "BudgetLedger",
    "BudgetedProvider",
    "current_period",
    "estimate_usage",
]

#: Percent of the cap at which `budget.warning` fires.
WARNING_THRESHOLD_PERCENT: Final[int] = 80

#: Pre-flight characters-per-token estimate. Intentionally below English's
#: roughly four characters, so estimates err toward refusal.
_CHARS_PER_TOKEN: Final[int] = 3


class BudgetExceededError(RuntimeError):
    """Raised before a cap-breaching call; ``reason`` is user-facing."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def current_period(now: datetime | None = None) -> str:
    """Return the UTC ``YYYY-MM`` spend bucket, whose boundary cannot travel."""
    moment = now or datetime.now(UTC)
    return f"{moment.year:04d}-{moment.month:02d}"


def estimate_usage(
    messages: list[Message],
    max_tokens: int,
    system: str | None = None,
) -> TokenUsage:
    """Estimate a pessimistic request-cost upper bound.

    Use characters, not a tokenizer that would require the network call this
    guard avoids. An assistant turn's calls are resent with it, so a written
    file's content counts again on every later request.
    """
    characters = sum(
        len(message.content)
        + sum(
            len(call.name) + len(json.dumps(call.arguments, default=str))
            for call in message.tool_calls
        )
        for message in messages
    )
    if system:
        characters += len(system)

    return TokenUsage(
        input_tokens=-(-characters // _CHARS_PER_TOKEN),
        output_tokens=max_tokens,
    )


class BudgetLedger:
    """Record spend and enforce the monthly cap."""

    def __init__(
        self,
        db: Database,
        settings: SettingsStore,
        events: EventStore | None = None,
    ) -> None:
        self._db = db
        self._settings = settings
        self._events = events

    # --- reading -----------------------------------------------------------

    async def spent_micros(
        self, period: str | None = None, *, space_id: str | None = None
    ) -> int:
        """Return period spend in micros; ``space_id`` filters through ``runs``."""
        return await asyncio.to_thread(
            self._spent_micros_sync, period or current_period(), space_id
        )

    def _spent_micros_sync(self, period: str, space_id: str | None) -> int:
        with self._db.read() as connection:
            if space_id is None:
                row = connection.execute(
                    "SELECT COALESCE(SUM(cost_micros), 0) AS total FROM spend WHERE period = ?",
                    (period,),
                ).fetchone()
            else:
                row = connection.execute(
                    "SELECT COALESCE(SUM(spend.cost_micros), 0) AS total FROM spend"
                    " JOIN runs ON runs.id = spend.run_id"
                    " WHERE spend.period = ? AND runs.space_id = ?",
                    (period, space_id),
                ).fetchone()
        return int(row["total"])

    async def run_spent_micros(self, run_id: str) -> int:
        """Return a run's total spend in micros across all periods."""
        return await asyncio.to_thread(self._run_spent_micros_sync, run_id)

    def _run_spent_micros_sync(self, run_id: str) -> int:
        with self._db.read() as connection:
            row = connection.execute(
                "SELECT COALESCE(SUM(cost_micros), 0) AS total FROM spend WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        return int(row["total"])

    async def cap_micros(self) -> int:
        settings = await self._settings.get()
        return settings.monthly_cap_micros

    # --- the gate ----------------------------------------------------------

    async def check(self, run_id: str, model: str, projected: TokenUsage) -> None:
        """Refuse a projected call that breaches this month's cap.

        Emit ``budget.exceeded`` on refusal.

        :raises BudgetExceededError: with a user-facing reason.
        """
        cap = await self.cap_micros()

        if not is_priced(model):
            # An unpriced model cannot be checked against the cap.
            reason = (
                f"Refusing to call {model!r}: it has no registered price, so its cost "
                f"cannot be counted against the monthly budget. Add it to pricing.py."
            )
            await self._emit_exceeded(run_id, reason, spent=None, cap=cap)
            raise BudgetExceededError(reason)

        spent = await self.spent_micros()
        projected_cost = cost_micros(model, projected)

        if spent + projected_cost > cap:
            reason = (
                f"This call would exceed the monthly budget. "
                f"Spent {format_micros(spent)} of {format_micros(cap)} this month; "
                f"this call could add up to {format_micros(projected_cost)}. "
                f"Raise the monthly cap in settings to continue."
            )
            await self._emit_exceeded(run_id, reason, spent=spent, cap=cap)
            raise BudgetExceededError(reason)

    # --- recording ---------------------------------------------------------

    async def record(
        self,
        run_id: str | None,
        provider: str,
        model: str,
        usage: TokenUsage,
    ) -> int:
        """Record actual spend and return its micros cost.

        :raises UnknownModelError: if the model has no price; write nothing.
        """
        cost = cost_micros(model, usage)  # raises before any row is written
        period = current_period()

        before, after = await asyncio.to_thread(
            self._record_sync, run_id, period, provider, model, usage, cost
        )

        await self._maybe_warn(run_id, before, after)
        return cost

    def _record_sync(
        self,
        run_id: str | None,
        period: str,
        provider: str,
        model: str,
        usage: TokenUsage,
        cost: int,
    ) -> tuple[int, int]:
        """Insert a row and return period totals before and after it.

        Read both inside one write transaction, so concurrent runs yield one
        threshold crossing.
        """
        with self._db.write() as connection:
            before = self._period_total(connection, period)
            connection.execute(
                "INSERT INTO spend (run_id, period, provider, model, input_tokens,"
                " output_tokens, cost_micros, ts) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    period,
                    provider,
                    model,
                    usage.input_tokens,
                    usage.output_tokens,
                    cost,
                    datetime.now(UTC).isoformat(),
                ),
            )
            after = self._period_total(connection, period)
        return before, after

    @staticmethod
    def _period_total(connection: sqlite3.Connection, period: str) -> int:
        row = connection.execute(
            "SELECT COALESCE(SUM(cost_micros), 0) AS total FROM spend WHERE period = ?",
            (period,),
        ).fetchone()
        return int(row["total"])

    # --- events ------------------------------------------------------------

    async def _maybe_warn(self, run_id: str | None, before: int, after: int) -> None:
        """Emit ``budget.warning`` only for the call crossing the threshold."""
        if run_id is None or self._events is None:
            return

        cap = await self.cap_micros()
        if cap <= 0:
            return

        threshold = cap * WARNING_THRESHOLD_PERCENT // 100
        if before < threshold <= after:
            await self._events.append(
                run_id,
                EventType.BUDGET_WARNING,
                {
                    "spent_micros": after,
                    "cap_micros": cap,
                    "percent": min(100, after * 100 // cap),
                    "reason": (
                        f"Used {format_micros(after)} of the {format_micros(cap)} "
                        f"monthly budget."
                    ),
                },
            )

    async def _emit_exceeded(
        self, run_id: str | None, reason: str, spent: int | None, cap: int
    ) -> None:
        if run_id is None or self._events is None:
            return

        payload: dict[str, Any] = {"reason": reason, "cap_micros": cap}
        if spent is not None:
            payload["spent_micros"] = spent

        await self._events.append(run_id, EventType.BUDGET_EXCEEDED, payload)


class BudgetedProvider:
    """A :class:`~agentbase.providers.base.Provider` constrained by the cap."""

    def __init__(self, inner: Provider, ledger: BudgetLedger, run_id: str | None) -> None:
        self._inner = inner
        self._ledger = ledger
        self._run_id = run_id

    @property
    def name(self) -> str:
        return self._inner.name

    @property
    def model(self) -> str:
        return self._inner.model

    async def complete(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        *,
        system: str | None = None,
        max_tokens: int = 4096,
    ) -> Completion:
        """Always check, call, then record."""
        projected = estimate_usage(messages, max_tokens=max_tokens, system=system)

        if self._run_id is not None:
            await self._ledger.check(self._run_id, self._inner.model, projected)
        else:
            # No run receives the refusal, but the cap still applies.
            await self._ledger.check("", self._inner.model, projected)

        completion = await self._inner.complete(
            messages, tools, system=system, max_tokens=max_tokens
        )

        cost = await self._ledger.record(
            run_id=self._run_id,
            provider=completion.provider,
            model=completion.model,
            usage=completion.usage,
        )
        return replace(completion, cost_micros=cost)

    async def stream(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        *,
        system: str | None = None,
        max_tokens: int = 4096,
    ) -> AsyncIterator[StreamEvent]:
        """Always check, stream, then record.

        Record before yielding completion: a consumer may stop then and close
        an otherwise unbilled generator.
        """
        projected = estimate_usage(messages, max_tokens=max_tokens, system=system)

        if self._run_id is not None:
            await self._ledger.check(self._run_id, self._inner.model, projected)
        else:
            await self._ledger.check("", self._inner.model, projected)

        events = self._inner.stream(messages, tools, system=system, max_tokens=max_tokens)
        try:
            async for event in events:
                if isinstance(event, Completion):
                    cost = await self._ledger.record(
                        run_id=self._run_id,
                        provider=event.provider,
                        model=event.model,
                        usage=event.usage,
                    )
                    yield replace(event, cost_micros=cost)
                    continue
                yield event
        finally:
            # Propagate early closure through wrappers so the transport can
            # release its connection and its shared ChatGPT request permit.
            if isinstance(events, AsyncGenerator):
                await events.aclose()


# Re-exported so callers catching budget failures need one import.
UnknownModelError = UnknownModelError
