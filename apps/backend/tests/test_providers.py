"""Tests for the three provider implementations and the factory.

Nothing touches the network: every request is served by an
`httpx2.MockTransport`, which also lets each test assert the exact request
body that would have gone out. The theme is normalization: three vendors'
shapes must produce the same `Completion`.
"""

from __future__ import annotations

import json
from typing import Any

import httpx2
import pytest

from agentspace.providers.anthropic import ANTHROPIC_VERSION, AnthropicProvider
from agentspace.providers.base import (
    Completion,
    Message,
    Provider,
    ProviderAuthError,
    ProviderError,
    ProviderRateLimitedError,
    ProviderUnavailableError,
    Role,
    TextDelta,
    TokenUsage,
    ToolSpec,
)
from agentspace.providers.factory import (
    SUPPORTED_PROVIDERS,
    UnknownProviderError,
    build_provider,
    qualified_model,
)
from agentspace.providers.ollama import OllamaProvider
from agentspace.providers.openai import OpenAIProvider
from agentspace.secrets import SecretStore
from agentspace.store.settings import WorkspaceSettings

pytestmark = pytest.mark.anyio


class Captured:
    """Records the single request a provider made."""

    def __init__(self) -> None:
        self.request: httpx2.Request | None = None

    @property
    def body(self) -> dict[str, Any]:
        assert self.request is not None, "no request was made"
        parsed: dict[str, Any] = json.loads(self.request.content)
        return parsed

    @property
    def headers(self) -> httpx2.Headers:
        assert self.request is not None, "no request was made"
        return self.request.headers


def mock_client(
    response_body: dict[str, Any] | None = None,
    status: int = 200,
    captured: Captured | None = None,
    headers: dict[str, str] | None = None,
    raises: Exception | None = None,
) -> httpx2.AsyncClient:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if captured is not None:
            captured.request = request
        if raises is not None:
            raise raises
        return httpx2.Response(
            status, json=response_body if response_body is not None else {}, headers=headers
        )

    return httpx2.AsyncClient(transport=httpx2.MockTransport(handler))


# --- Anthropic ---------------------------------------------------------------

ANTHROPIC_OK: dict[str, Any] = {
    "model": "claude-opus-5",
    "content": [{"type": "text", "text": "Hello there."}],
    "stop_reason": "end_turn",
    "usage": {"input_tokens": 12, "output_tokens": 5},
}


async def test_anthropic_normalizes_a_text_response() -> None:
    provider = AnthropicProvider(
        "fake-anthropic-key", "claude-opus-5", client=mock_client(ANTHROPIC_OK)
    )

    result = await provider.complete([Message(role=Role.USER, content="hi")])

    assert result.provider == "anthropic"
    assert result.model == "claude-opus-5"
    assert result.text == "Hello there."
    assert result.usage == TokenUsage(input_tokens=12, output_tokens=5)
    assert result.stop_reason == "end_turn"


async def test_anthropic_exposes_thinking_blocks_beside_the_text() -> None:
    """Extended thinking arrives as its own content blocks. They are not the
    answer and stay out of `text`; they are not dropped either."""
    provider = AnthropicProvider(
        api_key="k",
        model="claude-opus-5",
        client=mock_client(
            {
                "id": "msg_1",
                "model": "claude-opus-5",
                "content": [
                    {
                        "type": "thinking",
                        "thinking": "Two lines, then a third.",
                        "signature": "s",
                    },
                    {"type": "text", "text": "Here is a haiku."},
                ],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 10, "output_tokens": 30},
            }
        ),
    )

    result = await provider.complete([Message(role=Role.USER, content="haiku")])

    assert result.text == "Here is a haiku."
    assert result.thinking == "Two lines, then a third."


async def test_anthropic_sends_the_documented_headers() -> None:
    captured = Captured()
    provider = AnthropicProvider(
        "fake-anthropic-key",
        "claude-opus-5",
        client=mock_client(ANTHROPIC_OK, captured=captured),
    )

    await provider.complete([Message(role=Role.USER, content="hi")])

    assert captured.headers["x-api-key"] == "fake-anthropic-key"
    assert captured.headers["anthropic-version"] == ANTHROPIC_VERSION


async def test_anthropic_lifts_the_system_prompt_out_of_messages() -> None:
    """Anthropic 400s on a `system` role inside `messages`. The neutral
    protocol allows one, so the adapter has to move it."""
    captured = Captured()
    provider = AnthropicProvider(
        "k", "claude-opus-5", client=mock_client(ANTHROPIC_OK, captured=captured)
    )

    await provider.complete(
        [
            Message(role=Role.SYSTEM, content="Be terse."),
            Message(role=Role.USER, content="hi"),
        ]
    )

    body = captured.body
    assert body["system"] == "Be terse."
    assert [turn["role"] for turn in body["messages"]] == ["user"]


async def test_anthropic_merges_the_system_argument_and_system_messages() -> None:
    captured = Captured()
    provider = AnthropicProvider(
        "k", "claude-opus-5", client=mock_client(ANTHROPIC_OK, captured=captured)
    )

    await provider.complete(
        [Message(role=Role.SYSTEM, content="Second.")],
        system="First.",
    )

    assert captured.body["system"] == "First.\n\nSecond."


