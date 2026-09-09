"""Tests for the monthly budget cap.

Written before `budget/ledger.py` (BUILD_SPEC §6).

The Phase 3 acceptance criterion is precise about ordering: "a run that would
exceed the monthly cap is refused with a clear reason **before any API call
fires**." A test that only checks the error message would pass just as happily
if the request went out first and the refusal came after — the user would be
billed for a call the app claims it prevented.

So the provider double here raises if it is called at all. Every refusal test
asserts both that the refusal happened *and* that the double was never
invoked. That is the only way the ordering is actually pinned.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from agentspace.budget.ledger import (
    BudgetedProvider,
    BudgetExceededError,
    BudgetLedger,
    current_period,
    estimate_usage,
)
from agentspace.events.types import EventType
from agentspace.providers.base import Completion, Message, Role, TokenUsage, ToolSpec
from agentspace.store.settings import SettingsStore

if TYPE_CHECKING:
    from agentspace.events.store import EventStore
    from agentspace.store.db import Database

pytestmark = pytest.mark.anyio


# --- doubles -----------------------------------------------------------------


class ExplodingProvider:
    """A provider that fails the test if it is ever called.

    This is the whole point of the suite: it makes "refused before the API
    call" a property the tests can actually observe, rather than something the
    implementation is trusted to do in the right order.
    """

    name = "exploding"
    model = "claude-opus-5"

    def __init__(self) -> None:
        self.calls = 0

    async def complete(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        *,
        system: str | None = None,
        max_tokens: int = 4096,
    ) -> Completion:
        self.calls += 1
        msg = "the API call fired despite the budget cap — this is the bug"
        raise AssertionError(msg)


class StubProvider:
    """A provider that succeeds and reports a fixed usage."""

    name = "stub"

    def __init__(self, model: str = "claude-opus-5", usage: TokenUsage | None = None) -> None:
        self.model = model
        self.calls = 0
        self._usage = usage or TokenUsage(input_tokens=1_000, output_tokens=500)

    async def complete(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        *,
        system: str | None = None,
        max_tokens: int = 4096,
    ) -> Completion:
        self.calls += 1
        return Completion(
            provider=self.name,
            model=self.model,
            text="ok",
            usage=self._usage,
            stop_reason="end_turn",
        )


@pytest.fixture
def settings(db: Database) -> SettingsStore:
    return SettingsStore(db)


@pytest.fixture
def ledger(db: Database, store: EventStore, settings: SettingsStore) -> BudgetLedger:
    return BudgetLedger(db, settings, store)


async def _run_id(store: EventStore) -> str:
    run = await store.create_run(goal="budget test")
    return run.id


# --- the period --------------------------------------------------------------


async def test_current_period_is_a_utc_year_month() -> None:
    """§4: `period TEXT NOT NULL -- 'YYYY-MM'`."""
    period = current_period()

    assert len(period) == 7
    assert period[4] == "-"
    year, month = period.split("-")
    assert year.isdigit() and month.isdigit()
    assert 1 <= int(month) <= 12


# --- recording ---------------------------------------------------------------


async def test_record_writes_a_spend_row_with_integer_micros(
    ledger: BudgetLedger, store: EventStore, db: Database
) -> None:
    run_id = await _run_id(store)

    cost = await ledger.record(
        run_id=run_id,
        provider="anthropic",
        model="claude-opus-5",
        usage=TokenUsage(input_tokens=1_000_000, output_tokens=0),
    )

    assert cost == 5_000_000

    with db.read() as connection:
        row = connection.execute("SELECT * FROM spend").fetchone()

    assert row["cost_micros"] == 5_000_000
    assert type(row["cost_micros"]) is int
    assert row["input_tokens"] == 1_000_000
    assert row["output_tokens"] == 0
    assert row["provider"] == "anthropic"
    assert row["model"] == "claude-opus-5"
    assert row["run_id"] == run_id
    assert row["period"] == current_period()


async def test_spent_micros_sums_the_current_period(
    ledger: BudgetLedger, store: EventStore
) -> None:
    run_id = await _run_id(store)
    usage = TokenUsage(input_tokens=100_000, output_tokens=0)

    assert await ledger.spent_micros() == 0

    await ledger.record(run_id=run_id, provider="anthropic", model="claude-opus-5", usage=usage)
    await ledger.record(run_id=run_id, provider="anthropic", model="claude-opus-5", usage=usage)

    assert await ledger.spent_micros() == 1_000_000


async def test_spend_from_another_period_does_not_count(
    ledger: BudgetLedger, store: EventStore, db: Database
) -> None:
    """A monthly cap that summed all history would refuse forever."""
    run_id = await _run_id(store)

    with db.write() as connection:
        connection.execute(
            "INSERT INTO spend (run_id, period, provider, model, input_tokens,"
            " output_tokens, cost_micros, ts) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (run_id, "2000-01", "anthropic", "claude-opus-5", 1, 1, 999_000_000, "2000-01-01"),
        )

    assert await ledger.spent_micros() == 0


async def test_recording_an_unpriced_model_raises_rather_than_recording_zero(
    ledger: BudgetLedger, store: EventStore, db: Database
) -> None:
    run_id = await _run_id(store)

    with pytest.raises(LookupError):
        await ledger.record(
            run_id=run_id,
            provider="anthropic",
            model="model-from-the-future",
            usage=TokenUsage(input_tokens=10),
        )

    with db.read() as connection:
        rows = connection.execute("SELECT COUNT(*) AS n FROM spend").fetchone()

    assert rows["n"] == 0


# --- the cap -----------------------------------------------------------------


async def test_check_passes_when_well_under_the_cap(
    ledger: BudgetLedger, store: EventStore
) -> None:
    run_id = await _run_id(store)

    await ledger.check(
        run_id=run_id, model="claude-opus-5", projected=TokenUsage(input_tokens=10)
    )


async def test_check_refuses_once_the_cap_is_reached(
    ledger: BudgetLedger, store: EventStore, settings: SettingsStore
) -> None:
    run_id = await _run_id(store)
    await settings.update({"monthly_cap_micros": 1_000_000})

    await ledger.record(
        run_id=run_id,
        provider="anthropic",
        model="claude-opus-5",
        usage=TokenUsage(input_tokens=200_000),
    )

    with pytest.raises(BudgetExceededError):
        await ledger.check(
            run_id=run_id, model="claude-opus-5", projected=TokenUsage(input_tokens=1)
        )


async def test_the_refusal_reason_is_human_legible(
    ledger: BudgetLedger, store: EventStore, settings: SettingsStore
) -> None:
    """§5 Phase 3: "refused with a clear reason". The user sees this string."""
    run_id = await _run_id(store)
    await settings.update({"monthly_cap_micros": 1_000_000})
    await ledger.record(
        run_id=run_id,
        provider="anthropic",
        model="claude-opus-5",
        usage=TokenUsage(input_tokens=200_000),
    )

    with pytest.raises(BudgetExceededError) as excinfo:
        await ledger.check(
            run_id=run_id, model="claude-opus-5", projected=TokenUsage(input_tokens=1)
        )

    message = str(excinfo.value)
    assert "$1.0000" in message
    assert "monthly" in message.lower()
    assert "{" not in message, "the reason must read as prose, not as a dict"


async def test_check_refuses_a_call_that_would_cross_the_cap(
    ledger: BudgetLedger, store: EventStore, settings: SettingsStore
) -> None:
    """ "Would exceed", not "has exceeded" — the projected cost of *this* call
    counts, otherwise the cap is always breached by one whole request."""
    run_id = await _run_id(store)
    await settings.update({"monthly_cap_micros": 1_000_000})

    with pytest.raises(BudgetExceededError):
        await ledger.check(
            run_id=run_id,
            model="claude-opus-5",
            projected=TokenUsage(input_tokens=1_000_000),  # $5.00, cap is $1.00
        )


async def test_an_unpriced_model_is_refused_before_the_call(
    ledger: BudgetLedger, store: EventStore
) -> None:
    """An unknown price cannot be checked against a cap, so it must refuse.

    Charging it at zero would let an unpriced model run unbounded — the exact
    hole `pricing.UnknownModelError` exists to close.
    """
    run_id = await _run_id(store)

    with pytest.raises((BudgetExceededError, LookupError)):
        await ledger.check(
            run_id=run_id, model="model-from-the-future", projected=TokenUsage(input_tokens=1)
        )


# --- events ------------------------------------------------------------------


async def test_budget_warning_is_emitted_at_eighty_percent(
    ledger: BudgetLedger, store: EventStore, settings: SettingsStore
) -> None:
    run_id = await _run_id(store)
    await settings.update({"monthly_cap_micros": 1_000_000})

    # $0.80 of a $1.00 cap.
    await ledger.record(
        run_id=run_id,
        provider="anthropic",
        model="claude-opus-5",
        usage=TokenUsage(input_tokens=160_000),
    )

    events = await store.read(run_id)
    types = [event.type for event in events]

    assert EventType.BUDGET_WARNING in types


async def test_budget_warning_is_not_emitted_below_the_threshold(
    ledger: BudgetLedger, store: EventStore, settings: SettingsStore
) -> None:
    run_id = await _run_id(store)
    await settings.update({"monthly_cap_micros": 1_000_000})

    await ledger.record(
        run_id=run_id,
        provider="anthropic",
        model="claude-opus-5",
        usage=TokenUsage(input_tokens=100_000),  # $0.50 — half the cap
    )

    events = await store.read(run_id)

    assert EventType.BUDGET_WARNING not in [event.type for event in events]


async def test_budget_warning_fires_once_per_crossing_not_once_per_call(
    ledger: BudgetLedger, store: EventStore, settings: SettingsStore
) -> None:
    """Warning on every call past 80% would bury the event log in duplicates —
    and the log is the UI's only source of truth."""
    run_id = await _run_id(store)
    await settings.update({"monthly_cap_micros": 1_000_000})
    usage = TokenUsage(input_tokens=160_000)  # $0.80 each

    await ledger.record(run_id=run_id, provider="a", model="claude-opus-5", usage=usage)
    await ledger.record(run_id=run_id, provider="a", model="claude-opus-5", usage=usage)

    events = await store.read(run_id)
    warnings = [e for e in events if e.type == EventType.BUDGET_WARNING]

    assert len(warnings) == 1


