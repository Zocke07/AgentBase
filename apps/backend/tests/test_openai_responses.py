"""Offline Responses protocol checks for reasoning models and app-owned tools."""

from __future__ import annotations

import copy
import json
from typing import Any

import httpx2
import pytest

from agentbase.providers.base import (
    Completion,
    Message,
    ProviderError,
    ProviderRateLimitedError,
    ProviderUnavailableError,
    Role,
    TextDelta,
    TokenUsage,
    ToolCall,
    ToolSpec,
)
from agentbase.providers.openai import OpenAIProvider

pytestmark = pytest.mark.anyio

REASONING: dict[str, Any] = {
    "type": "reasoning",
    "id": "rs_market",
    "summary": [{"type": "summary_text", "text": "Check the quote before forecasting."}],
    "encrypted_content": "opaque-encrypted-reasoning",
}
FUNCTION_CALL: dict[str, Any] = {
    "type": "function_call",
    "id": "fc_quote",
    "call_id": "call_quote",
    "name": "get_stock_prices",
    "arguments": '{"tickers":["MU"]}',
    "status": "completed",
}
PRICE_TOOL = ToolSpec(
    name="get_stock_prices",
    description="Get the latest available prices.",
    input_schema={
        "type": "object",
        "properties": {
            "tickers": {"type": "array", "items": {"type": "string"}},
            "as_of": {"type": "string"},
        },
        "required": ["tickers"],
    },
)


def response_body(*output: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": "resp_market",
        "object": "response",
        "model": "gpt-6.1-sol",
        "status": "completed",
        "output": copy.deepcopy(list(output)),
        "error": None,
        "usage": {
            "input_tokens": 32,
            "output_tokens": 18,
            "output_tokens_details": {"reasoning_tokens": 12},
        },
    }


def text_item(text: str) -> dict[str, Any]:
    return {
        "type": "message",
        "id": "msg_market",
        "status": "completed",
        "role": "assistant",
        "content": [{"type": "output_text", "text": text, "annotations": []}],
    }


def sse(*frames: dict[str, Any]) -> str:
    return "".join(f"event: {frame['type']}\ndata: {json.dumps(frame)}\n\n" for frame in frames)


def client_for(
    bodies: list[dict[str, Any] | str], captured: list[httpx2.Request]
) -> httpx2.AsyncClient:
    responses = iter(bodies)

    def handle(request: httpx2.Request) -> httpx2.Response:
        captured.append(request)
        body = next(responses)
        if isinstance(body, str):
            return httpx2.Response(
                200, text=body, headers={"content-type": "text/event-stream"}
            )
        return httpx2.Response(200, json=body)

    return httpx2.AsyncClient(transport=httpx2.MockTransport(handle))


def payload(request: httpx2.Request) -> dict[str, Any]:
    decoded: dict[str, Any] = json.loads(request.content)
    return decoded


@pytest.mark.parametrize(
    "model", ["gpt-6", "gpt-6-astra", "gpt-6.1-sol", "gpt-6-sol", "gpt-6-luna"]
)
async def test_current_models_use_responses_with_local_tools_and_no_server_state(
    model: str,
) -> None:
    captured: list[httpx2.Request] = []
    provider = OpenAIProvider(
        "test-key", model, client=client_for([response_body(text_item("Ready."))], captured)
    )

    result = await provider.complete(
        [Message(Role.USER, "Watch my holdings.")],
        [PRICE_TOOL],
        system="Use source evidence.",
        max_tokens=2048,
    )

    assert captured[0].url.path == "/v1/responses"
    request = payload(captured[0])
    assert request["model"] == model
    assert request["input"] == [{"role": "user", "content": "Watch my holdings."}]
    assert request["instructions"] == "Use source evidence."
    assert request["reasoning"] == {"effort": "low"}
    assert request["max_output_tokens"] == 2048
    assert request["store"] is False
    assert request["include"] == ["reasoning.encrypted_content"]
    assert request["tools"] == [
        {
            "type": "function",
            "name": PRICE_TOOL.name,
            "description": PRICE_TOOL.description,
            "parameters": PRICE_TOOL.input_schema,
            "strict": False,
        }
    ]
    assert not {"previous_response_id", "conversation", "temperature", "top_p"} & request.keys()
    assert result.text == "Ready."