async def test_anthropic_always_sends_max_tokens() -> None:
    """Omitting it is a 400, unlike OpenAI, where it defaults."""
    captured = Captured()
    provider = AnthropicProvider(
        "k", "claude-opus-5", client=mock_client(ANTHROPIC_OK, captured=captured)
    )

    await provider.complete([Message(role=Role.USER, content="hi")], max_tokens=99)

    assert captured.body["max_tokens"] == 99


async def test_anthropic_normalizes_tool_calls() -> None:
    body = {
        "model": "claude-opus-5",
        "content": [
            {"type": "text", "text": "Let me read that."},
            {
                "type": "tool_use",
                "id": "toolu_1",
                "name": "read_file",
                "input": {"path": "q3.md"},
            },
        ],
        "stop_reason": "tool_use",
        "usage": {"input_tokens": 20, "output_tokens": 8},
    }
    provider = AnthropicProvider("k", "claude-opus-5", client=mock_client(body))

    result = await provider.complete([Message(role=Role.USER, content="read q3")])

    assert result.text == "Let me read that."
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].name == "read_file"
    assert result.tool_calls[0].arguments == {"path": "q3.md"}
    assert result.tool_calls[0].id == "toolu_1"


async def test_anthropic_sends_tools_in_its_own_schema() -> None:
    captured = Captured()
    provider = AnthropicProvider(
        "k", "claude-opus-5", client=mock_client(ANTHROPIC_OK, captured=captured)
    )

    await provider.complete(
        [Message(role=Role.USER, content="hi")],
        [
            ToolSpec(
                name="read_file", description="Read a file", input_schema={"type": "object"}
            )
        ],
    )

    tool = captured.body["tools"][0]
    assert tool["name"] == "read_file"
    assert tool["input_schema"] == {"type": "object"}


async def test_anthropic_refuses_without_a_key_before_making_a_request() -> None:
    captured = Captured()
    provider = AnthropicProvider("", "claude-opus-5", client=mock_client(captured=captured))

    with pytest.raises(ProviderAuthError):
        await provider.complete([Message(role=Role.USER, content="hi")])

    assert captured.request is None


# --- OpenAI ------------------------------------------------------------------

OPENAI_OK: dict[str, Any] = {
    "model": "gpt-5.4",
    "choices": [
        {"message": {"role": "assistant", "content": "Hello there."}, "finish_reason": "stop"}
    ],
    "usage": {"prompt_tokens": 12, "completion_tokens": 5},
}


async def test_openai_normalizes_a_text_response() -> None:
    provider = OpenAIProvider("fake-openai-key", "gpt-5.4", client=mock_client(OPENAI_OK))

    result = await provider.complete([Message(role=Role.USER, content="hi")])

    assert result.provider == "openai"
    assert result.text == "Hello there."
    assert result.usage == TokenUsage(input_tokens=12, output_tokens=5)
    assert result.stop_reason == "stop"


async def test_openai_maps_its_own_usage_field_names() -> None:
    """`prompt_tokens`/`completion_tokens` vs Anthropic's
    `input_tokens`/`output_tokens`. The ledger only ever sees TokenUsage."""
    provider = OpenAIProvider("k", "gpt-5.4", client=mock_client(OPENAI_OK))

    result = await provider.complete([Message(role=Role.USER, content="hi")])

    assert result.usage.input_tokens == 12
    assert result.usage.output_tokens == 5


async def test_openai_keeps_the_system_prompt_as_a_message() -> None:
    """The mirror image of the Anthropic case."""
    captured = Captured()
    provider = OpenAIProvider("k", "gpt-5.4", client=mock_client(OPENAI_OK, captured=captured))

    await provider.complete([Message(role=Role.USER, content="hi")], system="Be terse.")

    turns = captured.body["messages"]
    assert turns[0] == {"role": "system", "content": "Be terse."}


async def test_openai_parses_tool_arguments_from_a_json_string() -> None:
    """OpenAI encodes arguments as a string; Anthropic and Ollama send an
    object. Callers must never see the difference."""
    body = {
        "model": "gpt-5.4",
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "read_file",
                                "arguments": '{"path": "q3.md"}',
                            },
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    }
    provider = OpenAIProvider("k", "gpt-5.4", client=mock_client(body))

    result = await provider.complete([Message(role=Role.USER, content="read q3")])

    assert result.text == ""
    assert result.tool_calls[0].arguments == {"path": "q3.md"}


