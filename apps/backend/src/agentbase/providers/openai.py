"""OpenAI Responses and legacy Chat Completions adapter.

GPT-6 tool calling requires Responses when reasoning is enabled. The app still
owns tool execution and sends full history without storing server conversations.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Final

import httpx2

from agentbase.providers.base import (
    Completion,
    Message,
    ProviderAuthError,
    ProviderError,
    ProviderRateLimitedError,
    ProviderUnavailableError,
    Role,
    StreamEvent,
    TextDelta,
    TokenUsage,
    ToolCall,
    ToolSpec,
    decode_arguments,
)
from agentbase.providers.transport import (
    DEFAULT_TIMEOUT_SECONDS,
    post_json,
    stream_sse,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterable

__all__ = ["DEFAULT_BASE_URL", "OpenAIProvider"]

DEFAULT_BASE_URL: Final[str] = "https://api.openai.com"


class OpenAIProvider:
    """Use Responses for GPT-6, retaining Chat Completions for legacy models."""

    name = "openai"

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str = DEFAULT_BASE_URL,
        client: httpx2.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx2.AsyncClient(timeout=DEFAULT_TIMEOUT_SECONDS)
        # Providers are shared within a run. Key replay by complete history and
        # system prompt, so one agent never inherits another agent's reasoning.
        self._response_outputs: dict[str, list[dict[str, Any]]] = {}

    @property
    def model(self) -> str:
        return self._model

    @property
    def _uses_responses(self) -> bool:
        return self._model == "gpt-6" or self._model.startswith(("gpt-6-", "gpt-6."))

    @property
    def _endpoint(self) -> str:
        route = "responses" if self._uses_responses else "chat/completions"
        return f"{self._base_url}/v1/{route}"

    def _payload(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None,
        system: str | None,
        max_tokens: int,
    ) -> dict[str, Any]:
        """The request body, shared by `complete` and `stream`."""
        if not self._api_key:
            msg = "no OpenAI API key is configured"
            raise ProviderAuthError(msg)

        if self._uses_responses:
            payload: dict[str, Any] = {
                "model": self._model,
                "input": _to_responses_input(messages, system, self._response_outputs),
                "max_output_tokens": max_tokens,
                "reasoning": {"effort": "low"},
                "include": ["reasoning.encrypted_content"],
                "store": False,
            }
            if system:
                payload["instructions"] = system
            if tools:
                payload["tools"] = [
                    {
                        "type": "function",
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.input_schema or {"type": "object", "properties": {}},
                        # Preserve optional fields in the app's tool schemas.
                        "strict": False,
                    }
                    for tool in tools
                ]
            return payload

        payload = {
            "model": self._model,
            "messages": _to_openai_messages(messages, system),
            "max_completion_tokens": max_tokens,
        }
        if tools:
            if any(
                self._model == family or self._model.startswith(f"{family}-")
                for family in ("gpt-5.4", "gpt-5.5", "gpt-5.6")
            ):
                # These retained models accept Chat Completions function
                # calling only with reasoning disabled. GPT-6 uses Responses.
                payload["reasoning_effort"] = "none"
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.input_schema or {"type": "object", "properties": {}},
                    },
                }
                for tool in tools
            ]
        return payload

    def _headers(self) -> dict[str, str]:
        return {
            "authorization": f"Bearer {self._api_key}",
            "content-type": "application/json",
        }

    async def complete(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        *,
        system: str | None = None,
        max_tokens: int = 4096,
    ) -> Completion:
        body = await post_json(
            self._client,
            self._endpoint,
            self._payload(messages, tools, system, max_tokens),
            self._headers(),
            self.name,
        )

        if self._uses_responses:
            return self._responses_completion(body, messages, system)
        return self._to_completion(body)

    async def stream(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        *,
        system: str | None = None,
        max_tokens: int = 4096,
    ) -> AsyncIterator[StreamEvent]:
        """Stream text, then complete calls and usage from a terminal response."""
        payload = self._payload(messages, tools, system, max_tokens)
        payload["stream"] = True
        if self._uses_responses:
            response: dict[str, Any] | None = None
            async for frame in stream_sse(
                self._client, self._endpoint, payload, self._headers(), self.name
            ):
                event_type = frame.get("type")
                if event_type in ("response.output_text.delta", "response.refusal.delta"):
                    delta = frame.get("delta")
                    if not isinstance(delta, str):
                        msg = "openai returned a malformed Responses text delta"
                        raise ProviderError(msg)
                    if delta:
                        yield TextDelta(delta)
                elif event_type in ("response.completed", "response.incomplete"):
                    terminal = frame.get("response")
                    if not isinstance(terminal, dict):
                        msg = "openai returned a malformed Responses completion event"
                        raise ProviderError(msg)
                    response = terminal
                elif event_type in ("error", "response.failed"):
                    terminal = frame.get("response")
                    failure = terminal if isinstance(terminal, dict) else frame
                    _raise_responses_error(failure)
            if response is None:
                msg = "openai ended the Responses stream before a completion event"
                raise ProviderUnavailableError(msg)
            yield self._responses_completion(response, messages, system)
            return

        payload["stream_options"] = {"include_usage": True}

        state = _StreamState(self._model)

        async for frame in stream_sse(
            self._client,
            self._endpoint,
            payload,
            self._headers(),
            self.name,
        ):
            text = state.consume(frame)
            if text:
                yield TextDelta(text)

        yield state.finish(self.name)

    def _responses_completion(
        self, body: dict[str, Any], messages: list[Message], system: str | None
    ) -> Completion:
        completion = _from_responses(body, self.name, self._model)
        if body.get("status") == "completed":
            output: list[dict[str, Any]] = body["output"]
            assistant = Message(
                role=Role.ASSISTANT,
                content=completion.text,
                tool_calls=completion.tool_calls,
            )
            self._response_outputs[_history_key([*messages, assistant], system)] = output
        return completion

    def _to_completion(self, body: dict[str, Any]) -> Completion:
        choices = body.get("choices")
        choice: dict[str, Any] = {}
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            choice = choices[0]

        message = choice.get("message")
        message = message if isinstance(message, dict) else {}

        content = message.get("content")
        usage = body.get("usage")
        usage = usage if isinstance(usage, dict) else {}

        return Completion(
            provider=self.name,
            model=str(body.get("model", self._model)),
            text=content if isinstance(content, str) else "",
            usage=TokenUsage(
                input_tokens=_non_negative_int(usage.get("prompt_tokens")),
                output_tokens=_non_negative_int(usage.get("completion_tokens")),
            ),
            tool_calls=tuple(_tool_calls(message.get("tool_calls"))),
            stop_reason=_optional_str(choice.get("finish_reason")),
        )


def _history_key(messages: Iterable[Message], system: str | None) -> str:
    """Identify a turn without relying on text shared by different agents."""
    return json.dumps(
        {"system": system, "messages": [message.as_payload() for message in messages]},
        sort_keys=True,
    )


def _to_responses_input(
    messages: list[Message],
    system: str | None,
    previous_outputs: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Replay full history, preserving reasoning and function call linkage."""
    turns: list[dict[str, Any]] = []
    pending_calls: set[str] = set()
    for index, message in enumerate(messages):
        if message.role is Role.TOOL:
            if not message.tool_call_id or message.tool_call_id not in pending_calls:
                msg = "openai Responses tool result has no matching preceding function call"
                raise ProviderError(msg)
            pending_calls.remove(message.tool_call_id)
            turns.append(
                {
                    "type": "function_call_output",
                    "call_id": message.tool_call_id,
                    "output": message.content,
                }
            )
            continue

        if message.role is Role.ASSISTANT:
            for call in message.tool_calls:
                if not call.id or not call.name or call.id in pending_calls:
                    msg = "openai Responses history has a malformed function call"
                    raise ProviderError(msg)
                pending_calls.add(call.id)
            replay = previous_outputs.get(_history_key(messages[: index + 1], system))
            if replay is not None:
                # In stateless Responses, encrypted reasoning must accompany
                # the calls it produced, before their function_call_outputs.
                turns.extend(replay)
                continue

        if message.content or not message.tool_calls:
            turns.append({"role": str(message.role), "content": message.content})
        turns.extend(
            {
                "type": "function_call",
                "call_id": call.id,
                "name": call.name,
                "arguments": json.dumps(call.arguments),
            }
            for call in message.tool_calls
        )

    if pending_calls:
        msg = "openai Responses history has function calls without tool results"
        raise ProviderError(msg)
    return turns


