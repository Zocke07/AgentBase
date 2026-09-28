"""Ollama adapter for the provider protocol.

Ollama uses a local daemon with no API key or usage cost.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

import httpx2

from agentbase.providers.base import (
    Completion,
    Message,
    Role,
    StreamEvent,
    TextDelta,
    TokenUsage,
    ToolCall,
    ToolSpec,
)
from agentbase.providers.transport import (
    DEFAULT_TIMEOUT_SECONDS,
    post_json,
    stream_ndjson,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterable

__all__ = ["DEFAULT_BASE_URL", "MODEL_PREFIX", "OllamaProvider"]

#: Default daemon address for outbound requests.
DEFAULT_BASE_URL: Final[str] = "http://127.0.0.1:11434"

#: Namespace local models so pricing recognizes them as free.
MODEL_PREFIX: Final[str] = "ollama/"


class OllamaProvider:
    """Calls `POST /api/chat`."""

    name = "ollama"

    def __init__(
        self,
        model: str,
        base_url: str = DEFAULT_BASE_URL,
        client: httpx2.AsyncClient | None = None,
    ) -> None:
        # Keep local models namespaced for pricing.
        self._model = model if model.startswith(MODEL_PREFIX) else MODEL_PREFIX + model
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx2.AsyncClient(timeout=DEFAULT_TIMEOUT_SECONDS)

    @property
    def model(self) -> str:
        return self._model

    @property
    def remote_model(self) -> str:
        """Return the daemon model name without the application namespace."""
        return self._model[len(MODEL_PREFIX) :]

    def _payload(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None,
        system: str | None,
        max_tokens: int,
        *,
        stream: bool,
    ) -> dict[str, Any]:
        """The request body, shared by `complete` and `stream`."""
        payload: dict[str, Any] = {
            "model": self.remote_model,
            "messages": _to_ollama_messages(messages, system),
            "stream": stream,
            "options": {"num_predict": max_tokens},
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

    # Ollama requires no authentication header.
    _HEADERS: Final[dict[str, str]] = {"content-type": "application/json"}

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
            f"{self._base_url}/api/chat",
            self._payload(messages, tools, system, max_tokens, stream=False),
            self._HEADERS,
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
        """Stream newline-delimited JSON and fold it into a completion response."""
        final: dict[str, Any] = {}

        async for frame in stream_ndjson(
            self._client,
            f"{self._base_url}/api/chat",
            self._payload(messages, tools, system, max_tokens, stream=True),
            self._HEADERS,
            self.name,
        ):
            final = _merge_frame(final, frame)

            text = _frame_text(frame)
            if text:
                yield TextDelta(text)

        yield self._to_completion(final)

    def _to_completion(self, body: dict[str, Any]) -> Completion:
        message = body.get("message")
        message = message if isinstance(message, dict) else {}

        content = message.get("content")
        thinking = message.get("thinking")

        return Completion(
            provider=self.name,
            model=self._model,
            text=content if isinstance(content, str) else "",
            # Keep model reasoning separate from answer text.
            thinking=thinking if isinstance(thinking, str) and thinking else None,
            usage=TokenUsage(
                # Ollama names input and output usage differently.
                input_tokens=_non_negative_int(body.get("prompt_eval_count")),
                output_tokens=_non_negative_int(body.get("eval_count")),
            ),
            tool_calls=tuple(_tool_calls(message.get("tool_calls"))),
            stop_reason=_optional_str(body.get("done_reason")),
        )


def _to_ollama_messages(
    messages: Iterable[Message], system: str | None
) -> list[dict[str, str]]:
    turns: list[dict[str, str]] = []
    if system:
        turns.append({"role": "system", "content": system})

    for message in messages:
        role = "tool" if message.role is Role.TOOL else str(message.role)
        turns.append({"role": role, "content": message.content})

    return turns


def _tool_calls(raw: Any) -> list[ToolCall]:
    """Parse Ollama's object-valued tool arguments."""
    if not isinstance(raw, list):
        return []

    calls: list[ToolCall] = []
    for index, entry in enumerate(raw):
        if not isinstance(entry, dict):
            continue
        function = entry.get("function")
        function = function if isinstance(function, dict) else {}
        arguments = function.get("arguments")

        calls.append(
            ToolCall(
                # Use index when Ollama omits a call ID.
                id=str(entry.get("id") or f"call_{index}"),
                name=str(function.get("name", "")),
                arguments=arguments if isinstance(arguments, dict) else {},
            )
        )

    return calls


def _non_negative_int(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return max(0, value)


def _optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _frame_text(frame: dict[str, Any]) -> str:
    message = frame.get("message")
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    return content if isinstance(content, str) else ""


def _merge_frame(accumulated: dict[str, Any], frame: dict[str, Any]) -> dict[str, Any]:
    """Fold one streamed line into blocking-response shape.

    Later fields win except concatenated message content and thinking.
    """
    merged = dict(accumulated)
    merged.update(frame)

    previous = accumulated.get("message")
    incoming = frame.get("message")
    if isinstance(incoming, dict):
        message = dict(incoming)
        if isinstance(previous, dict):
            message["content"] = _text_of(previous) + _text_of(incoming)
            message["thinking"] = _thinking_of(previous) + _thinking_of(incoming)
            # Preserve one-frame tool calls through later empty messages.
            if not incoming.get("tool_calls") and previous.get("tool_calls"):
                message["tool_calls"] = previous["tool_calls"]
        merged["message"] = message

    return merged


def _text_of(message: dict[str, Any]) -> str:
    content = message.get("content")
    return content if isinstance(content, str) else ""


def _thinking_of(message: dict[str, Any]) -> str:
    thinking = message.get("thinking")
    return thinking if isinstance(thinking, str) else ""