async def test_openai_survives_unparseable_tool_arguments() -> None:
    """A model can emit invalid JSON. That is a bad tool call for the approval
    gate to reject, not a crashed run."""
    body = {
        "model": "gpt-5.4",
        "choices": [
            {
                "message": {
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "function": {"name": "read_file", "arguments": "{not json"},
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {},
    }
    provider = OpenAIProvider("k", "gpt-5.4", client=mock_client(body))

    result = await provider.complete([Message(role=Role.USER, content="x")])

    assert result.tool_calls[0].name == "read_file"
    assert result.tool_calls[0].arguments == {}


async def test_openai_sends_a_bearer_token() -> None:
    captured = Captured()
    provider = OpenAIProvider(
        "fake-openai-key", "gpt-5.4", client=mock_client(OPENAI_OK, captured=captured)
    )

    await provider.complete([Message(role=Role.USER, content="hi")])

    assert captured.headers["authorization"] == "Bearer fake-openai-key"


# --- Ollama ------------------------------------------------------------------

OLLAMA_OK: dict[str, Any] = {
    "model": "llama3.3",
    "message": {"role": "assistant", "content": "Hello there."},
    "done_reason": "stop",
    "prompt_eval_count": 12,
    "eval_count": 5,
}


async def test_ollama_normalizes_a_text_response() -> None:
    provider = OllamaProvider("llama3.3", client=mock_client(OLLAMA_OK))

    result = await provider.complete([Message(role=Role.USER, content="hi")])

    assert result.provider == "ollama"
    assert result.text == "Hello there."
    assert result.usage == TokenUsage(input_tokens=12, output_tokens=5)


async def test_ollama_exposes_thinking_beside_the_answer() -> None:
    """Phase 5 watched `qwen3:4b` return empty content and no tool call five
    times running, with the whole response in Ollama's separate
    `message.thinking` field, and the adapter dropped it, so the log said
    the model produced nothing. It said a great deal; it was just not the
    answer. Reasoning is not output, so it stays out of `text`; it travels
    beside it so the log can tell silence from thought."""
    provider = OllamaProvider(
        "qwen3:4b",
        client=mock_client(
            {
                "model": "qwen3:4b",
                "message": {
                    "role": "assistant",
                    "content": "",
                    "thinking": "The user wants a file written but I have no such tool.",
                },
                "done_reason": "stop",
                "prompt_eval_count": 40,
                "eval_count": 60,
            }
        ),
    )

    result = await provider.complete([Message(role=Role.USER, content="write it")])

    assert result.text == ""
    assert result.thinking == "The user wants a file written but I have no such tool."


async def test_a_completion_with_no_reasoning_has_none_not_empty() -> None:
    """`None` is "the provider exposed nothing"; `""` would be "it reasoned
    and said nothing", and the log should not have to guess which."""
    provider = OllamaProvider("llama3.3", client=mock_client(OLLAMA_OK))

    result = await provider.complete([Message(role=Role.USER, content="hi")])

    assert result.thinking is None


async def test_ollama_namespaces_the_model_so_pricing_sees_it_as_local() -> None:
    """`pricing` resolves any `ollama/` model to zero cost. Without the prefix
    a local model would raise UnknownModelError and be refused."""
    provider = OllamaProvider("llama3.3")

    assert provider.model == "ollama/llama3.3"
    assert provider.remote_model == "llama3.3"


async def test_ollama_sends_the_unprefixed_name_to_the_daemon() -> None:
    """The daemon has never heard of our namespace."""
    captured = Captured()
    provider = OllamaProvider(
        "ollama/llama3.3", client=mock_client(OLLAMA_OK, captured=captured)
    )

    await provider.complete([Message(role=Role.USER, content="hi")])

    assert captured.body["model"] == "llama3.3"


async def test_ollama_sends_no_authorization_header() -> None:
    """The point of this provider: the protocol must not assume cloud (§7)."""
    captured = Captured()
    provider = OllamaProvider("llama3.3", client=mock_client(OLLAMA_OK, captured=captured))

    await provider.complete([Message(role=Role.USER, content="hi")])

    assert "authorization" not in captured.headers


async def test_ollama_disables_streaming() -> None:
    """A streamed body would arrive as newline-delimited JSON and break the
    single-Completion contract."""
    captured = Captured()
    provider = OllamaProvider("llama3.3", client=mock_client(OLLAMA_OK, captured=captured))

    await provider.complete([Message(role=Role.USER, content="hi")])

    assert captured.body["stream"] is False


# --- normalization across all three -----------------------------------------


@pytest.mark.parametrize(
    "provider",
    [
        AnthropicProvider("k", "claude-opus-5", client=mock_client(ANTHROPIC_OK)),
        OpenAIProvider("k", "gpt-5.4", client=mock_client(OPENAI_OK)),
        OllamaProvider("llama3.3", client=mock_client(OLLAMA_OK)),
    ],
    ids=["anthropic", "openai", "ollama"],
)
async def test_all_providers_produce_the_same_normalized_shape(
    provider: Provider,
) -> None:
    """The criterion, expressed as a test: three vendors, one result shape."""
    result = await provider.complete([Message(role=Role.USER, content="hi")])

    assert isinstance(result, Completion)
    assert result.text == "Hello there."
    assert result.usage.input_tokens == 12
    assert result.usage.output_tokens == 5


async def test_every_provider_satisfies_the_protocol() -> None:
    for provider in (
        AnthropicProvider("k", "claude-opus-5"),
        OpenAIProvider("k", "gpt-5.4"),
        OllamaProvider("llama3.3"),
    ):
        assert isinstance(provider, Provider)


# --- error taxonomy ----------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, ProviderAuthError),
        (403, ProviderAuthError),
        (429, ProviderRateLimitedError),
        (500, ProviderUnavailableError),
        (503, ProviderUnavailableError),
        (400, ProviderError),
    ],
)
async def test_http_status_maps_to_the_shared_error_taxonomy(
    status: int, expected: type[Exception]
) -> None:
    """Callers above this layer branch on these, never on a vendor code, that
    would be a code change when switching provider."""
    provider = AnthropicProvider(
        "k",
        "claude-opus-5",
        client=mock_client({"error": {"message": "nope"}}, status=status),
    )

    with pytest.raises(expected):
        await provider.complete([Message(role=Role.USER, content="hi")])


async def test_rate_limit_carries_retry_after() -> None:
    provider = OpenAIProvider(
        "k",
        "gpt-5.4",
        client=mock_client(
            {"error": {"message": "slow down"}}, 429, headers={"retry-after": "30"}
        ),
    )

    with pytest.raises(ProviderRateLimitedError) as excinfo:
        await provider.complete([Message(role=Role.USER, content="hi")])

    assert excinfo.value.retry_after_seconds == 30.0


async def test_a_transport_failure_becomes_provider_unavailable() -> None:
    """An httpx2 exception escaping would couple every caller to this module's
    choice of HTTP client."""
    provider = OpenAIProvider(
        "k", "gpt-5.4", client=mock_client(raises=httpx2.ConnectError("refused"))
    )

    with pytest.raises(ProviderUnavailableError):
        await provider.complete([Message(role=Role.USER, content="hi")])


async def test_a_timeout_becomes_provider_unavailable() -> None:
    provider = OpenAIProvider(
        "k", "gpt-5.4", client=mock_client(raises=httpx2.TimeoutException("slow"))
    )

    with pytest.raises(ProviderUnavailableError):
        await provider.complete([Message(role=Role.USER, content="hi")])


async def test_the_error_message_carries_the_vendor_reason() -> None:
    """Whatever the vendor said has to survive to the user, or a misconfigured
    key looks identical to an outage."""
    provider = AnthropicProvider(
        "k",
        "claude-opus-5",
        client=mock_client({"error": {"message": "credit balance too low"}}, status=400),
    )

    with pytest.raises(ProviderError, match="credit balance too low"):
        await provider.complete([Message(role=Role.USER, content="hi")])


async def test_a_non_json_error_body_does_not_mask_the_status() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        return httpx2.Response(502, text="<html>Bad Gateway</html>")

    provider = OpenAIProvider(
        "k", "gpt-5.4", client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    )

    with pytest.raises(ProviderUnavailableError, match="502"):
        await provider.complete([Message(role=Role.USER, content="hi")])


# --- the factory: switching provider is a settings change --------------------


async def test_the_factory_builds_each_supported_provider() -> None:
    secrets = SecretStore({"anthropic_api_key": "a", "openai_api_key": "o"})

    for name, model in (
        ("anthropic", "claude-opus-5"),
        ("openai", "gpt-5.4"),
        ("ollama", "llama3.3"),
    ):
        provider = build_provider(WorkspaceSettings(provider=name, model=model), secrets)
        assert provider.name == name


async def test_qualified_model_is_what_the_built_provider_reports() -> None:
    """The two must agree, structurally, for every provider.

    `qualified_model` exists so a caller can ask a question about the model a
    run will be *billed* for without building a provider: `GET /settings` has
    no credentials to build one with. That makes it a second copy of a naming
    rule, and a second copy is a copy that drifts: pricing an Ollama model under
    its raw name rather than `ollama/<name>` is the bug this function was added
    to fix. Comparing it to the real provider is what stops the next provider
    with a naming rule of its own repeating it.
    """
    secrets = SecretStore({"anthropic_api_key": "a", "openai_api_key": "o"})

    for name, model in (
        ("anthropic", "claude-opus-5"),
        ("openai", "gpt-5.4"),
        ("ollama", "llama3.3"),
        # Already namespaced: qualifying twice would produce `ollama/ollama/x`.
        ("ollama", "ollama/llama3.3"),
    ):
        settings = WorkspaceSettings(provider=name, model=model)
        provider = build_provider(settings, secrets)

        assert qualified_model(name, model) == provider.model


async def test_switching_provider_is_only_a_settings_change() -> None:
    """BUILD_SPEC §5 Phase 3, acceptance criterion, first clause.

    The same call site, the same types, no branch on provider anywhere, only
    the stored settings differ.
    """
    secrets = SecretStore({"anthropic_api_key": "a", "openai_api_key": "o"})

    first = build_provider(
        WorkspaceSettings(provider="anthropic", model="claude-opus-5"), secrets
    )
    second = build_provider(WorkspaceSettings(provider="openai", model="gpt-5.4"), secrets)

    assert first.name == "anthropic"
    assert second.name == "openai"
    assert isinstance(first, Provider)
    assert isinstance(second, Provider)


async def test_the_factory_rejects_an_unknown_provider() -> None:
    with pytest.raises(UnknownProviderError, match="anthropic, ollama, openai"):
        build_provider(WorkspaceSettings(provider="hal9000"), SecretStore())


async def test_the_factory_reports_a_missing_key_before_any_request() -> None:
    """A missing key must not surface later as an opaque vendor 401."""
    with pytest.raises(ProviderAuthError, match="restarted"):
        build_provider(WorkspaceSettings(provider="anthropic"), SecretStore())


async def test_ollama_needs_no_key_at_all() -> None:
    """If this ever requires a secret, the abstraction has grown a cloud
    assumption."""
    provider = build_provider(
        WorkspaceSettings(provider="ollama", model="llama3.3"), SecretStore()
    )

    assert provider.name == "ollama"


async def test_the_supported_provider_table_matches_the_spec() -> None:
    """§5 Phase 3 names exactly these three."""
    assert set(SUPPORTED_PROVIDERS) == {"anthropic", "openai", "ollama"}
    assert SUPPORTED_PROVIDERS["ollama"] is None


# --- streaming ---------------------------------------------------------------
#
# Phase 4 streams by default, so these shapes are the ones that actually run.
# The recurring assertion is *equivalence*: the `Completion` that ends a stream
# must equal the one `complete()` returns for the same logical response. If the
# two diverge, choosing to stream becomes a behavioural change and the
# orchestrator has to know which path it took, which is the Phase 3 acceptance
# criterion failing by a side door.


def mock_stream_client(
    body: str,
    status: int = 200,
    captured: Captured | None = None,
) -> httpx2.AsyncClient:
    """A client whose response body is delivered as a stream."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        if captured is not None:
            captured.request = request
        return httpx2.Response(status, content=body.encode())

    return httpx2.AsyncClient(transport=httpx2.MockTransport(handler))


async def collect(provider: Provider, **kwargs: Any) -> tuple[list[str], Completion]:
    """Drain a stream into its text deltas and its terminal completion."""
    deltas: list[str] = []
    terminal: Completion | None = None

    async for event in provider.stream([Message(role=Role.USER, content="hi")], **kwargs):
        if isinstance(event, TextDelta):
            assert terminal is None, "a delta arrived after the terminal completion"
            deltas.append(event.text)
        else:
            assert terminal is None, "more than one completion was yielded"
            terminal = event

    assert terminal is not None, "the stream ended without a terminal completion"
    return deltas, terminal


ANTHROPIC_STREAM = "\n".join(
    [
        "event: message_start",
        'data: {"type":"message_start","message":{"id":"msg_1",'
        '"model":"claude-opus-5","usage":{"input_tokens":25,"output_tokens":1}}}',
        "",
        "event: content_block_start",
        'data: {"type":"content_block_start","index":0,'
        '"content_block":{"type":"text","text":""}}',
        "",
        "event: ping",
        'data: {"type":"ping"}',
        "",
        "event: content_block_delta",
        'data: {"type":"content_block_delta","index":0,'
        '"delta":{"type":"text_delta","text":"Hello"}}',
        "",
        "event: content_block_delta",
        'data: {"type":"content_block_delta","index":0,'
        '"delta":{"type":"text_delta","text":" there."}}',
        "",
        "event: content_block_stop",
        'data: {"type":"content_block_stop","index":0}',
        "",
        "event: message_delta",
        'data: {"type":"message_delta","delta":{"stop_reason":"end_turn"},'
        '"usage":{"output_tokens":15}}',
        "",
        "event: message_stop",
        'data: {"type":"message_stop"}',
        "",
    ]
)


async def test_anthropic_stream_yields_deltas_then_a_completion() -> None:
    provider = AnthropicProvider(
        api_key="test-key", model="claude-opus-5", client=mock_stream_client(ANTHROPIC_STREAM)
    )

    deltas, completion = await collect(provider)

    assert deltas == ["Hello", " there."]
    assert completion.text == "Hello there."
    assert completion.stop_reason == "end_turn"


async def test_anthropic_stream_takes_input_tokens_from_start_and_output_from_the_end() -> None:
    """The counts live in two different frames.

    `message_start` reports `output_tokens: 1`: a placeholder, not the answer.
    Reading usage from that frame alone would bill 15 output tokens as 1 and
    quietly under-count every streamed call against the cap.
    """
    provider = AnthropicProvider(
        api_key="test-key", model="claude-opus-5", client=mock_stream_client(ANTHROPIC_STREAM)
    )

    _, completion = await collect(provider)

    assert completion.usage == TokenUsage(input_tokens=25, output_tokens=15)


async def test_anthropic_stream_sets_the_stream_flag_and_keeps_the_blocking_body() -> None:
    captured = Captured()
    provider = AnthropicProvider(
        api_key="test-key",
        model="claude-opus-5",
        client=mock_stream_client(ANTHROPIC_STREAM, captured=captured),
    )

    await collect(provider, tools=[ToolSpec(name="read_file", description="Read a file")])

    body = captured.body
    assert body["stream"] is True
    # Everything else must match what `complete` would have sent.
    assert body["model"] == "claude-opus-5"
    assert body["messages"] == [{"role": "user", "content": "hi"}]
    assert body["tools"][0]["name"] == "read_file"
    assert captured.headers["anthropic-version"] == ANTHROPIC_VERSION


async def test_anthropic_stream_folds_thinking_deltas_without_yielding_them() -> None:
    body = "\n".join(
        [
            "event: message_start",
            'data: {"type":"message_start","message":{"id":"msg_1",'
            '"model":"claude-opus-5","usage":{"input_tokens":25,"output_tokens":1}}}',
            "",
            "event: content_block_start",
            'data: {"type":"content_block_start","index":0,'
            '"content_block":{"type":"thinking","thinking":""}}',
            "",
            "event: content_block_delta",
            'data: {"type":"content_block_delta","index":0,'
            '"delta":{"type":"thinking_delta","thinking":"Let me "}}',
            "",
            "event: content_block_delta",
            'data: {"type":"content_block_delta","index":0,'
            '"delta":{"type":"thinking_delta","thinking":"count."}}',
            "",
            "event: content_block_delta",
            'data: {"type":"content_block_delta","index":0,'
            '"delta":{"type":"signature_delta","signature":"abc"}}',
            "",
            "event: content_block_stop",
            'data: {"type":"content_block_stop","index":0}',
            "",
            "event: content_block_start",
            'data: {"type":"content_block_start","index":1,'
            '"content_block":{"type":"text","text":""}}',
            "",
            "event: content_block_delta",
            'data: {"type":"content_block_delta","index":1,'
            '"delta":{"type":"text_delta","text":"Five."}}',
            "",
            "event: message_delta",
            'data: {"type":"message_delta","delta":{"stop_reason":"end_turn"},'
            '"usage":{"output_tokens":9}}',
            "",
            "event: message_stop",
            'data: {"type":"message_stop"}',
            "",
        ]
    )
    provider = AnthropicProvider(
        api_key="k", model="claude-opus-5", client=mock_stream_client(body)
    )

    deltas, completion = await collect(provider)

    assert deltas == ["Five."]
    assert completion.text == "Five."
    assert completion.thinking == "Let me count."


async def test_anthropic_stream_reassembles_a_tool_call_from_json_fragments() -> None:
    """`input_json_delta` arrives as slices of a JSON string, not as an object.

    A single fragment is never valid JSON on its own, so an adapter that tried
    to parse each one would produce no tool call at all.
    """
    body = "\n".join(
        [
            'data: {"type":"message_start","message":{"model":"claude-opus-5",'
            '"usage":{"input_tokens":10,"output_tokens":0}}}',
            "",
            'data: {"type":"content_block_start","index":0,"content_block":'
            '{"type":"tool_use","id":"toolu_1","name":"read_file","input":{}}}',
            "",
            'data: {"type":"content_block_delta","index":0,"delta":'
            '{"type":"input_json_delta","partial_json":"{\\"path\\":"}}',
            "",
            'data: {"type":"content_block_delta","index":0,"delta":'
            '{"type":"input_json_delta","partial_json":" \\"q3.md\\"}"}}',
            "",
            'data: {"type":"message_delta","delta":{"stop_reason":"tool_use"},'
            '"usage":{"output_tokens":20}}',
            "",
        ]
    )
    provider = AnthropicProvider(
        api_key="test-key", model="claude-opus-5", client=mock_stream_client(body)
    )

    deltas, completion = await collect(provider)

    assert deltas == [], "tool arguments are not text deltas"
    assert len(completion.tool_calls) == 1
    call = completion.tool_calls[0]
    assert call.id == "toolu_1"
    assert call.name == "read_file"
    assert call.arguments == {"path": "q3.md"}
    assert completion.stop_reason == "tool_use"


async def test_anthropic_stream_matches_the_blocking_call() -> None:
    """The protocol's equivalence guarantee, asserted rather than assumed."""
    blocking = AnthropicProvider(
        api_key="test-key",
        model="claude-opus-5",
        client=mock_client(
            {
                "model": "claude-opus-5",
                "content": [{"type": "text", "text": "Hello there."}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 25, "output_tokens": 15},
            }
        ),
    )
    streaming = AnthropicProvider(
        api_key="test-key", model="claude-opus-5", client=mock_stream_client(ANTHROPIC_STREAM)
    )

    expected = await blocking.complete([Message(role=Role.USER, content="hi")])
    _, actual = await collect(streaming)

    assert actual == expected


async def test_anthropic_raises_on_an_error_frame_after_a_200() -> None:
    """Anthropic can fail *after* the status line.

    Returning the truncated text instead would charge for a response that never
    finished and hand the orchestrator a silently incomplete answer.
    """
    body = "\n".join(
        [
            'data: {"type":"message_start","message":{"model":"claude-opus-5",'
            '"usage":{"input_tokens":10,"output_tokens":0}}}',
            "",
            'data: {"type":"content_block_delta","index":0,"delta":'
            '{"type":"text_delta","text":"Partial"}}',
            "",
            'data: {"type":"error","error":{"type":"overloaded_error","message":"Overloaded"}}',
            "",
        ]
    )
    provider = AnthropicProvider(
        api_key="test-key", model="claude-opus-5", client=mock_stream_client(body)
    )

    with pytest.raises(ProviderError, match="Overloaded"):
        await collect(provider)


OPENAI_STREAM = "\n".join(
    [
        'data: {"id":"c1","model":"gpt-5","choices":[{"index":0,'
        '"delta":{"role":"assistant","content":""},"finish_reason":null}]}',
        "",
        'data: {"id":"c1","model":"gpt-5","choices":[{"index":0,'
        '"delta":{"content":"Hello"},"finish_reason":null}]}',
        "",
        'data: {"id":"c1","model":"gpt-5","choices":[{"index":0,'
        '"delta":{"content":" there."},"finish_reason":null}]}',
        "",
        'data: {"id":"c1","model":"gpt-5","choices":[{"index":0,'
        '"delta":{},"finish_reason":"stop"}]}',
        "",
        'data: {"id":"c1","model":"gpt-5","choices":[],'
        '"usage":{"prompt_tokens":25,"completion_tokens":15}}',
        "",
        "data: [DONE]",
        "",
    ]
)


async def test_openai_stream_yields_deltas_then_a_completion() -> None:
    provider = OpenAIProvider(
        api_key="test-key", model="gpt-5", client=mock_stream_client(OPENAI_STREAM)
    )

    deltas, completion = await collect(provider)

    assert deltas == ["Hello", " there."]
    assert completion.text == "Hello there."
    assert completion.stop_reason == "stop"
    assert completion.usage == TokenUsage(input_tokens=25, output_tokens=15)


async def test_openai_stream_requests_usage_explicitly() -> None:
    """Without `stream_options.include_usage` a streamed response reports no
    token counts at all: every call would be recorded as free and the monthly
    cap would silently stop binding."""
    captured = Captured()
    provider = OpenAIProvider(
        api_key="test-key",
        model="gpt-5",
        client=mock_stream_client(OPENAI_STREAM, captured=captured),
    )

    await collect(provider)

    body = captured.body
    assert body["stream"] is True
    assert body["stream_options"] == {"include_usage": True}


async def test_openai_stream_survives_the_usage_chunks_empty_choices() -> None:
    """The frame carrying the token counts has `choices: []`.

    Reading `choices[0]` unconditionally raises on precisely the one chunk the
    budget ledger depends on.
    """
    provider = OpenAIProvider(
        api_key="test-key", model="gpt-5", client=mock_stream_client(OPENAI_STREAM)
    )

    _, completion = await collect(provider)

    assert completion.usage.total_tokens == 40


async def test_openai_stream_accumulates_tool_calls_by_index() -> None:
    """Only the first chunk of a tool call carries its id and name.

    Later chunks have an `index` and another slice of the argument string, so
    keying on anything but `index` loses the name or merges parallel calls.
    """
    body = "\n".join(
        [
            'data: {"id":"c1","model":"gpt-5","choices":[{"index":0,"delta":'
            '{"tool_calls":[{"index":0,"id":"call_1","type":"function",'
            '"function":{"name":"read_file","arguments":""}}]}}]}',
            "",
            'data: {"id":"c1","model":"gpt-5","choices":[{"index":0,"delta":'
            '{"tool_calls":[{"index":0,"function":{"arguments":"{\\"path\\":"}}]}}]}',
            "",
            'data: {"id":"c1","model":"gpt-5","choices":[{"index":0,"delta":'
            '{"tool_calls":[{"index":0,"function":{"arguments":" \\"q3.md\\"}"}}]}}]}',
            "",
            'data: {"id":"c1","model":"gpt-5","choices":[{"index":0,"delta":{},'
            '"finish_reason":"tool_calls"}]}',
            "",
            'data: {"id":"c1","model":"gpt-5","choices":[],'
            '"usage":{"prompt_tokens":30,"completion_tokens":20}}',
            "",
            "data: [DONE]",
            "",
        ]
    )
    provider = OpenAIProvider(
        api_key="test-key", model="gpt-5", client=mock_stream_client(body)
    )

    _, completion = await collect(provider)

    assert len(completion.tool_calls) == 1
    call = completion.tool_calls[0]
    assert call.id == "call_1"
    assert call.name == "read_file"
    assert call.arguments == {"path": "q3.md"}


async def test_openai_stream_matches_the_blocking_call() -> None:
    blocking = OpenAIProvider(
        api_key="test-key",
        model="gpt-5",
        client=mock_client(
            {
                "model": "gpt-5",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "Hello there."},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 25, "completion_tokens": 15},
            }
        ),
    )
    streaming = OpenAIProvider(
        api_key="test-key", model="gpt-5", client=mock_stream_client(OPENAI_STREAM)
    )

    expected = await blocking.complete([Message(role=Role.USER, content="hi")])
    _, actual = await collect(streaming)

    assert actual == expected


