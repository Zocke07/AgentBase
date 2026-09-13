"""OpenAI Chat Completions, normalized to the provider protocol.

The differences from Anthropic that this adapter absorbs, so nothing above it
has to know:

* The system prompt is an ordinary message with `role: "system"`, not a
  top-level field.
* Tool calls arrive as `tool_calls` on the message, and their `arguments` are a
  **JSON-encoded string**, not an object. Parsing that string here is what
  keeps :class:`~agentspace.providers.base.ToolCall` uniform.
* Usage is `prompt_tokens` / `completion_tokens`.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Final

import httpx2

from agentspace.providers.base import (
    Completion,
    Message,
    ProviderAuthError,
    Role,
    StreamEvent,
    TextDelta,
    TokenUsage,
    ToolCall,
    ToolSpec,
)
from agentspace.providers.transport import (
    DEFAULT_TIMEOUT_SECONDS,
    post_json,
    stream_sse,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterable

__all__ = ["DEFAULT_BASE_URL", "OpenAIProvider"]

DEFAULT_BASE_URL: Final[str] = "https://api.openai.com"


class OpenAIProvider:
    """Calls `POST /v1/chat/completions`."""

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

    @property
    def model(self) -> str:
        return self._model

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

        payload: dict[str, Any] = {
            "model": self._model,
            "messages": _to_openai_messages(messages, system),
            "max_completion_tokens": max_tokens,
        }
        if tools:
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
            f"{self._base_url}/v1/chat/completions",
            self._payload(messages, tools, system, max_tokens),
            self._headers(),
            self.name,
        )

        return self._to_completion(body)

    async def stream(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        *,
        system: str | None = None,
        max_tokens: int = 4096,
    ) -> AsyncIterator[StreamEvent]:
        """Stream `POST /v1/chat/completions` with `stream: true`.

        `stream_options.include_usage` is required: without it no chunk
        carries token counts and every streamed call would record as free.
        """
        payload = self._payload(messages, tools, system, max_tokens)
        payload["stream"] = True
        payload["stream_options"] = {"include_usage": True}

        state = _StreamState(self._model)

        async for frame in stream_sse(
            self._client,
            f"{self._base_url}/v1/chat/completions",
            payload,
            self._headers(),
            self.name,
        ):
            text = state.consume(frame)
            if text:
                yield TextDelta(text)

        yield state.finish(self.name)

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
        else:
            turns.append({"role": str(message.role), "content": message.content})

    return turns


def _decode_arguments(encoded: str) -> dict[str, Any]:
    """Decode a tool call's JSON-encoded `arguments` string; invalid JSON degrades to empty
    arguments.
    """
    if not encoded.strip():
        return {}

    try:
        decoded: Any = json.loads(encoded)
    except json.JSONDecodeError:
        return {}

    return decoded if isinstance(decoded, dict) else {}


def _tool_calls(raw: Any) -> list[ToolCall]:
    """Parse `tool_calls`, whose `arguments` is a JSON *string*."""
    if not isinstance(raw, list):
        return []

    calls: list[ToolCall] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        function = entry.get("function")
        function = function if isinstance(function, dict) else {}

        encoded = function.get("arguments")
        arguments = _decode_arguments(encoded if isinstance(encoded, str) else "")

        calls.append(
            ToolCall(
                id=str(entry.get("id", "")),
                name=str(function.get("name", "")),
                arguments=arguments,
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
    """Reassembles OpenAI's streamed chunks into one :class:`Completion`.

    Two shapes make this more than string concatenation:

    * **Tool calls arrive keyed by `index`, not by id.** Only the first chunk
      for a call carries `id` and `function.name`; every later chunk has just
      the `index` and another slice of the argument string. Keying on anything
      else loses the name or merges two parallel calls into one.
    * **The usage chunk has an empty `choices` list.** Code that reads
      `choices[0]` on every frame raises on the one frame that carries the
      token counts.
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
                arguments=_decode_arguments("".join(call["arguments"])),
            )
            for _, call in sorted(self._calls.items())
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
