"""The monthly spending cap.

§5 Phase 3: "Check *before* each call, record *after*. Emit `budget.warning` at
80%, `budget.exceeded` and refuse at 100%."

**Why the guard is a wrapper and not a convention.** The check could have been
a function the orchestrator is expected to call first. That kind of rule holds
right up until someone adds a second call site — and the failure is silent and
expensive, because the evidence is a provider invoice rather than a stack
trace. :class:`BudgetedProvider` implements the same protocol as the thing it
wraps, so the only way to reach the model is through the check. Phase 4 cannot
forget to call it, because there is nothing else to call.

**The estimate is pessimistic on purpose.** A pre-flight check has to guess the
cost of a response that has not happened yet. It assumes the model returns
`max_tokens` — the most it is permitted to — so the guard refuses early rather
than late. What gets *recorded* afterwards is the provider's own reported
usage, never the estimate.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final

from agentspace.events.types import EventType
from agentspace.providers.base import Completion, TokenUsage
from agentspace.providers.pricing import (
    UnknownModelError,
    cost_micros,
    format_micros,
    is_priced,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from agentspace.events.store import EventStore
    from agentspace.providers.base import Message, Provider, StreamEvent, ToolSpec
    from agentspace.store.db import Database
    from agentspace.store.settings import SettingsStore

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

#: Rough characters per token. Used only to size the pre-flight estimate, never
#: to charge: the real count comes back from the provider. Deliberately low
#: (real English is nearer 4) so the estimate errs towards refusing early.
_CHARS_PER_TOKEN: Final[int] = 3


class BudgetExceededError(RuntimeError):
    """Raised instead of making a call that would breach the monthly cap.

    Carries a human-legible reason: it is surfaced to the user more or less
    verbatim, so it must read as prose rather than as a serialized object.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def current_period(now: datetime | None = None) -> str:
    """The `YYYY-MM` bucket §4 stores spend under. UTC, so the boundary does
    not move with the user's timezone or their travel."""
    moment = now or datetime.now(UTC)
    return f"{moment.year:04d}-{moment.month:02d}"


def estimate_usage(
    messages: list[Message],
    max_tokens: int,
    system: str | None = None,
) -> TokenUsage:
    """A deliberately pessimistic upper bound on what a request will cost.

    Not a tokenizer. Each provider tokenizes differently and none of them will
    tell us the count without being asked over the network — which is the very
    call we are trying to avoid making. A character heuristic is enough for a
    guard whose only job is to decide "is there room for this at all".
    """
    characters = sum(len(message.content) for message in messages)
    if system:
        characters += len(system)

    return TokenUsage(
        input_tokens=-(-characters // _CHARS_PER_TOKEN),
        output_tokens=max_tokens,
    )


class BudgetLedger:
    """Records spend and enforces the monthly cap."""

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
        """Total recorded spend for a period, in micros.

        ``space_id`` narrows it to the runs of one space, by joining `spend`
        to `runs` — `spend` itself carries no space, because a run knows its
        space and a second column would be a second place for the answer to
        live (§5 Phase 11).
        """
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

    async def cap_micros(self) -> int:
        settings = await self._settings.get()
        return settings.monthly_cap_micros

    # --- the gate ----------------------------------------------------------

    async def check(self, run_id: str, model: str, projected: TokenUsage) -> None:
        """Refuse if ``projected`` on ``model`` would breach this month's cap.

        Called before the request leaves the machine. Emits `budget.exceeded`
        on refusal so the UI learns why the run stopped from the event log,
        like everything else (§2).

        :raises BudgetExceededError: with a reason fit to show a user.
        """
        cap = await self.cap_micros()

        if not is_priced(model):
            # An unpriced model cannot be checked against a cap. Letting it
            # through would make the cap meaningless for exactly the models we
            # know least about.
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
        """Record actual spend and return what it cost, in micros.

        :raises UnknownModelError: if the model has no price. Recording zero
            for an unknown model would corrupt the cap silently, so this fails
            loudly instead — and writes nothing.
        """
        cost = cost_micros(model, usage)  # raises before any row is written
        period = current_period()

        before = await self.spent_micros(period)
        await asyncio.to_thread(self._record_sync, run_id, period, provider, model, usage, cost)
        after = before + cost

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
    ) -> None:
        with self._db.write() as connection:
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

    # --- events ------------------------------------------------------------

    async def _maybe_warn(self, run_id: str | None, before: int, after: int) -> None:
        """Emit `budget.warning` on the call that crosses 80%, and only then.

        Comparing before and after makes this fire once per period rather than
        once per call for the rest of the month. The event log is the UI's only
        input, so a warning repeated on every subsequent call would drown it.
        """
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
    """A :class:`~agentspace.providers.base.Provider` that cannot outspend the cap.

    Implements the same protocol as the provider it wraps, so nothing above it
    knows the difference — which is what makes the check impossible to skip.
    """

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
        """Check, call, record — in that order, always."""
        projected = estimate_usage(messages, max_tokens=max_tokens, system=system)

        if self._run_id is not None:
            await self._ledger.check(self._run_id, self._inner.model, projected)
        else:
            # No run to attribute the refusal to, but the cap still binds.
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
        """Check, stream, record — in that order, always.

        Wrapping this method is not optional. The orchestrator streams by
        default, so a `BudgetedProvider` that guarded only `complete` would
        leave the cap binding nothing that actually runs, while every existing
        test kept passing.

        **Spend is recorded before the terminal completion is yielded, not
        after.** A consumer that stops iterating the moment it has the
        completion — an entirely reasonable thing to write — would otherwise
        close the generator before the recording line ever ran, and the call
        would go unbilled.
        """
        projected = estimate_usage(messages, max_tokens=max_tokens, system=system)

        if self._run_id is not None:
            await self._ledger.check(self._run_id, self._inner.model, projected)
        else:
            await self._ledger.check("", self._inner.model, projected)

        async for event in self._inner.stream(
            messages, tools, system=system, max_tokens=max_tokens
        ):
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


# Re-exported so callers catching budget failures need one import.
UnknownModelError = UnknownModelError