OLLAMA_STREAM = "\n".join(
    [
        '{"model":"llama3","message":{"role":"assistant","content":"Hello"},"done":false}',
        '{"model":"llama3","message":{"role":"assistant","content":" there."},"done":false}',
        '{"model":"llama3","message":{"role":"assistant","content":""},"done":true,'
        '"done_reason":"stop","prompt_eval_count":25,"eval_count":15}',
        "",
    ]
)


async def test_ollama_streams_newline_delimited_json_not_sse() -> None:
    """Ollama has no `data:` prefix and no blank-line framing.

    An SSE reader pointed at this body finds no lines it recognises and yields
    an empty response, with no error anywhere, which is the failure mode this
    test exists to prevent.
    """
    provider = OllamaProvider(model="llama3", client=mock_stream_client(OLLAMA_STREAM))

    deltas, completion = await collect(provider)

    assert deltas == ["Hello", " there."]
    assert completion.text == "Hello there."
    assert completion.usage == TokenUsage(input_tokens=25, output_tokens=15)
    assert completion.stop_reason == "stop"


async def test_ollama_stream_sets_the_stream_flag() -> None:
    captured = Captured()
    provider = OllamaProvider(
        model="llama3", client=mock_stream_client(OLLAMA_STREAM, captured=captured)
    )

    await collect(provider)

    assert captured.body["stream"] is True
    assert captured.body["model"] == "llama3", "the namespace prefix must not reach the daemon"