async def test_budget_exceeded_is_emitted_when_a_call_is_refused(
    ledger: BudgetLedger, store: EventStore, settings: SettingsStore
) -> None:
    run_id = await _run_id(store)
    await settings.update({"monthly_cap_micros": 1_000_000})

    with pytest.raises(BudgetExceededError):
        await ledger.check(
            run_id=run_id, model="claude-opus-5", projected=TokenUsage(input_tokens=1_000_000)
        )

    events = await store.read(run_id)
    exceeded = [e for e in events if e.type == EventType.BUDGET_EXCEEDED]

    assert len(exceeded) == 1
    assert "reason" in exceeded[0].payload


# --- the acceptance criterion ------------------------------------------------


async def test_a_run_over_cap_is_refused_before_any_api_call_fires(
    ledger: BudgetLedger, store: EventStore, settings: SettingsStore
) -> None:
    """BUILD_SPEC §5 Phase 3, acceptance criterion, second clause.

    `ExplodingProvider` turns "the call fired" into a test failure, so this
    asserts the *ordering*, not just that an exception was raised somewhere.
    """
    run_id = await _run_id(store)
    await settings.update({"monthly_cap_micros": 100})  # $0.0001
    inner = ExplodingProvider()
    guarded = BudgetedProvider(inner, ledger, run_id)

    with pytest.raises(BudgetExceededError):
        await guarded.complete([Message(role=Role.USER, content="hello" * 500)])

    assert inner.calls == 0, "the provider was called despite the cap"


