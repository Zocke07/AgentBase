"""Anthropic Messages API, normalized to the provider protocol.

Only the vendor-shaped parts live here. Anything a caller above this module
would have to branch on is translated: `content` blocks become text plus
:class:`~agentspace.providers.base.ToolCall`s, and `usage.input_tokens` /
`usage.output_tokens` become :class:`~agentspace.providers.base.TokenUsage`.

Two shape details that are easy to get wrong:

* **The system prompt is a top-level field, not a message.** Anthropic rejects
  a `system` role inside `messages`; OpenAI requires exactly that. This is the
  single biggest reason the neutral :class:`Message` carries `Role.SYSTEM` and
  each adapter decides where it belongs.
* **`max_tokens` is required.** Omitting it is a 400, unlike OpenAI where it
  defaults.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Final

import httpx2

from agentspace.providers.base import (
    Completion,
    Message,
    ProviderAuthError,
    ProviderError,
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

__all__ = ["ANTHROPIC_VERSION", "DEFAULT_BASE_URL", "AnthropicProvider"]

DEFAULT_BASE_URL: Final[str] = "https://api.anthropic.com"

#: Pinned rather than tracked. The header selects a frozen request/response
#: shape, so a new version changing the wire format cannot break a shipped
#: installer that nobody is going to update.
ANTHROPIC_VERSION: Final[str] = "2023-06-01"


class AnthropicProvider:
    """Calls `POST /v1/messages`."""

    name = "anthropic"

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
        """The request body, shared by `complete` and `stream`.

        Shared rather than duplicated on purpose: the two paths must send the
        same request or streaming becomes a behavioural change instead of a
        transport one, and a tool list that reached only one of them would be a
        bug nothing above this module could diagnose.
        """
        if not self._api_key:
            msg = "no Anthropic API key is configured"
            raise ProviderAuthError(msg)

        system_prompt, turns = _split_system(messages, system)

        payload: dict[str, Any] = {
            "model": self._model,
            "max_tokens": max_tokens,
            "messages": turns,
        }
        if system_prompt:
            payload["system"] = system_prompt
        if tools:
            payload["tools"] = [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": tool.input_schema or {"type": "object", "properties": {}},
                }
                for tool in tools
            ]
        return payload

    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": self._api_key,
            "anthropic-version": ANTHROPIC_VERSION,
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
            f"{self._base_url}/v1/messages",
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
        """Stream `POST /v1/messages` with `stream: true`.

        Anthropic splits a response across `message_start`,
        `content_block_delta` and `message_delta` frames, and the token counts
        arrive in *two* of them: input on `message_start`, output on
        `message_delta` at the very end. Reading usage from either one alone
        undercounts, which for a budget ledger means a cap that does not hold.
        """
        payload = self._payload(messages, tools, system, max_tokens)
        payload["stream"] = True

        state = _StreamState(self._model)

        async for frame in stream_sse(
            self._client,
            f"{self._base_url}/v1/messages",
            payload,
            self._headers(),
            self.name,
        ):
            text = state.consume(frame)
            if text:
                yield TextDelta(text)

        yield state.finish(self.name)

    def _to_completion(self, body: dict[str, Any]) -> Completion:
        text_parts: list[str] = []
        thinking_parts: list[str] = []
        tool_calls: list[ToolCall] = []

        for block in _blocks(body.get("content")):
            kind = block.get("type")
            if kind == "text":
                value = block.get("text")
                if isinstance(value, str):
                    text_parts.append(value)
            elif kind == "thinking":
                # Extended thinking: its own block type, never part of the
                # answer. The signature beside it is for round-tripping and
                # is not kept.
                value = block.get("thinking")
                if isinstance(value, str):
                    thinking_parts.append(value)
            elif kind == "tool_use":
                arguments = block.get("input")
                tool_calls.append(
                    ToolCall(
                        id=str(block.get("id", "")),
                        name=str(block.get("name", "")),
                        arguments=arguments if isinstance(arguments, dict) else {},
                    )
                )

        usage = body.get("usage")
        usage = usage if isinstance(usage, dict) else {}

        return Completion(
            provider=self.name,
            model=str(body.get("model", self._model)),
            text="".join(text_parts),
            thinking="".join(thinking_parts) or None,
            usage=TokenUsage(
                input_tokens=_non_negative_int(usage.get("input_tokens")),
                output_tokens=_non_negative_int(usage.get("output_tokens")),
            ),
            tool_calls=tuple(tool_calls),
            stop_reason=_optional_str(body.get("stop_reason")),
        )


def _split_system(
    messages: Iterable[Message], system: str | None
) -> tuple[str | None, list[dict[str, str]]]:
    """Lift `Role.SYSTEM` turns into the top-level `system` field.

    Anthropic returns a 400 for a `system` role inside `messages`, so a caller
    that used the neutral shape naively would get a vendor error for something
    the protocol says is legal.
    """
    collected = [system] if system else []
    turns: list[dict[str, str]] = []

    for message in messages:
        if message.role is Role.SYSTEM:
            collected.append(message.content)
            continue
        # `tool` is not a role Anthropic accepts; a tool result is a user turn.
        role = "user" if message.role in (Role.USER, Role.TOOL) else "assistant"
        turns.append({"role": role, "content": message.content})

    return ("\n\n".join(collected) if collected else None), turns


def _blocks(content: Any) -> list[dict[str, Any]]:
    if not isinstance(content, list):
        return []
    return [block for block in content if isinstance(block, dict)]


def _non_negative_int(value: Any) -> int:
    """Coerce a reported token count, defaulting to 0 rather than raising.

    A provider that omits usage must not crash a run — but it also must not
    make the call look free, which is why the budget check happens *before*
    the call rather than relying on what comes back.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return max(0, value)


