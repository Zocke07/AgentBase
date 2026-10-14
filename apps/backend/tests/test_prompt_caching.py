"""Prompt caching: providers bill re-sent text at a discount (2026-10-14).

Each step of an agent re-sends its whole conversation: 71% of the input
tokens in the 2026-10-14 chain repeated the agent's previous call. Providers
cache that prefix and bill a cache read at a fraction of the input rate and a
cache write at a premium, at rates published 2026-10-14 on
developers.openai.com/api/docs/pricing and Anthropic's prompt-caching page.
The Anthropic adapter asks for caching (OpenAI caches without being asked),
every adapter reports the cached part of ``input_tokens``, and the price
table charges it.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import httpx2
import pytest

from agentbase.providers.anthropic import AnthropicProvider
from agentbase.providers.base import Completion, Message, Role, TextDelta, TokenUsage
from agentbase.providers.chatgpt import _usage as chatgpt_usage
from agentbase.providers.openai import OpenAIProvider
from agentbase.providers.pricing import cost_micros

pytestmark = pytest.mark.anyio

#: Under every model's long-context threshold, so the short rates apply.
_TOKENS = 100_000


def _client(body: dict[str, Any] | str, sent: list[dict[str, Any]]) -> httpx2.AsyncClient:
    def handle(request: httpx2.Request) -> httpx2.Response:
        sent.append(json.loads(request.content))
        if isinstance(body, str):
            return httpx2.Response(
                200, text=body, headers={"content-type": "text/event-stream"}
            )
        return httpx2.Response(200, json=body)

    return httpx2.AsyncClient(transport=httpx2.MockTransport(handle))


async def _terminal(provider: AnthropicProvider | OpenAIProvider) -> Completion:
    completion: Completion | None = None
    async for event in provider.stream([Message(Role.USER, "hi")]):
        if not isinstance(event, TextDelta):
            completion = event
    assert completion is not None
    return completion


# --- prices -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("model", "read_per_million", "write_per_million"),
    [
        ("gpt-5.6-terra", 200_000, 2_500_000),
        ("gpt-5.6-luna", 20_000, 250_000),
        ("gpt-5.6-sol", 400_000, 5_000_000),
        ("gpt-6.1-sol", 100_000, 2_500_000),
        ("gpt-6-sol", 200_000, 2_500_000),
        ("gpt-6-luna", 10_000, 125_000),
        ("gpt-6-astra", 1_000_000, 12_500_000),
        # Before GPT-5.6, a write costs the plain input rate.
        ("gpt-5.4", 250_000, 2_500_000),
        ("gpt-4.1", 500_000, 2_000_000),
        ("gpt-4o", 1_250_000, 2_500_000),
        ("o3-mini", 550_000, 1_100_000),
        # Anthropic: writes at 1.25x; reads at 0.1x, 0.05x for Sonnet and Opus
        # 5.5, and 0.025x for Fable 5.1.
        ("claude-sonnet-5-5", 100_000, 2_500_000),
        ("claude-opus-5-5", 200_000, 5_000_000),
        ("claude-haiku-5-5", 10_000, 125_000),
        ("claude-fable-5-1", 250_000, 12_500_000),
        ("claude-opus-4-8", 500_000, 6_250_000),
    ],
)
def test_cached_and_written_tokens_cost_their_published_rates(
    model: str, read_per_million: int, write_per_million: int
) -> None:
    read = cost_micros(model, TokenUsage(input_tokens=_TOKENS, cache_read_tokens=_TOKENS))
    written = cost_micros(model, TokenUsage(input_tokens=_TOKENS, cache_write_tokens=_TOKENS))

    assert (read, written) == (read_per_million // 10, write_per_million // 10)


def test_the_rest_of_the_prompt_and_the_answer_keep_their_rates() -> None:
    usage = TokenUsage(
        input_tokens=200_000,
        output_tokens=10_000,
        cache_read_tokens=160_000,
        cache_write_tokens=20_000,
    )

    # GPT-5.6 Terra: 20k plain at $2, 160k read at $0.20, 20k written at
    # $2.50 and 10k out at $12 per million.
    assert cost_micros("gpt-5.6-terra", usage) == 40_000 + 32_000 + 50_000 + 120_000


def test_a_long_prompt_prices_its_cached_part_at_the_long_tier() -> None:
    # GPT-5.6 Terra over 272k input: $4 input, $0.40 cached, $5 written.
    assert cost_micros("gpt-5.6-terra", TokenUsage(input_tokens=300_000)) == 1_200_000
    usage = TokenUsage(
        input_tokens=300_000, cache_read_tokens=200_000, cache_write_tokens=100_000
    )
    assert cost_micros("gpt-5.6-terra", usage) == 80_000 + 500_000
    # GPT-5.5 over 272k: $10 input.
    assert cost_micros("gpt-5.5", TokenUsage(input_tokens=300_000)) == 3_000_000


def test_reported_cache_counts_never_exceed_the_prompt() -> None:
    """What was cached or written is part of input_tokens, never extra."""
    capped = TokenUsage(input_tokens=1_000, cache_read_tokens=1_000)
    assert cost_micros(
        "gpt-5.6-terra", TokenUsage(input_tokens=1_000, cache_read_tokens=5_000)
    ) == cost_micros("gpt-5.6-terra", capped)
    both = TokenUsage(input_tokens=1_000, cache_read_tokens=800, cache_write_tokens=800)
    assert cost_micros("gpt-5.6-terra", both) == cost_micros(
        "gpt-5.6-terra",
        TokenUsage(input_tokens=1_000, cache_read_tokens=800, cache_write_tokens=200),
    )


# --- what each provider reports ------------------------------------------------


_ANTHROPIC_USAGE = {
    "input_tokens": 50,
    "cache_creation_input_tokens": 200,
    "cache_read_input_tokens": 9_000,
}
_CACHED = TokenUsage(9_250, 7, cache_read_tokens=9_000, cache_write_tokens=200)


async def test_anthropic_asks_for_caching_and_counts_the_whole_prompt() -> None:
    """Anthropic caches only when asked, and its input_tokens is only what
    follows the cached part: the prompt is the three counts together."""
    sent: list[dict[str, Any]] = []
    body = {
        "model": "claude-sonnet-5-5",
        "content": [{"type": "text", "text": "ok"}],
        "stop_reason": "end_turn",
        "usage": {**_ANTHROPIC_USAGE, "output_tokens": 7},
    }
    provider = AnthropicProvider("k", "claude-sonnet-5-5", client=_client(body, sent))

    result = await provider.complete([Message(Role.USER, "hi")], system="Be careful.")

    assert sent[0]["cache_control"] == {"type": "ephemeral"}
    assert result.usage == _CACHED


async def test_anthropic_streams_its_cache_counts() -> None:
    start = {
        "id": "m",
        "model": "claude-sonnet-5-5",
        "usage": {**_ANTHROPIC_USAGE, "output_tokens": 1},
    }
    frames = "\n".join(
        [
            "event: message_start",
            f"data: {json.dumps({'type': 'message_start', 'message': start})}",
            "",
            "event: content_block_start",
            'data: {"type":"content_block_start","index":0,'
            '"content_block":{"type":"text","text":""}}',
            "",
            "event: content_block_delta",
            'data: {"type":"content_block_delta","index":0,'
            '"delta":{"type":"text_delta","text":"ok"}}',
            "",
            "event: content_block_stop",
            'data: {"type":"content_block_stop","index":0}',
            "",
            "event: message_delta",
            'data: {"type":"message_delta","delta":{"stop_reason":"end_turn"},'
            '"usage":{"output_tokens":7}}',
            "",
            "event: message_stop",
            'data: {"type":"message_stop"}',
            "",
        ]
    )
    sent: list[dict[str, Any]] = []
    provider = AnthropicProvider("k", "claude-sonnet-5-5", client=_client(frames, sent))

    completion = await _terminal(provider)

    assert sent[0]["cache_control"] == {"type": "ephemeral"}
    assert completion.usage == _CACHED


async def test_openai_chat_reports_the_cached_and_written_part_of_the_prompt() -> None:
    usage = {
        "prompt_tokens": 9_250,
        "completion_tokens": 7,
        "prompt_tokens_details": {"cached_tokens": 9_000, "cache_write_tokens": 200},
    }
    body = {
        "model": "gpt-5.6-terra",
        "choices": [
            {"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}
        ],
        "usage": usage,
    }
    provider = OpenAIProvider("k", "gpt-5.6-terra", client=_client(body, []))

    assert (await provider.complete([Message(Role.USER, "hi")])).usage == _CACHED

    chunks = [
        {
            "id": "c",
            "model": "gpt-5.6-terra",
            "choices": [
                {
                    "index": 0,
                    "delta": {"role": "assistant", "content": "ok"},
                    "finish_reason": None,
                }
            ],
        },
        {
            "id": "c",
            "model": "gpt-5.6-terra",
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        },
        {"id": "c", "model": "gpt-5.6-terra", "choices": [], "usage": usage},
    ]
    stream = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n"
    streaming = OpenAIProvider("k", "gpt-5.6-terra", client=_client(stream, []))

    assert (await _terminal(streaming)).usage == _CACHED


async def test_openai_responses_report_the_cached_and_written_part_of_the_input() -> None:
    body = {
        "id": "r",
        "object": "response",
        "model": "gpt-6.1-sol",
        "status": "completed",
        "error": None,
        "output": [
            {
                "type": "message",
                "id": "m",
                "status": "completed",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "ok", "annotations": []}],
            }
        ],
        "usage": {
            "input_tokens": 9_250,
            "output_tokens": 7,
            "input_tokens_details": {"cached_tokens": 9_000, "cache_write_tokens": 200},
        },
    }
    provider = OpenAIProvider("k", "gpt-6.1-sol", client=_client(body, []))

    assert (await provider.complete([Message(Role.USER, "hi")])).usage == _CACHED


def test_chatgpt_reports_the_cached_and_written_part_of_its_prompt() -> None:
    last = SimpleNamespace(
        input_tokens=9_250,
        cached_input_tokens=9_000,
        cache_write_input_tokens=200,
        output_tokens=7,
    )
    assert chatgpt_usage(SimpleNamespace(last=last)) == _CACHED

    # A runtime that reports no write count.
    older = SimpleNamespace(
        input_tokens=9_250,
        cached_input_tokens=9_000,
        cache_write_input_tokens=None,
        output_tokens=7,
    )
    assert chatgpt_usage(SimpleNamespace(last=older)) == TokenUsage(
        9_250, 7, cache_read_tokens=9_000
    )