async def test_ollama_stream_matches_the_blocking_call() -> None:
    blocking = OllamaProvider(
        model="llama3",
        client=mock_client(
            {
                "model": "llama3",
                "message": {"role": "assistant", "content": "Hello there."},
                "done": True,
                "done_reason": "stop",
                "prompt_eval_count": 25,
                "eval_count": 15,
            }
        ),
    )
    streaming = OllamaProvider(model="llama3", client=mock_stream_client(OLLAMA_STREAM))

    expected = await blocking.complete([Message(role=Role.USER, content="hi")])
    _, actual = await collect(streaming)

    assert actual == expected


async def test_ollama_stream_concatenates_thinking_across_frames() -> None:
    """Streamed, the reasoning arrives a few words per line like the answer
    does, and is folded the same way, never yielded as a `TextDelta`,
    because a delta is the answer being typed and this is not the answer."""
    body = "\n".join(
        [
            '{"model":"qwen3:4b","message":{"role":"assistant","content":"",'
            '"thinking":"First, "},"done":false}',
            '{"model":"qwen3:4b","message":{"role":"assistant","content":"",'
            '"thinking":"count the syllables."},"done":false}',
            '{"model":"qwen3:4b","message":{"role":"assistant","content":"Five."},"done":false}',
            '{"model":"qwen3:4b","message":{"role":"assistant","content":""},"done":true,'
            '"done_reason":"stop","prompt_eval_count":30,"eval_count":20}',
            "",
        ]
    )
    provider = OllamaProvider(model="qwen3:4b", client=mock_stream_client(body))

    deltas, completion = await collect(provider)

    assert deltas == ["Five."]
    assert completion.text == "Five."
    assert completion.thinking == "First, count the syllables."


