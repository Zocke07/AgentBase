"""Tests for the three provider implementations and the factory.

**Nothing here touches the network.** Every request is served by an
`httpx2.MockTransport`, which also lets each test assert the exact request body
that *would* have gone out — the vendor shape is the thing most likely to be
wrong, and it is invisible if you only assert on the parsed response.

The recurring theme is normalization: the same logical response, expressed
three different ways by three vendors, must produce the same `Completion`. If
these tests pass but a caller still has to know which provider it holds, the
Phase 3 acceptance criterion is not met regardless of what the tests say.
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
    TokenUsage,
    ToolSpec,
)
from agentspace.providers.factory import (
    SUPPORTED_PROVIDERS,
    UnknownProviderError,
    build_provider,
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
    """Omitting it is a 400 — unlike OpenAI, where it defaults."""
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
    """Callers above this layer branch on these, never on a vendor code — that
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


async def test_switching_provider_is_only_a_settings_change() -> None:
    """BUILD_SPEC §5 Phase 3, acceptance criterion, first clause.

    The same call site, the same types, no branch on provider anywhere — only
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
