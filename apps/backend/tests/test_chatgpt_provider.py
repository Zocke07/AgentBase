"""ChatGPT subscription access behind the ordinary OpenAI provider contract."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

import pytest
from openai_codex import ApprovalMode, AsyncCodex, Sandbox

from agentbase.providers.base import (
    Completion,
    Message,
    Provider,
    ProviderModelUnavailableError,
    Role,
    TextDelta,
    TokenUsage,
    ToolCall,
    ToolSpec,
)
from agentbase.providers.chatgpt import (
    ChatGPTModelDelta,
    ChatGPTModelResponse,
    ChatGPTSubscriptionProvider,
    CodexAppServerRuntime,
    _decision_prompt,
    _mapped_provider_error,
    _parse_decision,
    _visible_structured_text,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

pytestmark = pytest.mark.anyio


@dataclass
class FakeRuntime:
    response: ChatGPTModelResponse
    stream_events: tuple[ChatGPTModelDelta | ChatGPTModelResponse, ...] = ()
    calls: list[dict[str, object]] = field(default_factory=list)

    async def infer(
        self,
        model: str,
        messages: list[Message],
        tools: list[ToolSpec] | None,
        *,
        system: str | None,
        max_tokens: int,
    ) -> ChatGPTModelResponse:
        self.calls.append(
            {
                "model": model,
                "messages": messages,
                "tools": tools,
                "system": system,
                "max_tokens": max_tokens,
            }
        )
        return self.response

    async def stream_infer(
        self,
        model: str,
        messages: list[Message],
        tools: list[ToolSpec] | None,
        *,
        system: str | None,
        max_tokens: int,
    ) -> AsyncIterator[ChatGPTModelDelta | ChatGPTModelResponse]:
        del model, messages, tools, system, max_tokens
        for event in self.stream_events or (self.response,):
            yield event


async def test_subscription_access_implements_the_same_openai_provider_contract() -> None:
    runtime = FakeRuntime(
        ChatGPTModelResponse(
            model="gpt-5.6-terra",
            text="I will read it.",
            usage=TokenUsage(input_tokens=12, output_tokens=5),
            tool_calls=(ToolCall("codex_turn_1_1", "read_file", {"path": "q3.md"}),),
            stop_reason="tool_calls",
        )
    )
    provider = ChatGPTSubscriptionProvider(runtime, "gpt-5.6-terra")
    messages = [Message(Role.USER, "Read q3.md")]
    tools = [ToolSpec("read_file", "Read a file", {"type": "object"})]

    completion = await provider.complete(messages, tools, system="Be concise.", max_tokens=99)

    assert isinstance(provider, Provider)
    assert completion.provider == "openai"
    assert completion.model == "gpt-5.6-terra"
    assert completion.text == "I will read it."
    assert completion.tool_calls[0].arguments == {"path": "q3.md"}
    assert completion.usage == TokenUsage(input_tokens=12, output_tokens=5)
    assert runtime.calls == [
        {
            "model": "gpt-5.6-terra",
            "messages": messages,
            "tools": tools,
            "system": "Be concise.",
            "max_tokens": 99,
        }
    ]


async def test_subscription_stream_has_the_same_terminal_completion() -> None:
    response = ChatGPTModelResponse(
        model="gpt-5.6-terra",
        text="Hello there.",
        usage=TokenUsage(12, 5),
        stop_reason="stop",
    )
    runtime = FakeRuntime(
        response,
        stream_events=(
            ChatGPTModelDelta("Hello "),
            ChatGPTModelDelta("there."),
            response,
        ),
    )
    provider = ChatGPTSubscriptionProvider(runtime, "gpt-5.6-terra")

    events = [event async for event in provider.stream([Message(Role.USER, "hi")])]

    assert events[:2] == [TextDelta("Hello "), TextDelta("there.")]
    terminal = events[-1]
    assert isinstance(terminal, Completion)
    assert terminal.provider == "openai"
    assert terminal.text == "Hello there."
    assert terminal.usage == TokenUsage(12, 5)


def test_the_transport_prompt_preserves_roles_tool_ids_and_schemas() -> None:
    prompt = _decision_prompt(
        [
            Message(Role.USER, "Read it"),
            Message(Role.ASSISTANT, "Working"),
            Message(Role.TOOL, "contents", tool_call_id="call_1"),
        ],
        [ToolSpec("read_file", "Read a file", {"type": "object"})],
        max_tokens=200,
    )

    assert '"role": "user"' in prompt
    assert '"role": "assistant"' in prompt
    assert '"role": "tool"' in prompt
    assert '"tool_call_id": "call_1"' in prompt
    assert '"name": "read_file"' in prompt
    assert '"max_output_tokens": 200' in prompt


def test_the_transport_prompt_shows_the_call_each_result_answers() -> None:
    """Without its call, GPT-5.6 Luna read config/sources.json until the stuck
    guard stopped it, in two live runs."""
    prompt = _decision_prompt(
        [
            Message(Role.USER, "Read it"),
            Message(
                Role.ASSISTANT,
                "",
                tool_calls=(ToolCall("codex_t_1", "read_file", {"path": "a.md"}),),
            ),
            Message(Role.TOOL, "contents", tool_call_id="codex_t_1"),
        ],
        None,
        max_tokens=200,
    )

    _, _, encoded = prompt.partition("\n\n")
    assert json.loads(encoded)["conversation"][1:] == [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "codex_t_1", "name": "read_file", "arguments": {"path": "a.md"}}
            ],
        },
        {"role": "tool", "content": "contents", "tool_call_id": "codex_t_1"},
    ]


def test_structured_codex_output_becomes_native_tool_calls() -> None:
    parsed = _parse_decision(
        '{"text":"Let me check.","tool_calls":['
        '{"name":"read_file","arguments_json":"{\\"path\\":\\"q3.md\\"}"}]}',
        model="gpt-5.6-terra",
        turn_id="turn_123",
        usage=TokenUsage(20, 8),
    )

    assert parsed.text == "Let me check."
    assert parsed.stop_reason == "tool_calls"
    assert parsed.tool_calls == (ToolCall("codex_turn_123_1", "read_file", {"path": "q3.md"}),)


def test_invalid_structured_output_is_a_provider_error() -> None:
    from agentbase.providers.base import ProviderError

    with pytest.raises(ProviderError, match="structured response"):
        _parse_decision(
            "not json",
            model="gpt-5.6-terra",
            turn_id="turn_123",
            usage=TokenUsage(),
        )


def test_structured_text_stream_decodes_only_complete_user_text() -> None:
    assert _visible_structured_text('{"te') is None
    assert _visible_structured_text('{"text":"Hello\\nwo') == "Hello\nwo"
    assert _visible_structured_text('{"text":"Hi \\uD83D') == "Hi "
    assert _visible_structured_text('{"text":"Hi \\uD83D\\uDC4B') == "Hi 👋"
    assert _visible_structured_text('{"tool_calls":[],"text":"hidden') is None


class _FakeAccount:
    def model_dump(self, *, mode: str) -> dict[str, str]:
        assert mode == "json"
        return {"type": "chatgpt", "email": "person@example.com", "plan_type": "plus"}


class _FakeThread:
    def __init__(self) -> None:
        self.run_kwargs: dict[str, Any] = {}

    async def run(self, prompt: str, **kwargs: Any) -> Any:
        self.run_kwargs = {"prompt": prompt, **kwargs}
        usage = SimpleNamespace(last=SimpleNamespace(input_tokens=31, output_tokens=9))
        return SimpleNamespace(
            final_response=(
                '{"text":"Reading.","tool_calls":['
                '{"name":"read_file","arguments_json":"{\\"path\\":\\"q3.md\\"}"}]}'
            ),
            id="turn_42",
            usage=usage,
        )

    async def turn(self, prompt: str, **kwargs: Any) -> Any:
        self.run_kwargs = {"prompt": prompt, **kwargs}
        return _FakeTurn()


class _FakeTurn:
    id = "turn_43"

    async def stream(self) -> AsyncIterator[Any]:
        encoded = '{"text":"Hello \\uD83D\\uDC4B","tool_calls":[]}'
        for delta in ('{"text":"Hel', "lo \\uD83D", '\\uDC4B","tool_calls":[]}'):
            yield SimpleNamespace(
                method="item/agentMessage/delta",
                payload=SimpleNamespace(item_id="item_1", delta=delta),
            )
        yield SimpleNamespace(
            method="thread/tokenUsage/updated",
            payload=SimpleNamespace(
                token_usage=SimpleNamespace(
                    last=SimpleNamespace(input_tokens=44, output_tokens=11)
                )
            ),
        )
        yield SimpleNamespace(
            method="item/completed",
            payload=SimpleNamespace(
                item=SimpleNamespace(
                    root=SimpleNamespace(
                        text=encoded,
                        phase=SimpleNamespace(value="final_answer"),
                    )
                )
            ),
        )
        yield SimpleNamespace(
            method="turn/completed",
            payload=SimpleNamespace(
                turn=SimpleNamespace(status=SimpleNamespace(value="completed"))
            ),
        )


class _FakeCodex:
    def __init__(self) -> None:
        self.thread = _FakeThread()
        self.thread_kwargs: dict[str, Any] = {}
        self.closed = False
        self.listed: list[str] = ["gpt-6-astra", "gpt-5.6-sol"]
        self.next_cursor: str | None = None
        self.model_calls = 0
        self.model_error: Exception | None = None

    async def models(self, *, include_hidden: bool = False) -> Any:
        self.model_calls += 1
        assert include_hidden is True
        if self.model_error is not None:
            raise self.model_error
        return SimpleNamespace(
            data=[SimpleNamespace(model=name, id=name) for name in self.listed],
            next_cursor=self.next_cursor,
        )

    async def account(self) -> Any:
        return SimpleNamespace(account=_FakeAccount())

    async def thread_start(self, **kwargs: Any) -> Any:
        self.thread_kwargs = kwargs
        return self.thread

    async def close(self) -> None:
        self.closed = True


async def test_codex_runtime_is_a_single_restricted_model_turn(tmp_path: Path) -> None:
    fake = _FakeCodex()
    runtime = CodexAppServerRuntime(tmp_path / "codex", codex=cast(AsyncCodex, fake))

    response = await runtime.infer(
        "gpt-5.6-terra",
        [
            Message(Role.SYSTEM, "Second system rule."),
            Message(Role.USER, "Read q3.md"),
        ],
        [ToolSpec("read_file", "Read a file", {"type": "object"})],
        system="First system rule.",
        max_tokens=500,
    )

    assert fake.thread_kwargs["model"] == "gpt-5.6-terra"
    assert fake.thread_kwargs["ephemeral"] is True
    assert fake.thread_kwargs["approval_mode"] is ApprovalMode.deny_all
    assert fake.thread_kwargs["sandbox"] is Sandbox.read_only
    assert fake.thread_kwargs["developer_instructions"] == (
        "First system rule.\n\nSecond system rule."
    )
    assert fake.thread.run_kwargs["approval_mode"] is ApprovalMode.deny_all
    assert fake.thread.run_kwargs["sandbox"] is Sandbox.read_only
    assert "Second system rule." not in fake.thread.run_kwargs["prompt"]
    assert response.usage == TokenUsage(31, 9)
    assert response.tool_calls == (ToolCall("codex_turn_42_1", "read_file", {"path": "q3.md"}),)
    status = await runtime.status()
    assert (status.state, status.email, status.plan) == (
        "connected",
        "person@example.com",
        "plus",
    )

    await runtime.aclose()
    assert fake.closed is True


async def test_codex_runtime_streams_only_decoded_text_then_the_decision(
    tmp_path: Path,
) -> None:
    fake = _FakeCodex()
    runtime = CodexAppServerRuntime(tmp_path / "codex", codex=cast(AsyncCodex, fake))

    events = [
        event
        async for event in runtime.stream_infer(
            "gpt-5.6-terra",
            [Message(Role.USER, "Say hello")],
            None,
            system=None,
            max_tokens=100,
        )
    ]

    assert events[:-1] == [
        ChatGPTModelDelta("Hel"),
        ChatGPTModelDelta("lo "),
        ChatGPTModelDelta("👋"),
    ]
    terminal = events[-1]
    assert isinstance(terminal, ChatGPTModelResponse)
    assert terminal.text == "Hello 👋"
    assert terminal.usage == TokenUsage(44, 11)
    assert terminal.tool_calls == ()


async def test_the_account_says_which_models_it_may_use_and_is_asked_once(
    tmp_path: Path,
) -> None:
    fake = _FakeCodex()
    runtime = CodexAppServerRuntime(tmp_path / "codex", codex=cast(AsyncCodex, fake))

    assert await runtime.models() == frozenset({"gpt-6-astra", "gpt-5.6-sol"})
    assert await runtime.models() == frozenset({"gpt-6-astra", "gpt-5.6-sol"})
    assert fake.model_calls == 1


async def test_a_list_it_cannot_trust_blocks_nothing(tmp_path: Path) -> None:
    """A second page means the list is partial: check nothing rather than
    refuse a model the account may well include."""
    fake = _FakeCodex()
    fake.next_cursor = "page-2"
    runtime = CodexAppServerRuntime(tmp_path / "codex", codex=cast(AsyncCodex, fake))

    assert await runtime.models() is None


async def test_a_list_reply_it_cannot_read_blocks_nothing(tmp_path: Path) -> None:
    """The SDK validates the reply: a shape a newer Codex sends must read as
    unknown, not take the catalogue and the pre-flight check down with it."""
    fake = _FakeCodex()
    fake.model_error = ValueError("1 validation error for ModelListResponse")
    runtime = CodexAppServerRuntime(tmp_path / "codex", codex=cast(AsyncCodex, fake))

    assert await runtime.models() is None


def test_a_model_the_plan_lacks_reads_as_a_sentence_not_json() -> None:
    raw = RuntimeError(
        '{"type":"error","status":400,"error":{"type":"invalid_request_error","message":'
        "\"The 'gpt-6-sol' model is not supported when using Codex with a ChatGPT account.\"}}"
    )

    mapped = _mapped_provider_error(raw, "gpt-6-sol")

    assert isinstance(mapped, ProviderModelUnavailableError)
    assert "does not include gpt-6-sol" in str(mapped)
    assert "{" not in str(mapped)
