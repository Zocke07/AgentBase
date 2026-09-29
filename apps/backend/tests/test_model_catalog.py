"""The model catalog: each priced model's tier, and moving a model between providers."""

from __future__ import annotations

import pytest

from agentbase.providers.catalog import DEFAULT_TIER, TIERS, catalog_for, equivalent, tier_of
from agentbase.providers.pricing import MODELS_BY_PROVIDER
from agentbase.store.settings import DEFAULT_MODELS


@pytest.mark.parametrize("provider", ["anthropic", "openai"])
def test_every_priced_model_has_a_place_and_nothing_else_does(provider: str) -> None:
    """A model priced but untiered would map as if unknown; one tiered but
    unpriced would be offered and then refused at run time."""
    assert sorted(entry.model for entry in catalog_for(provider)) == sorted(
        MODELS_BY_PROVIDER[provider]
    )


@pytest.mark.parametrize("provider", ["anthropic", "openai"])
def test_a_current_lineup_has_at_most_one_model_per_tier(provider: str) -> None:
    """Mapping picks the current model at a tier; two would make it arbitrary."""
    tiers = [entry.tier for entry in catalog_for(provider) if entry.current]
    assert len(tiers) == len(set(tiers))
    assert set(tiers) <= set(TIERS)


@pytest.mark.parametrize("provider", ["anthropic", "openai"])
def test_a_new_space_starts_where_an_unknown_model_would_map(provider: str) -> None:
    """The defaults are the current model nearest `DEFAULT_TIER`, so a space
    created on a provider and one switched there from an untiered model agree."""
    assert DEFAULT_MODELS[provider] == equivalent(None, "ollama", provider)
    assert DEFAULT_TIER == "strong"


@pytest.mark.parametrize(
    ("model", "source", "target", "expected"),
    [
        ("claude-haiku-4-5", "anthropic", "openai", "gpt-6-luna"),
        ("claude-haiku-4-5-20251001", "anthropic", "openai", "gpt-6-luna"),
        ("claude-sonnet-5", "anthropic", "openai", "gpt-6-sol"),
        ("claude-fable-5-1", "anthropic", "openai", "gpt-6-astra"),
        # GPT-6 has nothing between Astra and Sol; a tie goes to the cheaper.
        ("claude-opus-5-5", "anthropic", "openai", "gpt-6-sol"),
        ("claude-opus-4-6", "anthropic", "openai", "gpt-6-sol"),
        ("gpt-6-luna", "openai", "anthropic", "claude-haiku-4-5"),
        ("gpt-6-sol", "openai", "anthropic", "claude-sonnet-5"),
        ("gpt-6-astra", "openai", "anthropic", "claude-fable-5-1"),
        ("gpt-5.5", "openai", "anthropic", "claude-opus-5-5"),
        ("gpt-4o-mini", "openai", "anthropic", "claude-haiku-4-5"),
        ("qwen3:4b", "ollama", "anthropic", "claude-opus-5-5"),
        ("claude-sonnet-5", "anthropic", "anthropic", "claude-sonnet-5"),
    ],
)
def test_a_model_moves_to_its_counterpart(
    model: str, source: str, target: str, expected: str
) -> None:
    assert equivalent(model, source, target) == expected


def test_nothing_is_guessed_for_a_provider_whose_models_are_typed() -> None:
    assert equivalent("claude-sonnet-5", "anthropic", "ollama") is None


def test_a_round_trip_through_the_gap_does_not_come_back() -> None:
    """Opus and Sonnet both land on Sol, and Sol comes back as Sonnet. Space
    settings shows every mapped model before saving for this reason."""
    there = equivalent("claude-opus-5-5", "anthropic", "openai")
    assert equivalent(there, "openai", "anthropic") == "claude-sonnet-5"


def test_an_unlisted_model_has_no_tier() -> None:
    assert tier_of("anthropic", "claude-3-haiku") is None
    assert tier_of("anthropic", None) is None


#: A ChatGPT plan's models (Codex, 2026-09-29): GPT-6 Sol and Luna are API-only.
PLAN = frozenset({"gpt-6-astra", "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna", "gpt-5.5"})


@pytest.mark.parametrize(
    ("model", "source", "expected"),
    [
        ("claude-opus-5-5", "anthropic", "gpt-5.6-sol"),
        ("claude-haiku-4-5", "anthropic", "gpt-5.6-luna"),
        ("gpt-6-sol", "openai", "gpt-5.6-terra"),
        ("gpt-6-luna", "openai", "gpt-5.6-luna"),
        ("gpt-6-astra", "openai", "gpt-6-astra"),
    ],
)
def test_a_plan_limits_the_mapping_to_models_it_includes(
    model: str, source: str, expected: str
) -> None:
    """Within the plan, a tier maps as it would on the price list, and a model
    the plan already includes is left alone."""
    assert equivalent(model, source, "openai", PLAN) == expected


def test_without_a_plan_the_mapping_is_unchanged() -> None:
    assert equivalent("claude-opus-5-5", "anthropic", "openai") == "gpt-6-sol"
    assert equivalent("gpt-6-sol", "openai", "openai") == "gpt-6-sol"