def _raise_responses_error(body: dict[str, Any]) -> None:
    error = body.get("error")
    error = error if isinstance(error, dict) else body
    detail = error.get("message")
    detail = detail if isinstance(detail, str) and detail else "response failed"
    msg = f"openai Responses failed: {detail}"
    code = error.get("code")
    if code in ("rate_limit_exceeded", "rate_limit_error", "insufficient_quota"):
        raise ProviderRateLimitedError(msg, retryable=code != "insufficient_quota")
    if code in ("server_error", "service_unavailable"):
        raise ProviderUnavailableError(msg)
    raise ProviderError(msg)


def _responses_tool_call(item: dict[str, Any]) -> ToolCall:
    call_id = item.get("call_id")
    name = item.get("name")
    encoded = item.get("arguments")
    if not isinstance(call_id, str) or not call_id or not isinstance(name, str) or not name:
        msg = "openai returned a Responses function call without a call_id or name"
        raise ProviderError(msg)
    if not isinstance(encoded, str):
        msg = "openai returned non-JSON Responses function arguments"
        raise ProviderError(msg)
    try:
        arguments: Any = json.loads(encoded)
    except json.JSONDecodeError as exc:
        msg = "openai returned invalid JSON in Responses function arguments"
        raise ProviderError(msg) from exc
    if not isinstance(arguments, dict):
        msg = "openai returned Responses function arguments that are not an object"
        raise ProviderError(msg)
    return ToolCall(id=call_id, name=name, arguments=arguments)


