"""Where each priced model sits in its provider's lineup.

A tier is a model's place in the lineup, from the most capable to the
fastest. Moving a space or an agent to another provider maps its model
through its tier, so a Haiku collector becomes the other provider's fast
model instead of that provider's default. Pickers list models in this order:
the current lineup first, then older models that are still sold.

Tiers are a judgement from each provider's own descriptions and prices, not a
benchmark. Checked 2026-09-27 against platform.claude.com's models overview
and developers.openai.com's models page.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final, Literal

__all__ = [
    "DEFAULT_TIER",
    "TIERS",
    "CatalogEntry",
    "Tier",
    "catalog_for",
    "equivalent",
    "tier_of",
]

Tier = Literal["frontier", "strong", "balanced", "fast"]

#: Most capable first.
TIERS: Final[tuple[Tier, ...]] = ("frontier", "strong", "balanced", "fast")

#: The tier a new space starts on; `store.settings.DEFAULT_MODELS` names it.
DEFAULT_TIER: Final[Tier] = "strong"


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    model: str
    tier: Tier
    #: In the provider's current lineup; older models are kept while sold.
    current: bool


def _entries(current: dict[str, Tier], older: dict[str, Tier]) -> tuple[CatalogEntry, ...]:
    return (
        *(CatalogEntry(model, tier, current=True) for model, tier in current.items()),
        *(CatalogEntry(model, tier, current=False) for model, tier in older.items()),
    )


_CATALOG: Final[dict[str, tuple[CatalogEntry, ...]]] = {
    "anthropic": _entries(
        {
            "claude-fable-5-1": "frontier",
            "claude-opus-5-5": "strong",
            "claude-sonnet-5": "balanced",
            "claude-haiku-4-5": "fast",
        },
        {
            "claude-fable-5": "frontier",
            "claude-opus-5": "strong",
            "claude-opus-4-8": "strong",
            "claude-opus-4-7": "strong",
            "claude-opus-4-6": "strong",
            "claude-sonnet-4-6": "balanced",
        },
    ),
    # GPT-6 has no model between Astra ($10/$50) and Sol ($2/$10), so nothing
    # current is "strong": Opus 5.5 moves to Sol, the model OpenAI describes
    # for complex coding and agentic work (maintainer's choice, 2026-09-27).
    "openai": _entries(
        {
            "gpt-6-astra": "frontier",
            "gpt-6-sol": "balanced",
            "gpt-6-luna": "fast",
        },
        {
            "gpt-5.6-sol": "strong",
            "gpt-5.6-terra": "balanced",
            "gpt-5.6-luna": "fast",
            "gpt-5.5": "strong",
            "gpt-5.4": "balanced",
            "gpt-5.4-mini": "fast",
            "gpt-5.4-nano": "fast",
            "gpt-5.2": "balanced",
            "gpt-5.1": "balanced",
            "gpt-5": "balanced",
            "gpt-5-mini": "fast",
            "gpt-5-nano": "fast",
            "gpt-4.1": "balanced",
            "gpt-4.1-mini": "fast",
            "gpt-4.1-nano": "fast",
            "gpt-4o": "balanced",
            "gpt-4o-mini": "fast",
            "o3": "balanced",
            "o3-mini": "fast",
        },
    ),
}

#: Anthropic's dated snapshots share their alias's place.
_SNAPSHOT: Final[re.Pattern[str]] = re.compile(r"^(claude-[a-z0-9-]+?)-\d{8}$")


def catalog_for(provider: str) -> tuple[CatalogEntry, ...]:
    """The provider's models in picker order; empty where models are typed."""
    return _CATALOG.get(provider, ())


def tier_of(provider: str, model: str | None) -> Tier | None:
    """The tier ``model`` serves on ``provider``, or ``None`` if it is not listed."""
    if model is None:
        return None
    match = _SNAPSHOT.match(model)
    name = match.group(1) if match else model
    return next((entry.tier for entry in catalog_for(provider) if entry.model == name), None)


def _nearest(tier: Tier) -> list[Tier]:
    """Tiers by distance from ``tier``; a tie goes to the faster, cheaper one."""
    at = TIERS.index(tier)
    return sorted(TIERS, key=lambda other: (abs(TIERS.index(other) - at), -TIERS.index(other)))


def equivalent(model: str | None, source: str, target: str) -> str | None:
    """``model`` on ``source``'s counterpart among ``target``'s current models.

    Same provider: unchanged. A model with no tier (typed, or unknown) maps
    to the target's default tier. ``None`` where the target's models are
    typed (Ollama), since nothing local can be guessed.
    """
    if source == target:
        return model
    current = [entry for entry in catalog_for(target) if entry.current]
    if not current:
        return None
    wanted = tier_of(source, model) or DEFAULT_TIER
    for tier in _nearest(wanted):
        for entry in current:
            if entry.tier == tier:
                return entry.model
    return None
