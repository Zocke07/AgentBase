"""Ollama, normalized to the provider protocol.

This implementation exists to keep the abstraction honest. §7 lists local model
support as optional and untested in v1, but §5 Phase 3 requires that the
protocol "must not assume cloud" — and the only way to know whether it does is
to put a provider behind it that has **no API key**, **no cost**, and **no
remote host**. Anything in the protocol that quietly assumed an `Authorization`
header or a positive price would fail to compile here.

It is deliberately not wired into the default settings, and nothing in the test
suite starts an Ollama daemon: these tests use a mock transport like the other
two. Whether a real daemon behaves as documented is untested (§6 — say what was
not verified).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

import httpx2

from agentspace.providers.base import (
    Completion,
    Message,
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
    stream_ndjson,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterable

__all__ = ["DEFAULT_BASE_URL", "MODEL_PREFIX", "OllamaProvider"]

#: The daemon's default address. Loopback, consistent with §1 constraint 3 —
#: though note this is an *outbound* address, not a bind.
DEFAULT_BASE_URL: Final[str] = "http://127.0.0.1:11434"

#: Model ids are namespaced so pricing can recognise them as free without
#: enumerating every model a user might have pulled.
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
        # Kept namespaced so `pricing.cost_micros` resolves it as local/free.
        self._model = model if model.startswith(MODEL_PREFIX) else MODEL_PREFIX + model
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx2.AsyncClient(timeout=DEFAULT_TIMEOUT_SECONDS)

    @property
    def model(self) -> str:
        return self._model

    @property
    def remote_model(self) -> str:
        """The name the daemon knows, without this app's namespace prefix."""
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

    # No auth header anywhere below: there is no key, and inventing one would
    # be the cloud assumption this provider exists to rule out.
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
        """Stream `POST /api/chat`.

        Ollama streams **newline-delimited JSON, not SSE** — no `data:` prefix,
        no blank-line framing. Every line is a whole response object of the same
        shape the blocking call returns, with `done: false` until the last one,
        which carries the token counts and no content.

        That shape is why the final object is assembled by folding each line
        through the same `_to_completion` the blocking path uses: the last line
        alone has the usage but none of the text.
        """
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

        return Completion(
            provider=self.name,
            model=self._model,
            text=content if isinstance(content, str) else "",
            usage=TokenUsage(
                # Ollama's names for input and output tokens.
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
    """Ollama returns `arguments` as an object, unlike OpenAI's JSON string."""
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
                # Ollama does not assign call ids; the orchestrator needs one
                # to correlate a result with its request, so index is used.
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
    """Fold one streamed line into a response object shaped like a blocking one.

    Later fields win, except `message.content`, which concatenates — that is
    the whole point of a stream. Doing it this way rather than with a bespoke
    accumulator means the streamed and blocking paths converge on one parser,
    so a field added to `_to_completion` cannot be read on only one of them.
    """
    merged = dict(accumulated)
    merged.update(frame)

    previous = accumulated.get("message")
    incoming = frame.get("message")
    if isinstance(incoming, dict):
        message = dict(incoming)
        if isinstance(previous, dict):
            message["content"] = _text_of(previous) + _text_of(incoming)
            # A tool call arrives on one line only; a later empty message
            # must not erase it.
            if not incoming.get("tool_calls") and previous.get("tool_calls"):
                message["tool_calls"] = previous["tool_calls"]
        merged["message"] = message

    return merged


def _text_of(message: dict[str, Any]) -> str:
    content = message.get("content")
    return content if isinstance(content, str) else ""