def _from_responses(body: dict[str, Any], provider: str, model: str) -> Completion:
    """Normalize typed Responses items without running provider-side tools."""
    if body.get("error") or body.get("status") == "failed":
        _raise_responses_error(body)
    status = body.get("status")
    if status not in ("completed", "incomplete"):
        msg = "openai returned a Responses body without a terminal status"
        raise ProviderError(msg)
    output = body.get("output")
    if not isinstance(output, list):
        msg = "openai returned a Responses body without an output array"
        raise ProviderError(msg)

    text: list[str] = []
    thinking: list[str] = []
    calls: list[ToolCall] = []
    for item in output:
        if not isinstance(item, dict):
            msg = "openai returned a malformed Responses output item"
            raise ProviderError(msg)
        item_type = item.get("type")
        if item_type == "message":
            content = item.get("content")
            if not isinstance(content, list):
                msg = "openai returned a Responses message without content"
                raise ProviderError(msg)
            for part in content:
                if not isinstance(part, dict):
                    msg = "openai returned a malformed Responses message part"
                    raise ProviderError(msg)
                part_type = part.get("type")
                if part_type == "output_text":
                    value = part.get("text")
                elif part_type == "refusal":
                    value = part.get("refusal")
                else:
                    msg = "openai returned an unsupported Responses message part"
                    raise ProviderError(msg)
                if not isinstance(value, str):
                    msg = "openai returned a Responses message part without text"
                    raise ProviderError(msg)
                text.append(value)
        elif item_type == "function_call":
            # A length cutoff may leave JSON arguments half-written. The
            # orchestrator will nudge a new turn without executing these calls.
            if status == "completed":
                calls.append(_responses_tool_call(item))
        elif item_type == "reasoning":
            summary = item.get("summary")
            if isinstance(summary, list):
                thinking.extend(
                    part["text"]
                    for part in summary
                    if isinstance(part, dict)
                    and part.get("type") == "summary_text"
                    and isinstance(part.get("text"), str)
                )
        else:
            msg = "openai returned an unsupported Responses output item"
            raise ProviderError(msg)

    if status == "completed" and not text and not calls:
        msg = "openai completed a Responses request without text or function calls"
        raise ProviderError(msg)
    usage = body.get("usage")
    usage = usage if isinstance(usage, dict) else {}
    if status == "incomplete":
        details = body.get("incomplete_details")
        reason = details.get("reason") if isinstance(details, dict) else None
        stop_reason = "length" if reason == "max_output_tokens" else "content_filter"
    else:
        stop_reason = "tool_calls" if calls else "stop"
    return Completion(
        provider=provider,
        model=str(body.get("model", model)),
        text="".join(text),
        usage=TokenUsage(
            input_tokens=_non_negative_int(usage.get("input_tokens")),
            # output_tokens already includes reasoning_tokens. Do not count
            # those details twice or exclude them from the app's budget.
            output_tokens=_non_negative_int(usage.get("output_tokens")),
        ),
        tool_calls=tuple(calls),
        stop_reason=stop_reason,
        thinking="\n".join(thinking) if thinking else None,
    )


