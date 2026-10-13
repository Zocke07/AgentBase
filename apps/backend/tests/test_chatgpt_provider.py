"""ChatGPT subscription access behind the ordinary OpenAI provider contract."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

import pytest
from openai_codex import ApprovalMode, AsyncCodex, CodexError, Sandbox, ServerBusyError
from openai_codex.generated.v2_all import TurnError

from agentbase.providers.base import (
    Completion,
    Message,
    Provider,
    ProviderAuthError,
    ProviderModelUnavailableError,
    ProviderRateLimitedError,
    ProviderUnavailableError,
    Role,
    StreamEvent,
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
    from collections.abc import AsyncGenerator, AsyncIterator
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


def test_call_arguments_that_cannot_be_read_are_reported_not_emptied() -> None:
    """2026-10-13: one read in a batch of ten arrived as ``{}`` and was told it
    named no path, so the decision skipped the file. The model is now told its
    arguments were unreadable, and the batch's other calls are unaffected."""
    parsed = _parse_decision(
        json.dumps(
            {
                "text": "",
                "tool_calls": [
                    {"name": "read_file", "arguments_json": '{"path": "raw/filings/MU.json"}'},
                    {"name": "read_file", "arguments_json": '{"path": "raw/filings/MSFT.json"'},
                    {"name": "read_file", "arguments_json": '["raw/filings/NOW.json"]'},
                    {"name": "list_dir", "arguments_json": ""},
                ],
            }
        ),
        model="gpt-5.6-sol",
        turn_id="turn_9",
        usage=TokenUsage(),
    )

    good, cut_off, listed, bare = parsed.tool_calls
    assert good.arguments == {"path": "raw/filings/MU.json"} and good.argument_error is None
    assert cut_off.arguments == {}
    assert cut_off.argument_error is not None
    assert cut_off.argument_error.startswith("they are not valid JSON")
    assert listed.argument_error == "they are a JSON list, not an object"
    # No arguments at all is a call that takes none, not a mistake.
    assert bare.arguments == {} and bare.argument_error is None


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
        self.run_calls = 0
        self.turn_calls = 0
        self.run_error: Exception | None = None
        self.turn_error: TurnError | None = None
        self.run_started = asyncio.Event()
        self.turn_started = asyncio.Event()
        self.run_release: asyncio.Event | None = None
        self.stream_release: asyncio.Event | None = None
        self.response: str | None = None
        self.turns: list[_FakeTurn] = []

    async def run(self, prompt: str, **kwargs: Any) -> Any:
        self.run_calls += 1
        self.run_kwargs = {"prompt": prompt, **kwargs}
        self.run_started.set()
        if self.run_release is not None:
            await self.run_release.wait()
        if self.run_error is not None:
            raise self.run_error
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
        self.turn_calls += 1
        self.run_kwargs = {"prompt": prompt, **kwargs}
        self.turn_started.set()
        if self.run_error is not None:
            raise self.run_error
        turn = _FakeTurn(self.turn_error, self.stream_release, self.response)
        self.turns.append(turn)
        return turn


class _FakeTurn:
    id = "turn_43"

    def __init__(
        self,
        error: TurnError | None = None,
        release: asyncio.Event | None = None,
        response: str | None = None,
    ) -> None:
        self.error = error
        self.release = release
        self.response = response
        self.interrupts = 0
        self.interrupt_error: Exception | None = None

    async def interrupt(self) -> None:
        self.interrupts += 1
        if self.interrupt_error is not None:
            raise self.interrupt_error

    async def stream(self) -> AsyncIterator[Any]:
        if self.release is not None:
            await self.release.wait()
        if self.error is not None:
            yield SimpleNamespace(
                method="turn/completed",
                payload=SimpleNamespace(
                    turn=SimpleNamespace(
                        status=SimpleNamespace(value="failed"), error=self.error
                    )
                ),
            )
            return
        encoded = '{"text":"Hello \\uD83D\\uDC4B","tool_calls":[]}'
        encoded = self.response or encoded
        deltas = (
            (encoded,)
            if self.response
            else ('{"text":"Hel', "lo \\uD83D", '\\uDC4B","tool_calls":[]}')
        )
        for delta in deltas:
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
    fake.thread.response = json.dumps(
        {
            "text": "Reading.",
            "tool_calls": [
                {"name": "read_file", "arguments_json": json.dumps({"path": "q3.md"})}
            ],
        }
    )
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
    assert response.usage == TokenUsage(44, 11)
    assert response.tool_calls == (ToolCall("codex_turn_43_1", "read_file", {"path": "q3.md"}),)
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


