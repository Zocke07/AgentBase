"""Per-model token pricing in integer micros.

Never use floats. Store prices per million tokens because $0.05/million is not
an integer micros-per-token value; divide and round up only at charge time.
Unpriced models raise rather than cost zero, which would silently disable caps.
Rows are dated list prices for the user's cap, never provider billing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from agentbase.providers.base import TokenUsage

__all__ = [
    "MICROS_PER_DOLLAR",
    "MODELS_BY_PROVIDER",
    "PRICES",
    "LongContextPrice",
    "ModelPrice",
    "UnknownModelError",
    "cost_micros",
    "format_micros",
    "is_priced",
]

#: One micro is one millionth of a US dollar. §4: ``cost_micros``.
MICROS_PER_DOLLAR: Final[int] = 1_000_000

#: Prices are quoted per this many tokens.
TOKENS_PER_PRICE_UNIT: Final[int] = 1_000_000

#: IDs under this prefix run locally and cost nothing.
LOCAL_MODEL_PREFIX: Final[str] = "ollama/"

#: Anthropic dated snapshots (for example ``claude-haiku-4-5-20251001``) use
#: alias pricing. OpenAI dated snapshots can differ, so match Anthropic only.
_ANTHROPIC_SNAPSHOT: Final[re.Pattern[str]] = re.compile(r"^(claude-[a-z0-9-]+?)-(\d{8})$")


class UnknownModelError(LookupError):
    """Model has no price; deliberately not a soft failure."""

    def __init__(self, model: str) -> None:
        super().__init__(
            f"no price is registered for model {model!r}. Add it to PRICES in "
            f"agentbase/providers/pricing.py: an unpriced model is refused "
            f"rather than charged at zero, because a zero-cost default makes "
            f"the monthly budget cap stop binding without any error."
        )
        self.model = model


@dataclass(frozen=True, slots=True)
class LongContextPrice:
    """Whole-request rates when input exceeds the given token threshold."""

    over_input_tokens: int
    input_micros_per_million: int
    output_micros_per_million: int

    def __post_init__(self) -> None:
        if self.over_input_tokens <= 0:
            msg = "a long-context threshold must be positive"
            raise ValueError(msg)
        if self.input_micros_per_million < 0 or self.output_micros_per_million < 0:
            msg = f"a price cannot be negative: {self!r}"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class ModelPrice:
    """Input/output micros per million tokens, with an optional prompt tier."""

    input_micros_per_million: int
    output_micros_per_million: int
    long_context: LongContextPrice | None = None

    def __post_init__(self) -> None:
        if self.input_micros_per_million < 0 or self.output_micros_per_million < 0:
            msg = f"a price cannot be negative: {self!r}"
            raise ValueError(msg)


def _usd(dollars_per_million_input: str, dollars_per_million_output: str) -> ModelPrice:
    """Build price from published string dollar figures; floats are inexact."""
    return ModelPrice(
        input_micros_per_million=_dollars_to_micros(dollars_per_million_input),
        output_micros_per_million=_dollars_to_micros(dollars_per_million_output),
    )


def _long_usd(
    input_price: str,
    output_price: str,
    over_input_tokens: int,
    long_input_price: str,
    long_output_price: str,
) -> ModelPrice:
    """Published short/long dollar rates; the selected rate prices the full call."""
    return ModelPrice(
        input_micros_per_million=_dollars_to_micros(input_price),
        output_micros_per_million=_dollars_to_micros(output_price),
        long_context=LongContextPrice(
            over_input_tokens=over_input_tokens,
            input_micros_per_million=_dollars_to_micros(long_input_price),
            output_micros_per_million=_dollars_to_micros(long_output_price),
        ),
    )


def _dollars_to_micros(dollars: str) -> int:
    """Parse decimal dollar string to micros exactly, without floats."""
    whole, _, fraction = dollars.partition(".")
    fraction = (fraction + "000000")[:6]
    return int(whole) * MICROS_PER_DOLLAR + int(fraction)


#: List prices per million tokens by provider, used by settings. Both checked
#: 2026-10-12, Anthropic against platform.claude.com/docs/en/models/overview
#: and OpenAI against developers.openai.com/api/docs/pricing. Standard-tier,
#: non-batch; applicable prompt-length premiums count against caps. `catalog.py`
#: gives each one a tier; a model
#: priced here and missing there fails a test.
_ANTHROPIC: Final[dict[str, ModelPrice]] = {
    "claude-fable-5-1": _usd("10.00", "50.00"),
    "claude-fable-5": _usd("10.00", "50.00"),
    "claude-opus-5-5": _usd("4.00", "20.00"),
    "claude-opus-5": _usd("5.00", "25.00"),
    "claude-opus-4-8": _usd("5.00", "25.00"),
    "claude-opus-4-7": _usd("5.00", "25.00"),
    "claude-opus-4-6": _usd("5.00", "25.00"),
    "claude-sonnet-5-5": _usd("2.00", "10.00"),
    "claude-sonnet-5": _usd("2.00", "10.00"),
    "claude-sonnet-4-6": _usd("3.00", "15.00"),
    "claude-haiku-5-5": _long_usd("0.10", "0.50", 100_000, "0.50", "2.50"),
    "claude-haiku-4-5": _usd("1.00", "5.00"),
}

_OPENAI: Final[dict[str, ModelPrice]] = {
    "gpt-6-astra": _long_usd("10.00", "50.00", 272_000, "20.00", "75.00"),
    "gpt-6.1-sol": _long_usd("2.00", "10.00", 272_000, "4.00", "15.00"),
    "gpt-6-sol": _long_usd("2.00", "10.00", 272_000, "4.00", "15.00"),
    "gpt-6-luna": _long_usd("0.10", "0.50", 272_000, "0.20", "0.75"),
    "gpt-5.6-sol": _long_usd("4.00", "20.00", 272_000, "8.00", "30.00"),
    "gpt-5.6-terra": _usd("2.00", "12.00"),
    "gpt-5.6-luna": _usd("0.20", "1.20"),
    "gpt-5.5": _usd("5.00", "30.00"),
    "gpt-5.4": _usd("2.50", "15.00"),
    "gpt-5.4-mini": _usd("0.75", "4.50"),
    "gpt-5.4-nano": _usd("0.20", "1.25"),
    "gpt-5.2": _usd("1.75", "14.00"),
    "gpt-5.1": _usd("1.25", "10.00"),
    "gpt-5": _usd("1.25", "10.00"),
    "gpt-5-mini": _usd("0.25", "2.00"),
    "gpt-5-nano": _usd("0.05", "0.40"),
    "gpt-4.1": _usd("2.00", "8.00"),
    "gpt-4.1-mini": _usd("0.40", "1.60"),
    "gpt-4.1-nano": _usd("0.10", "0.40"),
    "gpt-4o": _usd("2.50", "10.00"),
    "gpt-4o-mini": _usd("0.15", "0.60"),
    "o3": _usd("2.00", "8.00"),
    "o3-mini": _usd("1.10", "4.40"),
}

#: Local inference is explicitly zero so free differs from unpriced. ``_lookup``
#: matches any ``ollama/`` free-text model, so ``MODELS_BY_PROVIDER`` lists none.
_LOCAL: Final[dict[str, ModelPrice]] = {
    "ollama/*": ModelPrice(input_micros_per_million=0, output_micros_per_million=0),
}

PRICES: Final[dict[str, ModelPrice]] = {**_ANTHROPIC, **_OPENAI, **_LOCAL}

#: Priced models by provider. Pickers use `catalog.py`'s order instead.
MODELS_BY_PROVIDER: Final[dict[str, list[str]]] = {
    "anthropic": sorted(_ANTHROPIC),
    "openai": sorted(_OPENAI),
    "ollama": [],
}


def _lookup(model: str) -> ModelPrice | None:
    """Resolve price or ``None``.

    Match local models by prefix and Anthropic dated snapshots by alias; otherwise
    require exact ID.
    """
    if model.startswith(LOCAL_MODEL_PREFIX):
        return PRICES["ollama/*"]
    price = PRICES.get(model)
    if price is None and (snapshot := _ANTHROPIC_SNAPSHOT.match(model)):
        price = _ANTHROPIC.get(snapshot.group(1))
    return price


def is_priced(model: str) -> bool:
    """Whether :func:`cost_micros` accepts ``model``; pre-flight refuses otherwise."""
    return _lookup(model) is not None


def cost_micros(model: str, usage: TokenUsage) -> int:
    """Return whole-micros ``usage`` cost for ``model``, rounded up.

    Caps must not undercount.

        :raises UnknownModelError: if no price is registered.
    """
    price = _lookup(model)
    if price is None:
        raise UnknownModelError(model)

    rates: ModelPrice | LongContextPrice = price
    if (
        price.long_context is not None
        and usage.input_tokens > price.long_context.over_input_tokens
    ):
        rates = price.long_context

    total = (
        usage.input_tokens * rates.input_micros_per_million
        + usage.output_tokens * rates.output_micros_per_million
    )

    # Integer-only ceiling division: ``-(-a // b)``.
    return -(-total // TOKENS_PER_PRICE_UNIT)


def format_micros(micros: int) -> str:
    """Render micros as four-place dollar string using integers.

    Unlike :func:`cost_micros`, display rounds nearest: rounding one micro up
    would falsely show ``$0.0001``.
    """
    sign = "-" if micros < 0 else ""

    # Work in $0.0001 units so .9999 carry falls out of division.
    ten_thousandths = (abs(micros) + 50) // 100
    dollars, remainder = divmod(ten_thousandths, 10_000)
    return f"{sign}${dollars}.{remainder:04d}"
