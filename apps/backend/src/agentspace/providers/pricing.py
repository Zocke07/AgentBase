"""Per-model token pricing, in integer micros.

**Money is never a float here.** §4 stores `cost_micros` as an INTEGER and this
module is why: a price expressed in dollars as a float (`0.05`) cannot be
represented exactly, and the error compounds across every call in a month until
the monthly cap is wrong by an amount nobody can explain.

**The unit is micros per *million* tokens**, not micros per token. Real prices
include $2.50 and $0.05 per million, which are 2.5 and 0.05 micros per token —
not integers. Storing the per-million figure keeps every published price exact,
and the division happens once, at the point of charging, with an explicit
rounding rule.

**An unpriced model raises.** The obvious `PRICES.get(model, 0)` would make the
budget cap silently stop binding the day a provider ships a model id this table
does not know, with no error anywhere. :class:`UnknownModelError` makes that a
loud failure before the API call instead of a quiet one after it.

Prices below are list prices per million tokens, recorded with the date they
were checked. They are data, not truth: a stale row over-or-under-charges the
user's own cap, which is annoying but local — it never affects what a provider
actually bills.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from agentspace.providers.base import TokenUsage

__all__ = [
    "MICROS_PER_DOLLAR",
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
    """Raised when a model has no price.

    Deliberately not a soft failure. See the module docstring.
    """

    def __init__(self, model: str) -> None:
        super().__init__(
            f"no price is registered for model {model!r}. Add it to PRICES in "
            f"agentspace/providers/pricing.py — an unpriced model is refused "
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
    """Build a price from the dollar figures as published.

    Takes strings and parses them as integer cents-of-a-micro rather than
    calling `float()`: `float("0.05") * 1_000_000` is 50000.00000000001 on this
    machine, and rounding it back is the exact class of bug this module exists
    to prevent.
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


#: List prices per million tokens.
#:
#: Anthropic rows checked 2026-06-24 against the bundled `claude-api` reference;
#: OpenAI rows checked 2026-09-09 against developers.openai.com/api/docs/pricing.
#: Both are standard-tier, short-context, non-batch rates.
PRICES: Final[dict[str, ModelPrice]] = {
    # --- Anthropic ---
    "claude-fable-5-1": _usd("10.00", "50.00"),
    "claude-fable-5": _usd("10.00", "50.00"),
    "claude-opus-5": _usd("5.00", "25.00"),
    "claude-opus-4-8": _usd("5.00", "25.00"),
    "claude-opus-4-7": _usd("5.00", "25.00"),
    "claude-opus-4-6": _usd("5.00", "25.00"),
    "claude-sonnet-5": _usd("2.00", "10.00"),
    "claude-sonnet-4-6": _usd("3.00", "15.00"),
    "claude-haiku-4-5": _usd("1.00", "5.00"),
    # --- OpenAI ---
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
    # --- Local ---
    #: Inference on the user's own hardware. Registered explicitly at zero so
    #: that "free" and "we do not know the price" stay different answers; the
    #: wildcard is documentation, `_lookup` matches any `ollama/` model.
    "ollama/*": ModelPrice(input_micros_per_million=0, output_micros_per_million=0),
}


def _lookup(model: str) -> ModelPrice | None:
    """Resolve a price, or ``None``. Local models match by prefix.

    Ollama serves whatever the user has pulled, so the set of valid names is
    open-ended and cannot be enumerated. Charging them at zero is correct
    rather than a guess: the tokens never leave the machine.
    """
    if model.startswith(LOCAL_MODEL_PREFIX):
        return PRICES["ollama/*"]
    return PRICES.get(model)


def is_priced(model: str) -> bool:
    """Whether :func:`cost_micros` will succeed for ``model``.

    The budget pre-flight uses this to refuse a run *before* any API call,
    which is the Phase 3 acceptance criterion.
    """
    return _lookup(model) is not None


def cost_micros(model: str, usage: TokenUsage) -> int:
    """What ``usage`` on ``model`` costs, in whole micros.

    Rounds **up**. The alternative directions are both worse for a spending
    cap: truncation lets sub-micro charges accumulate as free, and
    round-to-nearest is unbiased across many calls but still under-counts about
    half of them. A cap that errs must err towards refusing too early, never
    towards letting a run through.

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
    """Render micros as a dollar string, for a human-legible refusal message.

    Four decimal places, rounded to nearest, with integer arithmetic only —
    `micros / 1_000_000` would reintroduce exactly the float this module exists
    to keep out of money.

    Rounding here is to *nearest*, unlike :func:`cost_micros`, which rounds up.
    They are answering different questions: charging must never under-count,
    while a displayed figure should be the closest true reading. Rounding a
    display up would render a single micro as ``$0.0001`` — a hundredfold
    overstatement of a real, and very common, amount.
    """
    sign = "-" if micros < 0 else ""

    # Work in hundredths of a micro-dollar, i.e. units of $0.0001, so the
    # carry from .9999 -> the next dollar falls out of the division.
    ten_thousandths = (abs(micros) + 50) // 100
    dollars, remainder = divmod(ten_thousandths, 10_000)
    return f"{sign}${dollars}.{remainder:04d}"