async def test_failed_stream_turn_exposes_429_and_recovery_action(tmp_path: Path) -> None:
    fake = _FakeCodex()
    detail = "exceeded retry limit, last status: 429 Too Many Requests"
    fake.thread.turn_error = TurnError(message=detail)
    runtime = CodexAppServerRuntime(tmp_path / "codex", codex=cast(AsyncCodex, fake))

    with pytest.raises(ProviderRateLimitedError) as caught:
        async for _ in runtime.stream_infer(
            "gpt-6-sol", [Message(Role.USER, "Read prices")], None, system=None, max_tokens=100
        ):
            pytest.fail("A failed turn must not emit a completion.")

    assert "ChatGPT limited requests for gpt-6-sol" in str(caught.value)
    assert "Wait before retrying" in str(caught.value)
    assert "temporary throttling or a subscription usage limit" in str(caught.value)
    assert detail in str(caught.value)
    assert caught.value.retryable is True
    assert fake.thread.turn_calls == 1
    assert (await runtime.status()).state == "connected"


async def test_nonstream_codex_429_uses_the_same_classification(tmp_path: Path) -> None:
    fake = _FakeCodex()
    detail = "HTTP 429 Too Many Requests"
    fake.thread.run_error = CodexError(detail)
    runtime = CodexAppServerRuntime(tmp_path / "codex", codex=cast(AsyncCodex, fake))

    with pytest.raises(ProviderRateLimitedError, match="Wait before retrying") as caught:
        await runtime.infer(
            "gpt-6-sol", [Message(Role.USER, "Read prices")], None, system=None, max_tokens=100
        )

    assert detail in str(caught.value)
    assert fake.thread.turn_calls == 1
    assert (await runtime.status()).state == "connected"


async def test_stream_preserves_confirmed_sdk_usage_limit_metadata(tmp_path: Path) -> None:
    fake = _FakeCodex()
    fake.thread.turn_error = TurnError.model_validate(
        {"message": "Request cannot proceed.", "codexErrorInfo": "usageLimitExceeded"}
    )
    runtime = CodexAppServerRuntime(tmp_path / "codex", codex=cast(AsyncCodex, fake))

    with pytest.raises(ProviderRateLimitedError, match="ChatGPT usage limit reached") as caught:
        async for _ in runtime.stream_infer(
            "gpt-6-sol", [Message(Role.USER, "Read prices")], None, system=None, max_tokens=100
        ):
            pytest.fail("A failed turn must not emit a completion.")

    assert "retry after the limit resets" in str(caught.value)
    assert "Request cannot proceed." in str(caught.value)
    assert "temporary throttling" not in str(caught.value)
    assert caught.value.retryable is False
    assert fake.thread.turn_calls == 1


@pytest.mark.parametrize("exception_type", [CodexError, RuntimeError])
@pytest.mark.parametrize("detail", ["HTTP 429", "Too Many Requests", "Rate limit exceeded"])
def test_rate_limit_messages_from_either_sdk_failure_type(
    exception_type: type[CodexError] | type[RuntimeError], detail: str
) -> None:
    mapped = _mapped_provider_error(exception_type(detail), "gpt-6-sol")

    assert isinstance(mapped, ProviderRateLimitedError)
    assert "gpt-6-sol" in str(mapped)
    assert detail in str(mapped)
    assert mapped.retryable is True


def test_error_numbers_containing_429_are_not_http_rate_limits() -> None:
    mapped = _mapped_provider_error(RuntimeError("Transport error 4290"), "gpt-6-sol")

    assert isinstance(mapped, ProviderUnavailableError)
    assert str(mapped) == "Transport error 4290"


def test_codex_auth_and_busy_failures_keep_their_classification() -> None:
    auth = _mapped_provider_error(CodexError("HTTP 401: login expired"), "gpt-6-sol")
    busy = _mapped_provider_error(ServerBusyError(-32000, "Server is busy"), "gpt-6-sol")

    assert isinstance(auth, ProviderAuthError)
    assert str(auth) == "HTTP 401: login expired"
    assert isinstance(busy, ProviderRateLimitedError)
    assert "Server is busy" in str(busy)