async def test_a_permitted_call_reaches_the_provider_and_is_recorded(
    ledger: BudgetLedger, store: EventStore
) -> None:
    run_id = await _run_id(store)
    inner = StubProvider()
    guarded = BudgetedProvider(inner, ledger, run_id)

    result = await guarded.complete([Message(role=Role.USER, content="hi")])

    assert inner.calls == 1
    assert result.text == "ok"
    # 1000 in @ $5/M + 500 out @ $25/M = 5000 + 12500 micros.
    assert await ledger.spent_micros() == 17_500


async def test_the_recorded_cost_uses_actual_usage_not_the_estimate(
    ledger: BudgetLedger, store: EventStore
) -> None:
    """The pre-flight estimate is a deliberately pessimistic upper bound. If it
    were also what got charged, every run would over-report its own spend."""
    run_id = await _run_id(store)
    inner = StubProvider(usage=TokenUsage(input_tokens=10, output_tokens=10))
    guarded = BudgetedProvider(inner, ledger, run_id)

    await guarded.complete([Message(role=Role.USER, content="x" * 10_000)], max_tokens=100_000)

    # Actual usage is tiny; the estimate for that request was far larger.
    assert await ledger.spent_micros() == 300


async def test_the_guard_preserves_the_provider_protocol(
    ledger: BudgetLedger, store: EventStore
) -> None:
    """Wrapping must be invisible above this layer — the orchestrator (Phase 4)
    must not need to know whether it holds a provider or a guarded provider."""
    run_id = await _run_id(store)
    inner = StubProvider(model="claude-sonnet-5")
    guarded = BudgetedProvider(inner, ledger, run_id)

    assert guarded.name == inner.name
    assert guarded.model == inner.model


# --- estimation --------------------------------------------------------------


async def test_the_estimate_is_an_upper_bound_on_output_tokens() -> None:
    """`max_tokens` is the most the model can return, so it is the honest
    worst case for a pre-flight check."""
    estimate = estimate_usage([Message(role=Role.USER, content="hi")], max_tokens=4_096)

    assert estimate.output_tokens == 4_096


async def test_the_estimate_grows_with_the_prompt() -> None:
    small = estimate_usage([Message(role=Role.USER, content="hi")], max_tokens=100)
    large = estimate_usage([Message(role=Role.USER, content="hi" * 5_000)], max_tokens=100)

    assert large.input_tokens > small.input_tokens


async def test_the_estimate_counts_the_system_prompt() -> None:
    without = estimate_usage([Message(role=Role.USER, content="hi")], max_tokens=100)
    with_system = estimate_usage(
        [Message(role=Role.USER, content="hi")], max_tokens=100, system="a" * 4_000
    )

    assert with_system.input_tokens > without.input_tokens
