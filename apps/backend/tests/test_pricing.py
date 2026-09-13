"""Tests for per-model pricing, written before `pricing.py` (§6).

Two properties matter more than the numbers: no float ever touches money
(the type is asserted, not just the value), and an unknown model is an error,
not free.
"""

from __future__ import annotations

import pytest

from agentspace.providers.base import TokenUsage
from agentspace.providers.pricing import (
    MICROS_PER_DOLLAR,
    PRICES,
    ModelPrice,
    UnknownModelError,
    cost_micros,
    format_micros,
    is_priced,
)

# --- the money type ----------------------------------------------------------


def test_every_price_is_an_integer() -> None:
    """Not `isinstance(x, int)` alone: bool is an int subclass, and a float
    that happens to be whole would pass a value-equality check."""
    for model, price in PRICES.items():
        assert type(price.input_micros_per_million) is int, model
        assert type(price.output_micros_per_million) is int, model
        assert price.input_micros_per_million >= 0, model
        assert price.output_micros_per_million >= 0, model


def test_cost_is_always_an_integer_number_of_micros() -> None:
    usage = TokenUsage(input_tokens=1_234, output_tokens=567)

    for model in PRICES:
        cost = cost_micros(model, usage)
        assert type(cost) is int, model


def test_micros_per_dollar_is_one_million() -> None:
    """The unit the whole ledger is denominated in. §4: `cost_micros`."""
    assert MICROS_PER_DOLLAR == 1_000_000


# --- known prices ------------------------------------------------------------


def test_known_anthropic_prices() -> None:
    """Claude Opus 5 is $5.00 / $25.00 per million tokens."""
    price = PRICES["claude-opus-5"]

    assert price.input_micros_per_million == 5_000_000
    assert price.output_micros_per_million == 25_000_000


def test_a_fractional_dollar_price_stays_exact() -> None:
    """$2.50 and $0.05 per million are the cases a naive per-token integer
    conversion destroys: 2.5 and 0.05 micros per token are not integers, which
    is exactly why the unit is micros *per million tokens*."""
    assert PRICES["gpt-4o"].input_micros_per_million == 2_500_000
    assert PRICES["gpt-5-nano"].input_micros_per_million == 50_000


def test_one_million_tokens_costs_exactly_the_quoted_price() -> None:
    """The definition of the unit, asserted so a refactor cannot drift it."""
    usage = TokenUsage(input_tokens=1_000_000, output_tokens=0)

    assert cost_micros("claude-opus-5", usage) == 5_000_000  # $5.00


def test_input_and_output_are_priced_separately() -> None:
    usage = TokenUsage(input_tokens=1_000_000, output_tokens=1_000_000)

    # $5.00 input + $25.00 output.
    assert cost_micros("claude-opus-5", usage) == 30_000_000


# --- rounding ----------------------------------------------------------------


def test_a_sub_micro_cost_rounds_up_rather_than_to_zero() -> None:
    """Rounding direction is a decision, not an accident.

    One token of Opus 5 input is 5 micros exactly; one token of a $0.05/M model
    is 0.05 micros. Truncating makes it free, and a few million truncated calls
    is a budget cap that does not bind. Rounding up is the conservative
    direction for a *cap*: it can never under-count what the user has spent.
    """
    one_token = TokenUsage(input_tokens=1, output_tokens=0)

    assert cost_micros("gpt-5-nano", one_token) == 1


def test_rounding_up_applies_to_the_total_not_each_token() -> None:
    """Ceiling per call, not per token: otherwise 1000 tokens of a $0.05/M
    model would cost 1000 micros instead of 50."""
    usage = TokenUsage(input_tokens=1_000, output_tokens=0)

    assert cost_micros("gpt-5-nano", usage) == 50


def test_zero_usage_costs_nothing() -> None:
    assert cost_micros("claude-opus-5", TokenUsage()) == 0


# --- the dangerous default ---------------------------------------------------


def test_an_unknown_model_raises_rather_than_costing_zero() -> None:
    """The whole point of this module having an error type.

    If this ever returns 0, the monthly cap stops binding the moment a provider
    ships a model id we have not priced, and nothing anywhere reports it.
    """
    with pytest.raises(UnknownModelError) as excinfo:
        cost_micros("some-model-released-tomorrow", TokenUsage(input_tokens=10))

    assert "some-model-released-tomorrow" in str(excinfo.value)


def test_unknown_model_error_names_the_provider_prefix_when_it_can() -> None:
    """The message has to be actionable: it is what the user sees when a run
    is refused."""
    with pytest.raises(UnknownModelError) as excinfo:
        cost_micros("claude-opus-99", TokenUsage(input_tokens=1))

    assert "pricing.py" in str(excinfo.value)


def test_is_priced_reports_without_raising() -> None:
    """Callers that want to *check* rather than *charge* need a non-raising
    path: the budget pre-flight uses it to fail before an API call."""
    assert is_priced("claude-opus-5")
    assert not is_priced("some-model-released-tomorrow")


# --- local models ------------------------------------------------------------


def test_a_local_model_is_explicitly_free_not_unknown() -> None:
    """§7: local model support is optional but the abstraction must not assume
    cloud. A zero-cost model must be *registered* as zero, so that "free" and
    "unpriced" stay distinguishable."""
    assert is_priced("ollama/*")
    assert cost_micros("ollama/*", TokenUsage(input_tokens=10_000)) == 0


def test_an_ollama_model_of_any_name_is_free() -> None:
    """Ollama runs whatever the user pulled; the names are unbounded."""
    usage = TokenUsage(input_tokens=5_000, output_tokens=5_000)

    assert cost_micros("ollama/llama3.3:70b", usage) == 0
    assert cost_micros("ollama/qwen2.5-coder", usage) == 0


# --- presentation ------------------------------------------------------------


def test_format_micros_renders_dollars_without_float_arithmetic() -> None:
    assert format_micros(0) == "$0.0000"
    assert format_micros(5_000_000) == "$5.0000"
    assert format_micros(1) == "$0.0000"
    assert format_micros(12_345) == "$0.0123"


def test_format_micros_handles_large_amounts() -> None:
    assert format_micros(123_456_789) == "$123.4568"


# --- the table itself --------------------------------------------------------


def test_model_price_is_frozen() -> None:
    """Prices are data, and nothing at runtime may edit them."""
    price = PRICES["claude-opus-5"]

    with pytest.raises((AttributeError, TypeError)):
        price.input_micros_per_million = 1  # type: ignore[misc]


def test_price_table_covers_the_default_models() -> None:
    """The models the app can actually be configured to use must be priced, or
    the first run refuses with UnknownModelError."""
    for model in ("claude-opus-5", "claude-sonnet-5", "gpt-5.4", "gpt-4o"):
        assert model in PRICES, model


def test_model_price_rejects_negative_prices() -> None:
    with pytest.raises(ValueError, match="negative"):
        ModelPrice(input_micros_per_million=-1, output_micros_per_million=0)