def test_rpc_usage_metadata_is_specific_even_when_the_message_is_generic() -> None:
    mapped = _mapped_provider_error(
        ServerBusyError(
            -32000,
            "Request cannot proceed.",
            {"codex_error_info": "usage_limit_reached"},
        ),
        "gpt-6-sol",
    )

    assert isinstance(mapped, ProviderRateLimitedError)
    assert "ChatGPT usage limit reached" in str(mapped)
    assert "retry after the limit resets" in str(mapped)
    assert mapped.retryable is False


@pytest.mark.parametrize("exception_type", [CodexError, RuntimeError])
@pytest.mark.parametrize(
    "detail", ["You've hit your usage limit", "usage_limit_reached", "usage_limit_exceeded"]
)
def test_explicit_usage_exhaustion_does_not_recommend_automatic_retries(
    exception_type: type[CodexError] | type[RuntimeError], detail: str
) -> None:
    mapped = _mapped_provider_error(exception_type(detail), "gpt-6-sol")

    assert isinstance(mapped, ProviderRateLimitedError)
    assert mapped.retryable is False
    assert "retry after the limit resets" in str(mapped)
    assert detail in str(mapped)


class _PacingClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.delays: list[float] = []
        self.sleep_started = asyncio.Event()
        self.sleep_release: asyncio.Event | None = None

    def __call__(self) -> float:
        return self.now

    async def sleep(self, delay: float) -> None:
        self.delays.append(delay)
        self.sleep_started.set()
        if self.sleep_release is not None:
            await self.sleep_release.wait()
        self.now += delay


class _PacingCodex(_FakeCodex):
    def __init__(self, clock: _PacingClock) -> None:
        super().__init__()
        self.clock = clock
        self.starts: list[tuple[str, float]] = []

    async def thread_start(self, **kwargs: Any) -> Any:
        self.starts.append((kwargs["model"], self.clock()))
        return await super().thread_start(**kwargs)


async def _infer(runtime: CodexAppServerRuntime, model: str) -> ChatGPTModelResponse:
    return await runtime.infer(
        model, [Message(Role.USER, "Read prices")], None, system=None, max_tokens=100
    )


async def _consume_stream(
    runtime: CodexAppServerRuntime, model: str
) -> list[ChatGPTModelDelta | ChatGPTModelResponse]:
    return [
        event
        async for event in runtime.stream_infer(
            model, [Message(Role.USER, "Read prices")], None, system=None, max_tokens=100
        )
    ]


async def test_shared_runtime_serializes_infer_and_stream_with_start_spacing(
    tmp_path: Path,
) -> None:
    clock = _PacingClock()
    fake = _PacingCodex(clock)
    fake.thread.stream_release = release = asyncio.Event()
    runtime = CodexAppServerRuntime(
        tmp_path / "codex", codex=cast(AsyncCodex, fake), clock=clock, sleep=clock.sleep
    )

    first = asyncio.create_task(_infer(runtime, "first-model"))
    await fake.thread.turn_started.wait()
    second = asyncio.create_task(_consume_stream(runtime, "second-model"))
    await asyncio.sleep(0)
    third = asyncio.create_task(_infer(runtime, "third-model"))
    await asyncio.sleep(0)

    assert fake.starts == [("first-model", 0.0)]
    assert fake.thread.turn_calls == 1
    fake.thread.stream_release = None
    release.set()
    results = await asyncio.gather(first, second, third)

    assert fake.starts == [("first-model", 0.0), ("second-model", 5.0), ("third-model", 10.0)]
    assert clock.delays == [5.0, 5.0]
    assert isinstance(results[1][-1], ChatGPTModelResponse)
    assert all(turn.interrupts == 0 for turn in fake.thread.turns)


async def test_completed_request_duration_counts_towards_start_spacing(tmp_path: Path) -> None:
    clock = _PacingClock()
    fake = _PacingCodex(clock)
    fake.thread.stream_release = release = asyncio.Event()
    runtime = CodexAppServerRuntime(
        tmp_path / "codex", codex=cast(AsyncCodex, fake), clock=clock, sleep=clock.sleep
    )

    first = asyncio.create_task(_infer(runtime, "first-model"))
    await fake.thread.turn_started.wait()
    second = asyncio.create_task(_infer(runtime, "second-model"))
    await asyncio.sleep(0)
    clock.now = 8.0
    fake.thread.stream_release = None
    release.set()
    await asyncio.gather(first, second)

    assert fake.starts == [("first-model", 0.0), ("second-model", 8.0)]
    assert clock.delays == []