@pytest.mark.parametrize(
    ("model", "requires_none"),
    [
        ("gpt-5.4", True),
        ("gpt-5.4-2026-03-05", True),
        ("gpt-5.5", True),
        ("gpt-5.6-sol", True),
        ("gpt-5.6-terra", True),
        ("gpt-5.6-luna", True),
        ("gpt-5", False),
        ("gpt-4o", False),
    ],
)
@pytest.mark.parametrize("with_tools", [False, True])
async def test_retained_chat_models_disable_reasoning_only_where_tool_calling_requires_it(
    model: str, requires_none: bool, with_tools: bool
) -> None:
    captured: list[httpx2.Request] = []
    body: dict[str, Any] = {
        "model": model,
        "choices": [{"message": {"content": "Ready."}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 3},
    }
    provider = OpenAIProvider("k", model, client=client_for([body], captured))

    await provider.complete(
        [Message(Role.USER, "Get MU.")], [PRICE_TOOL] if with_tools else None
    )

    assert captured[0].url.path == "/v1/chat/completions"
    request = payload(captured[0])
    assert request["messages"] == [{"role": "user", "content": "Get MU."}]
    if with_tools and requires_none:
        assert request["reasoning_effort"] == "none"
    else:
        assert "reasoning_effort" not in request
    if with_tools:
        assert request["tools"][0]["function"]["name"] == PRICE_TOOL.name


async def test_completion_normalizes_call_ids_reasoning_and_total_output_usage() -> None:
    body = response_body(REASONING, text_item("Checking MU."), FUNCTION_CALL)
    provider = OpenAIProvider("k", "gpt-6.1-sol", client=client_for([body], []))

    result = await provider.complete([Message(Role.USER, "Get MU.")], [PRICE_TOOL])

    assert result.model == "gpt-6.1-sol"
    assert result.tool_calls == (
        ToolCall("call_quote", "get_stock_prices", {"tickers": ["MU"]}),
    )
    assert result.text == "Checking MU."
    assert result.thinking == "Check the quote before forecasting."
    assert "opaque-encrypted-reasoning" not in result.text
    assert result.usage == TokenUsage(32, 18)
    assert result.stop_reason == "tool_calls"


@pytest.mark.parametrize("first_streamed", [False, True])
async def test_continuation_replays_encrypted_reasoning_before_linked_tool_output(
    first_streamed: bool,
) -> None:
    captured: list[httpx2.Request] = []
    first_body = response_body(REASONING, text_item("Checking MU."), FUNCTION_CALL)
    first: dict[str, Any] | str = (
        sse({"type": "response.completed", "response": first_body})
        if first_streamed
        else first_body
    )
    provider = OpenAIProvider(
        "k",
        "gpt-6.1-sol",
        client=client_for([first, response_body(text_item("MU is $100."))], captured),
    )
    messages = [Message(Role.USER, "Get MU.")]
    if first_streamed:
        events = [
            event async for event in provider.stream(messages, [PRICE_TOOL], system="Market")
        ]
        completion = events[-1]
        assert isinstance(completion, Completion)
    else:
        completion = await provider.complete(messages, [PRICE_TOOL], system="Market")
    messages.extend(
        [
            Message(Role.ASSISTANT, completion.text, tool_calls=completion.tool_calls),
            Message(Role.TOOL, '{"MU":100}', tool_call_id="call_quote"),
        ]
    )

    await provider.complete(messages, [PRICE_TOOL], system="Market")

    sent = payload(captured[1])
    assert sent["input"] == [
        {"role": "user", "content": "Get MU."},
        *first_body["output"],
        {"type": "function_call_output", "call_id": "call_quote", "output": '{"MU":100}'},
    ]
    assert "previous_response_id" not in sent
    assert sent["store"] is False


async def test_plain_assistant_continuation_also_preserves_reasoning() -> None:
    captured: list[httpx2.Request] = []
    provider = OpenAIProvider(
        "k",
        "gpt-6-luna",
        client=client_for(
            [
                response_body(REASONING, text_item("I will check MU.")),
                response_body(FUNCTION_CALL),
            ],
            captured,
        ),
    )
    user = Message(Role.USER, "Get MU.")
    first = await provider.complete([user])

    await provider.complete(
        [user, Message(Role.ASSISTANT, first.text), Message(Role.USER, "Use the price tool.")],
        [PRICE_TOOL],
    )

    assert payload(captured[1])["input"][1] == REASONING


async def test_shared_provider_does_not_replay_reasoning_for_another_agent() -> None:
    captured: list[httpx2.Request] = []
    provider = OpenAIProvider(
        "k",
        "gpt-6.1-sol",
        client=client_for(
            [
                response_body(REASONING, text_item("Checking MU."), FUNCTION_CALL),
                response_body(text_item("Done.")),
            ],
            captured,
        ),
    )
    user = Message(Role.USER, "Get MU.")
    first = await provider.complete([user], [PRICE_TOOL], system="First agent")

    await provider.complete(
        [
            user,
            Message(Role.ASSISTANT, first.text, tool_calls=first.tool_calls),
            Message(Role.TOOL, "100", tool_call_id="call_quote"),
        ],
        [PRICE_TOOL],
        system="Second agent",
    )

    assert not any(item.get("type") == "reasoning" for item in payload(captured[1])["input"])
    assert payload(captured[1])["input"][2] == {
        "type": "function_call",
        "call_id": "call_quote",
        "name": "get_stock_prices",
        "arguments": '{"tickers": ["MU"]}',
    }


async def test_stream_exposes_calls_only_in_terminal_completion() -> None:
    captured: list[httpx2.Request] = []
    body = response_body(REASONING, text_item("Checking MU."), FUNCTION_CALL)
    stream = sse(
        {"type": "response.created", "response": {"status": "in_progress"}},
        {"type": "response.reasoning_summary_text.delta", "delta": "Private summary"},
        {"type": "response.output_item.added", "item": {**FUNCTION_CALL, "arguments": ""}},
        {"type": "response.function_call_arguments.delta", "delta": '{"tickers":'},
        {"type": "response.output_text.delta", "delta": "Checking "},
        {"type": "response.function_call_arguments.delta", "delta": '["MU"]}'},
        {"type": "response.output_text.delta", "delta": "MU."},
        {
            "type": "response.function_call_arguments.done",
            "arguments": FUNCTION_CALL["arguments"],
        },
        {"type": "response.completed", "response": body},
    )
    provider = OpenAIProvider("k", "gpt-6.1-sol", client=client_for([stream], captured))

    events = [
        event async for event in provider.stream([Message(Role.USER, "Get MU.")], [PRICE_TOOL])
    ]

    assert events[:2] == [TextDelta("Checking "), TextDelta("MU.")]
    assert len(events) == 3
    completion = events[-1]
    assert isinstance(completion, Completion)
    assert completion.tool_calls[0].id == "call_quote"
    assert completion.text == "Checking MU."
    assert completion.usage == TokenUsage(32, 18)
    request = payload(captured[0])
    assert request["stream"] is True
    assert "stream_options" not in request


async def test_max_output_tokens_cutoff_never_exposes_partial_calls() -> None:
    body = response_body(
        text_item("Part of an answer"), {**FUNCTION_CALL, "arguments": '{"tickers":'}
    )
    body.update(status="incomplete", incomplete_details={"reason": "max_output_tokens"})
    provider = OpenAIProvider(
        "k",
        "gpt-6-luna",
        client=client_for([sse({"type": "response.incomplete", "response": body})], []),
    )

    events = [
        event async for event in provider.stream([Message(Role.USER, "Get MU.")], [PRICE_TOOL])
    ]

    assert isinstance(events[-1], Completion)
    assert events[-1].stop_reason == "length"
    assert events[-1].tool_calls == ()
    assert events[-1].usage == TokenUsage(32, 18)


async def test_refusal_is_visible_in_stream_and_completion() -> None:
    refusal = text_item("")
    refusal["content"] = [{"type": "refusal", "refusal": "I cannot help with that."}]
    provider = OpenAIProvider(
        "k",
        "gpt-6-astra",
        client=client_for(
            [
                sse(
                    {"type": "response.refusal.delta", "delta": "I cannot help with that."},
                    {"type": "response.completed", "response": response_body(refusal)},
                )
            ],
            [],
        ),
    )

    events = [event async for event in provider.stream([Message(Role.USER, "Request")])]

    assert events[0] == TextDelta("I cannot help with that.")
    assert isinstance(events[1], Completion)
    assert events[1].text == events[0].text


@pytest.mark.parametrize(
    ("item", "error"),
    [
        ({**FUNCTION_CALL, "arguments": "{broken"}, "invalid JSON"),
        ({**FUNCTION_CALL, "arguments": "[]"}, "not an object"),
        ({**FUNCTION_CALL, "call_id": ""}, "without a call_id"),
        ({"type": "web_search_call"}, "unsupported Responses output item"),
        ({"type": "message", "content": "invalid"}, "without content"),
    ],
)
async def test_malformed_or_unoffered_outputs_fail_clearly(
    item: dict[str, Any], error: str
) -> None:
    provider = OpenAIProvider("k", "gpt-6-astra", client=client_for([response_body(item)], []))

    with pytest.raises(ProviderError, match=error):
        await provider.complete([Message(Role.USER, "Get MU.")], [PRICE_TOOL])


@pytest.mark.parametrize(
    "body", [{}, {"status": "in_progress"}, {"status": "completed", "output": None}]
)
async def test_malformed_terminal_bodies_are_not_empty_successes(body: dict[str, Any]) -> None:
    provider = OpenAIProvider("k", "gpt-6-astra", client=client_for([body], []))

    with pytest.raises(ProviderError, match="Responses body"):
        await provider.complete([Message(Role.USER, "Get MU.")])


async def test_interrupted_stream_is_retryable_and_never_yields_a_completion() -> None:
    provider = OpenAIProvider(
        "k",
        "gpt-6-astra",
        client=client_for(
            [sse({"type": "response.output_text.delta", "delta": "Partial"})], []
        ),
    )
    events: list[TextDelta | Completion] = []

    with pytest.raises(ProviderUnavailableError, match="before a completion event"):
        async for event in provider.stream([Message(Role.USER, "Get MU.")]):
            events.append(event)

    assert events == [TextDelta("Partial")]


@pytest.mark.parametrize("event_type", ["error", "response.failed"])
async def test_stream_error_event_does_not_become_a_completion(event_type: str) -> None:
    failure: dict[str, Any] = {
        "error": {"code": "server_error", "message": "Server overloaded"}
    }
    event = (
        {"type": event_type, **failure}
        if event_type == "error"
        else {"type": event_type, "response": failure}
    )
    provider = OpenAIProvider("k", "gpt-6-astra", client=client_for([sse(event)], []))

    with pytest.raises(ProviderUnavailableError, match="Server overloaded"):
        _ = [event async for event in provider.stream([Message(Role.USER, "Get MU.")])]


@pytest.mark.parametrize(
    ("code", "retryable"), [("rate_limit_exceeded", True), ("insufficient_quota", False)]
)
async def test_response_rate_limit_retains_retry_policy(code: str, retryable: bool) -> None:
    failure = {"status": "failed", "error": {"code": code, "message": "Limit reached"}}
    provider = OpenAIProvider("k", "gpt-6-astra", client=client_for([failure], []))

    with pytest.raises(ProviderRateLimitedError) as raised:
        await provider.complete([Message(Role.USER, "Get MU.")])

    assert raised.value.retryable is retryable


async def test_unlinked_tool_result_fails_before_an_http_request() -> None:
    captured: list[httpx2.Request] = []
    provider = OpenAIProvider("k", "gpt-6-astra", client=client_for([], captured))

    with pytest.raises(ProviderError, match="no matching preceding function call"):
        await provider.complete([Message(Role.TOOL, "100", tool_call_id="missing")])

    assert captured == []