def _to_openai_messages(
    messages: Iterable[Message], system: str | None
) -> list[dict[str, Any]]:
    turns: list[dict[str, Any]] = []
    if system:
        turns.append({"role": "system", "content": system})

    for message in messages:
        if message.role is Role.TOOL:
            turns.append(
                {
                    "role": "tool",
                    "content": message.content,
                    "tool_call_id": message.tool_call_id or "",
                }
            )
        elif message.role is Role.ASSISTANT and message.tool_calls:
            # A `tool` turn must follow the assistant turn whose call it answers.
            turns.append(
                {
                    "role": "assistant",
                    "content": message.content or None,
                    "tool_calls": [
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {
                                "name": call.name,
                                "arguments": json.dumps(call.arguments),
                            },
                        }
                        for call in message.tool_calls
                    ],
                }
            )
        else:
            turns.append({"role": str(message.role), "content": message.content})

    return turns


def _tool_calls(raw: Any) -> list[ToolCall]:
    """Parse ``tool_calls`` with JSON-string arguments."""
    if not isinstance(raw, list):
        return []

    calls: list[ToolCall] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        function = entry.get("function")
        function = function if isinstance(function, dict) else {}

        encoded = function.get("arguments")
        arguments, problem = decode_arguments(encoded if isinstance(encoded, str) else "")

        calls.append(
            ToolCall(
                id=str(entry.get("id", "")),
                name=str(function.get("name", "")),
                arguments=arguments,
                argument_error=problem,
            )
        )

    return calls


def _non_negative_int(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return max(0, value)


def _optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) else None


class _StreamState:
    """Fold OpenAI chunks into a :class:`Completion`.

    Merge tool calls by chunk index because only first chunks carry IDs and
    names; usage chunks may contain no choices.
    """

    def __init__(self, model: str) -> None:
        self._model = model
        self._text: list[str] = []
        self._calls: dict[int, dict[str, Any]] = {}
        self._input_tokens = 0
        self._output_tokens = 0
        self._stop_reason: str | None = None

    def consume(self, frame: dict[str, Any]) -> str:
        """Fold one chunk in; return any text it contributed."""
        model = frame.get("model")
        if isinstance(model, str) and model:
            self._model = model

        usage = frame.get("usage")
        if isinstance(usage, dict):
            self._input_tokens = _non_negative_int(usage.get("prompt_tokens"))
            self._output_tokens = _non_negative_int(usage.get("completion_tokens"))

        choices = frame.get("choices")
        if not isinstance(choices, list) or not choices:
            return ""

        choice = choices[0]
        if not isinstance(choice, dict):
            return ""

        finish = choice.get("finish_reason")
        if isinstance(finish, str):
            self._stop_reason = finish

        delta = choice.get("delta")
        if not isinstance(delta, dict):
            return ""

        self._merge_tool_calls(delta.get("tool_calls"))

        content = delta.get("content")
        if isinstance(content, str) and content:
            self._text.append(content)
            return content

        return ""

    def _merge_tool_calls(self, raw: Any) -> None:
        if not isinstance(raw, list):
            return

        for entry in raw:
            if not isinstance(entry, dict):
                continue

            index = entry.get("index")
            index = index if isinstance(index, int) and not isinstance(index, bool) else 0
            call = self._calls.setdefault(index, {"id": "", "name": "", "arguments": []})

            identifier = entry.get("id")
            if isinstance(identifier, str) and identifier:
                call["id"] = identifier

            function = entry.get("function")
            if not isinstance(function, dict):
                continue

            name = function.get("name")
            if isinstance(name, str) and name:
                call["name"] = name

            arguments = function.get("arguments")
            if isinstance(arguments, str) and arguments:
                parts: list[str] = call["arguments"]
                parts.append(arguments)

    def finish(self, provider: str) -> Completion:
        """The assembled response."""
        tool_calls = [
            ToolCall(
                id=str(call["id"]),
                name=str(call["name"]),
                arguments=arguments,
                argument_error=problem,
            )
            for _, call in sorted(self._calls.items())
            for arguments, problem in [decode_arguments("".join(call["arguments"]))]
        ]

        return Completion(
            provider=provider,
            model=self._model,
            text="".join(self._text),
            usage=TokenUsage(
                input_tokens=self._input_tokens,
                output_tokens=self._output_tokens,
            ),
            tool_calls=tuple(tool_calls),
            stop_reason=self._stop_reason,
        )