@pytest.mark.parametrize("streaming", [False, True])
async def test_cancelled_active_request_releases_the_shared_permit(
    tmp_path: Path, streaming: bool
) -> None:
    clock = _PacingClock()
    fake = _PacingCodex(clock)
    fake.thread.stream_release = asyncio.Event()
    runtime = CodexAppServerRuntime(
        tmp_path / "codex", codex=cast(AsyncCodex, fake), clock=clock, sleep=clock.sleep
    )

    first: (
        asyncio.Task[ChatGPTModelResponse]
        | asyncio.Task[list[ChatGPTModelDelta | ChatGPTModelResponse]]
    )
    if streaming:
        first = asyncio.create_task(_consume_stream(runtime, "first-model"))
        await fake.thread.turn_started.wait()
    else:
        first = asyncio.create_task(_infer(runtime, "first-model"))
        await fake.thread.turn_started.wait()
    second = asyncio.create_task(_infer(runtime, "second-model"))
    await asyncio.sleep(0)
    assert fake.starts == [("first-model", 0.0)]
    fake.thread.stream_release = None
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    await second

    assert fake.starts == [("first-model", 0.0), ("second-model", 5.0)]
    assert fake.thread.turns[0].interrupts == 1
    assert fake.thread.turns[1].interrupts == 0


async def test_closing_provider_stream_between_deltas_releases_runtime_permit(
    tmp_path: Path,
) -> None:
    clock = _PacingClock()
    fake = _PacingCodex(clock)
    runtime = CodexAppServerRuntime(
        tmp_path / "codex", codex=cast(AsyncCodex, fake), clock=clock, sleep=clock.sleep
    )
    provider = ChatGPTSubscriptionProvider(runtime, "stream-model")
    stream = cast(
        "AsyncGenerator[StreamEvent, None]", provider.stream([Message(Role.USER, "hi")])
    )

    assert await anext(stream) == TextDelta("Hel")
    second = asyncio.create_task(_infer(runtime, "next-model"))
    await asyncio.sleep(0)
    assert fake.starts == [("stream-model", 0.0)]
    await stream.aclose()
    await second

    assert fake.starts == [("stream-model", 0.0), ("next-model", 5.0)]
    assert fake.thread.turns[0].interrupts == 1
    assert fake.thread.turns[1].interrupts == 0


async def test_cancellation_during_spacing_does_not_block_the_next_request(
    tmp_path: Path,
) -> None:
    clock = _PacingClock()
    fake = _PacingCodex(clock)
    runtime = CodexAppServerRuntime(
        tmp_path / "codex", codex=cast(AsyncCodex, fake), clock=clock, sleep=clock.sleep
    )
    await _infer(runtime, "first-model")
    clock.sleep_release = release = asyncio.Event()

    cancelled = asyncio.create_task(_infer(runtime, "cancelled-model"))
    await clock.sleep_started.wait()
    next_request = asyncio.create_task(_infer(runtime, "next-model"))
    await asyncio.sleep(0)
    cancelled.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cancelled
    release.set()
    await next_request

    assert fake.starts == [("first-model", 0.0), ("next-model", 5.0)]
    assert clock.delays == [5.0, 5.0]


async def test_interrupt_cleanup_failure_preserves_request_cancellation(tmp_path: Path) -> None:
    fake = _FakeCodex()
    fake.thread.stream_release = asyncio.Event()
    runtime = CodexAppServerRuntime(
        tmp_path / "codex", codex=cast(AsyncCodex, fake), min_interval_seconds=0
    )
    pending = asyncio.create_task(_infer(runtime, "test-model"))
    await fake.thread.turn_started.wait()
    fake.thread.turns[0].interrupt_error = RuntimeError("App server closed")
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert fake.thread.turns[0].interrupts == 1
    fake.thread.stream_release = None
    assert isinstance(await _infer(runtime, "next-model"), ChatGPTModelResponse)


async def test_failed_terminal_turn_is_not_interrupted(tmp_path: Path) -> None:
    fake = _FakeCodex()
    fake.thread.turn_error = TurnError.model_validate(
        {"message": "Too many requests", "codexErrorInfo": "rateLimitExceeded"}
    )
    runtime = CodexAppServerRuntime(tmp_path / "codex", codex=cast(AsyncCodex, fake))
    with pytest.raises(ProviderRateLimitedError):
        await _infer(runtime, "test-model")
    assert fake.thread.turns[0].interrupts == 0


def test_rate_limit_exception_remains_retryable_by_default() -> None:
    error = ProviderRateLimitedError("Retry later.", 12.5)

    assert error.retry_after_seconds == 12.5
    assert error.retryable is True