async def test_ollama_stream_keeps_a_tool_call_a_later_empty_message_would_erase() -> None:
    """The final frame carries an empty message plus the token counts.

    Folding it in naively overwrites the frame that held the tool call, and the
    completion comes back with no tool calls and no error.
    """
    body = "\n".join(
        [
            '{"model":"llama3","message":{"role":"assistant","content":"",'
            '"tool_calls":[{"function":{"name":"read_file",'
            '"arguments":{"path":"q3.md"}}}]},"done":false}',
            '{"model":"llama3","message":{"role":"assistant","content":""},"done":true,'
            '"done_reason":"stop","prompt_eval_count":30,"eval_count":20}',
            "",
        ]
    )
    provider = OllamaProvider(model="llama3", client=mock_stream_client(body))

    _, completion = await collect(provider)

    assert len(completion.tool_calls) == 1
    assert completion.tool_calls[0].name == "read_file"
    assert completion.tool_calls[0].arguments == {"path": "q3.md"}


@pytest.mark.parametrize(
    "provider",
    [
        AnthropicProvider(api_key="k", model="claude-opus-5"),
        OpenAIProvider(api_key="k", model="gpt-5"),
        OllamaProvider(model="llama3"),
    ],
    ids=["anthropic", "openai", "ollama"],
)
def test_every_provider_satisfies_the_protocol_including_stream(provider: Provider) -> None:
    """`runtime_checkable` only checks that the members exist, which is
    exactly the check that matters when a method is added to the protocol and
    one implementation is forgotten."""
    assert isinstance(provider, Provider)
    assert hasattr(provider, "stream")


async def test_a_streamed_auth_failure_reports_the_vendors_reason() -> None:
    """On a streamed response the body is unread when the status arrives.

    Without an explicit read the error detail comes back empty, and a wrong API
    key surfaces as a blank message instead of the vendor's explanation.
    """
    provider = AnthropicProvider(
        api_key="bad-key",
        model="claude-opus-5",
        client=mock_stream_client(
            '{"error":{"type":"authentication_error","message":"invalid x-api-key"}}',
            status=401,
        ),
    )

    with pytest.raises(ProviderAuthError, match="invalid x-api-key"):
        await collect(provider)