def _optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) else None


class _StreamState:
    """Reassembles Anthropic's streamed frames into one :class:`Completion`.

    The final object must be equivalent to what a non-streamed call would have
    returned (see :class:`~agentspace.providers.base.Provider`), so everything
    the blocking path reads off the response body has to be collected from a
    different frame here:

    ============  =====================================================
    field         where it arrives
    ============  =====================================================
    model         ``message_start``
    input tokens  ``message_start``
    text          ``content_block_delta`` / ``text_delta``
    tool calls    ``content_block_start`` plus ``input_json_delta`` parts
    output tokens ``message_delta`` (final frame, not the first)
    stop reason   ``message_delta``
    ============  =====================================================
    """

    def __init__(self, model: str) -> None:
        self._model = model
        self._text: list[str] = []
        self._thinking: list[str] = []
        self._blocks: dict[int, dict[str, Any]] = {}
        self._input_tokens = 0
        self._output_tokens = 0
        self._stop_reason: str | None = None
        self._error: str | None = None

    def consume(self, frame: dict[str, Any]) -> str:
        """Fold one frame in; return any text it contributed."""
        kind = frame.get("type")

        if kind == "message_start":
            self._message_start(frame)
        elif kind == "content_block_start":
            self._block_start(frame)
        elif kind == "content_block_delta":
            return self._block_delta(frame)
        elif kind == "message_delta":
            self._message_delta(frame)
        elif kind == "error":
            self._error = _error_message(frame)

        return ""

    def _message_start(self, frame: dict[str, Any]) -> None:
        message = frame.get("message")
        if not isinstance(message, dict):
            return

        model = message.get("model")
        if isinstance(model, str) and model:
            self._model = model

        usage = message.get("usage")
        if isinstance(usage, dict):
            self._input_tokens = _non_negative_int(usage.get("input_tokens"))
            # Present but near-zero at this point; the real figure lands on
            # `message_delta`. Taken anyway so a stream cut short still
            # reports something rather than nothing.
            self._output_tokens = _non_negative_int(usage.get("output_tokens"))

    def _block_start(self, frame: dict[str, Any]) -> None:
        block = frame.get("content_block")
        if not isinstance(block, dict) or block.get("type") != "tool_use":
            return

        index = _index_of(frame)
        self._blocks[index] = {
            "id": str(block.get("id", "")),
            "name": str(block.get("name", "")),
            "json": [],
        }

    def _block_delta(self, frame: dict[str, Any]) -> str:
        delta = frame.get("delta")
        if not isinstance(delta, dict):
            return ""

        if delta.get("type") == "text_delta":
            text = delta.get("text")
            if isinstance(text, str) and text:
                self._text.append(text)
                return text
            return ""

        if delta.get("type") == "thinking_delta":
            # Folded, not yielded: a `TextDelta` is the answer being typed.
            thinking = delta.get("thinking")
            if isinstance(thinking, str):
                self._thinking.append(thinking)
            return ""

        if delta.get("type") == "input_json_delta":
            partial = delta.get("partial_json")
            block = self._blocks.get(_index_of(frame))
            if isinstance(partial, str) and block is not None:
                parts: list[str] = block["json"]
                parts.append(partial)

        return ""

    def _message_delta(self, frame: dict[str, Any]) -> None:
        delta = frame.get("delta")
        if isinstance(delta, dict):
            stop = delta.get("stop_reason")
            if isinstance(stop, str):
                self._stop_reason = stop

        usage = frame.get("usage")
        if isinstance(usage, dict):
            output = usage.get("output_tokens")
            if output is not None:
                self._output_tokens = _non_negative_int(output)

    def finish(self, provider: str) -> Completion:
        """The assembled response.

        An `error` frame is raised rather than returned. Anthropic can send one
        mid-stream after a `200 OK`, so the status code alone does not decide
        whether the call succeeded — returning a truncated completion here
        would charge the user for a response that never finished and hand the
        orchestrator a silently incomplete answer.
        """
        if self._error is not None:
            msg = f"{provider} failed mid-stream: {self._error}"
            raise ProviderError(msg)

        tool_calls = [
            ToolCall(
                id=str(block["id"]),
                name=str(block["name"]),
                arguments=_parse_arguments(block["json"]),
            )
            for _, block in sorted(self._blocks.items())
        ]

        return Completion(
            provider=provider,
            model=self._model,
            text="".join(self._text),
            thinking="".join(self._thinking) or None,
            usage=TokenUsage(
                input_tokens=self._input_tokens,
                output_tokens=self._output_tokens,
            ),
            tool_calls=tuple(tool_calls),
            stop_reason=self._stop_reason,
        )


def _index_of(frame: dict[str, Any]) -> int:
    value = frame.get("index")
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _parse_arguments(parts: list[str]) -> dict[str, Any]:
    """Join the `input_json_delta` fragments and decode them.

    A tool call with no arguments streams zero fragments, which is an empty
    string rather than `{}` — decoding that would raise, so it is handled
    before `json.loads` sees it.
    """
    joined = "".join(parts).strip()
    if not joined:
        return {}

    try:
        parsed: Any = json.loads(joined)
    except ValueError:
        return {}

    return parsed if isinstance(parsed, dict) else {}


def _error_message(frame: dict[str, Any]) -> str:
    error = frame.get("error")
    if isinstance(error, dict):
        message = error.get("message")
        if isinstance(message, str):
            return message
    return "no reason given"
