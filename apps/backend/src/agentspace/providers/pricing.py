"""Per-model token pricing, in integer micros.

Money never touches a float. Prices are stored per *million* tokens because
$0.05 per million is 0.05 micros per token, not an integer; the one division
happens at the point of charging, rounding up. An unpriced model raises rather
than costing zero, since a zero default would let the cap stop binding
silently. The rows are list prices recorded on a date, and only affect the
user's own cap, never what a provider bills.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from agentspace.providers.base import TokenUsage

__all__ = [
    "MICROS_PER_DOLLAR",
    "MODELS_BY_PROVIDER",
    "PRICES",
    "ModelPrice",
    "UnknownModelError",
    "cost_micros",
    "format_micros",
    "is_priced",
]

#: A micro is one millionth of a US dollar. §4: `cost_micros`.
MICROS_PER_DOLLAR: Final[int] = 1_000_000

#: Prices are quoted per this many tokens.
TOKENS_PER_PRICE_UNIT: Final[int] = 1_000_000

#: Model ids under this prefix run on the user's own machine and cost nothing.
LOCAL_MODEL_PREFIX: Final[str] = "ollama/"


class UnknownModelError(LookupError):
    """Raised when a model has no price. Deliberately not a soft failure."""

    def __init__(self, model: str) -> None:
        super().__init__(
            f"no price is registered for model {model!r}. Add it to PRICES in "
            f"agentspace/providers/pricing.py: an unpriced model is refused "
            f"rather than charged at zero, because a zero-cost default makes "
            f"the monthly budget cap stop binding without any error."
        )
        self.model = model


@dataclass(frozen=True, slots=True)
class ModelPrice:
    """What one million input and output tokens cost, in micros."""

    input_micros_per_million: int
    output_micros_per_million: int

    def __post_init__(self) -> None:
        if self.input_micros_per_million < 0 or self.output_micros_per_million < 0:
            msg = f"a price cannot be negative: {self!r}"
            raise ValueError(msg)


def _usd(dollars_per_million_input: str, dollars_per_million_output: str) -> ModelPrice:
    """Build a price from the published dollar figures, as strings.

    `float("0.05") * 1_000_000` is not 50000.
    """
    return ModelPrice(
        input_micros_per_million=_dollars_to_micros(dollars_per_million_input),
        output_micros_per_million=_dollars_to_micros(dollars_per_million_output),
    )


def _dollars_to_micros(dollars: str) -> int:
    """Parse a decimal dollar string into micros, exactly and without floats."""
    whole, _, fraction = dollars.partition(".")
    fraction = (fraction + "000000")[:6]
    return int(whole) * MICROS_PER_DOLLAR + int(fraction)


#: List prices per million tokens, one table per provider, so the settings API
#: can say which models belong to which. Anthropic rows checked 2026-06-24
#: against the bundled `claude-api` reference; OpenAI rows checked 2026-09-09
#: against developers.openai.com. Standard-tier, short-context, non-batch.
_ANTHROPIC: Final[dict[str, ModelPrice]] = {
    "claude-fable-5-1": _usd("10.00", "50.00"),
    "claude-fable-5": _usd("10.00", "50.00"),
    "claude-opus-5": _usd("5.00", "25.00"),
    "claude-opus-4-8": _usd("5.00", "25.00"),
    "claude-opus-4-7": _usd("5.00", "25.00"),
    "claude-opus-4-6": _usd("5.00", "25.00"),
    "claude-sonnet-5": _usd("2.00", "10.00"),
    "claude-sonnet-4-6": _usd("3.00", "15.00"),
    "claude-haiku-4-5": _usd("1.00", "5.00"),
}

_OPENAI: Final[dict[str, ModelPrice]] = {
    "gpt-6-astra": _usd("10.00", "50.00"),
    "gpt-5.6-sol": _usd("4.00", "20.00"),
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

#: Inference on the user's own hardware, registered explicitly at zero so
#: "free" and "unpriced" stay different answers. `_lookup` matches any
#: `ollama/` model; the name is free text, so ``MODELS_BY_PROVIDER`` lists none.
_LOCAL: Final[dict[str, ModelPrice]] = {
    "ollama/*": ModelPrice(input_micros_per_million=0, output_micros_per_million=0),
}

PRICES: Final[dict[str, ModelPrice]] = {**_ANTHROPIC, **_OPENAI, **_LOCAL}

#: The selectable models of each provider, derived from the same tables as ``PRICES``.
MODELS_BY_PROVIDER: Final[dict[str, list[str]]] = {
    "anthropic": sorted(_ANTHROPIC),
    "openai": sorted(_OPENAI),
    "ollama": [],
}


def _lookup(model: str) -> ModelPrice | None:
    """Resolve a price, or ``None``. Local models match by prefix."""
    if model.startswith(LOCAL_MODEL_PREFIX):
        return PRICES["ollama/*"]
    return PRICES.get(model)


def is_priced(model: str) -> bool:
    """Whether :func:`cost_micros` will succeed for ``model``; the pre-flight refuses if not."""
    return _lookup(model) is not None


def cost_micros(model: str, usage: TokenUsage) -> int:
    """What ``usage`` on ``model`` costs, in whole micros.

    Rounded up: a cap must never under-count.

    :raises UnknownModelError: if ``model`` has no registered price.
    """
    price = _lookup(model)
    if price is None:
        raise UnknownModelError(model)

    total = (
        usage.input_tokens * price.input_micros_per_million
        + usage.output_tokens * price.output_micros_per_million
    )

    # Ceiling division, integer-only: -(-a // b).
    return -(-total // TOKENS_PER_PRICE_UNIT)


def format_micros(micros: int) -> str:
    """Render micros as a dollar string: four places, integer arithmetic only.

    Rounded to nearest, unlike :func:`cost_micros`: a display should be the closest
    true reading, and rounding one micro up would show ``$0.0001``.
    """
    sign = "-" if micros < 0 else ""

    # In units of $0.0001, so the carry from .9999 falls out of the division.
    ten_thousandths = (abs(micros) + 50) // 100
    dollars, remainder = divmod(ten_thousandths, 10_000)
    return f"{sign}${dollars}.{remainder:04d}"
