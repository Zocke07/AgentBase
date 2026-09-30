"""Where each priced model sits in its provider's lineup.

A tier is a model's place in the lineup, from the most capable to the
fastest. Moving a space or an agent to another provider maps its model
through its tier, so a Haiku collector becomes the other provider's fast
model instead of that provider's default. Pickers list models in this order:
the current lineup first, then older models that are still sold.

Tiers are a judgement from each provider's own descriptions and prices, not a
benchmark. Checked 2026-09-30 against platform.claude.com's models overview
and developers.openai.com's models page.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal

if TYPE_CHECKING:
    from collections.abc import Collection

__all__ = [
    "DEFAULT_TIERS",
    "SHIPPED_AGENT_TIERS",
    "TIERS",
    "CatalogEntry",
    "Tier",
    "catalog_for",
    "equivalent",
    "equivalent_for_agent",
    "lineup",
    "tier_of",
]

Tier = Literal["frontier", "strong", "balanced", "fast"]

#: Most capable first.
TIERS: Final[tuple[Tier, ...]] = ("frontier", "strong", "balanced", "fast")

#: The billed-token model level a new space starts on for each fixed catalogue.
#: A ChatGPT plan starts strong instead; its calls are not billed per token.
DEFAULT_TIERS: Final[dict[str, Tier]] = {
    "anthropic": "balanced",
    "openai": "balanced",
}

#: The intended level of each shipped investment agent. GPT-6 Sol stands in
#: for balanced and strong, so fixed IDs retain their distinction when it is
#: later repaired to a ChatGPT plan model.
SHIPPED_AGENT_TIERS: Final[dict[str, Tier]] = {
    "c2a1ac57-ee48-4799-b94c-b01a051fdfe3": "fast",
    "0cdfe6c1-4f35-47a6-99d1-f92952984df4": "balanced",
    "c2704070-67ec-4058-ba4f-4a63f0bdf479": "fast",
    "1ab3b5f3-6c98-4297-b7ff-35971356dd27": "fast",
    "26846fbe-8a39-409a-9626-ccb84ab3e893": "fast",
    "6dcd4865-b830-42fe-b005-cca3f9d1057a": "balanced",
    "cc55c979-8117-4b68-b9ea-83d4435e1823": "balanced",
    "714a2fec-4ddf-4583-922e-833b6abd4fd4": "balanced",
    "3ea7f62a-6177-43c2-9367-3631dea22798": "strong",
    "8995be58-7f43-4292-a52f-3b8ee8b533a6": "balanced",
}


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
            "claude-sonnet-5-5": "balanced",
            "claude-haiku-4-5": "fast",
        },
        {
            "claude-fable-5": "frontier",
            "claude-opus-5": "strong",
            "claude-opus-4-8": "strong",
            "claude-opus-4-7": "strong",
            "claude-opus-4-6": "strong",
            "claude-sonnet-5": "balanced",
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

#: A space's model that stands in for a tier its own lineup lacks, sought at
#: that tier where a ChatGPT plan does not include it. GPT-6 has no strong
#: model, so new spaces and Opus 5.5 landed on Sol; a space there wants the
#: plan's strong model, GPT-5.6 Sol, which OpenAI describes for complex work
#: (maintainer's choice, 2026-09-29). An agent on Sol may have come from
#: Sonnet 5, so agents keep Sol's own tier.
_SPACE_STANDS_IN: Final[dict[tuple[str, str], Tier]] = {("openai", "gpt-6-sol"): "strong"}

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


def lineup(provider: str, available: Collection[str] | None = None) -> list[CatalogEntry]:
    """The models a mapping may land on.

    The current lineup, or, where an account lists the models it may use (a
    ChatGPT subscription through Codex), every listed model the catalog
    prices, current ones first. Older models count there because a plan can
    carry a model the API has moved on from.
    """
    entries = catalog_for(provider)
    if available is None:
        return [entry for entry in entries if entry.current]
    allowed = [entry for entry in entries if entry.model in available]
    return sorted(allowed, key=lambda entry: not entry.current)


def equivalent(
    model: str | None,
    source: str,
    target: str,
    available: Collection[str] | None = None,
    *,
    space: bool = False,
) -> str | None:
    """``model`` on ``source``'s counterpart among ``target``'s models.

    Same provider: unchanged, unless ``available`` excludes it, when it maps
    to the nearest listed tier; ``space`` marks a space's own model, which may
    stand in for another tier there (`_SPACE_STANDS_IN`). A model with no tier
    (typed, or unknown) maps to the target's default tier. ``None`` where the
    target's models are typed (Ollama), since nothing local can be guessed, or
    where nothing the account lists is priced.
    """
    if source == target and (available is None or model in available):
        return model
    current = lineup(target, available)
    if not current:
        return None
    wanted = tier_of(source, model)
    if wanted is None:
        # A plan limits OpenAI to subscription models and starts at its strong
        # model. Otherwise an untiered model follows the target provider's
        # billed-token space default, as chosen on 2026-09-30.
        wanted = (
            "strong" if target == "openai" and available is not None else DEFAULT_TIERS[target]
        )
    if space and source == target and model is not None:
        wanted = _SPACE_STANDS_IN.get((source, model), wanted)
    for tier in _nearest(wanted):
        for entry in current:
            if entry.tier == tier:
                return entry.model
    return None


def equivalent_for_agent(
    agent_id: str,
    model: str | None,
    source: str,
    target: str,
    available: Collection[str] | None = None,
) -> str | None:
    """Map an agent model, preserving a shipped agent's level across Sol.

    GPT-6 Sol is normally balanced, but it also stands in for the shipped
    decision agent's strong model. Other models, including a model a person
    chose, continue to map by their catalogue tier.
    """
    if (source, model) != ("openai", "gpt-6-sol"):
        return equivalent(model, source, target, available)
    current = lineup(target, available)
    if not current:
        return None
    wanted = SHIPPED_AGENT_TIERS.get(agent_id, "balanced")
    for tier in _nearest(wanted):
        for entry in current:
            if entry.tier == tier:
                return entry.model
    return None
