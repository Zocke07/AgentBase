"""Anthropic Messages API adapter.

Anthropic requires a top-level system prompt and ``max_tokens``. Every request
asks for prompt caching: each agent step re-sends its whole conversation, and
a cached prefix costs a small fraction of the input rate (2026-10-14).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

import httpx2

from agentbase.providers.base import (
    Completion,
    Message,
    ProviderAuthError,
    ProviderError,
    ProviderOverloadedError,
    Role,
    StreamEvent,
    TextDelta,
    TokenUsage,
    ToolCall,
    ToolSpec,
    decode_arguments,
    mentions_overload,
)
from agentbase.providers.transport import (
    DEFAULT_TIMEOUT_SECONDS,
    post_json,
    stream_sse,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterable

__all__ = ["ANTHROPIC_VERSION", "DEFAULT_BASE_URL", "AnthropicProvider"]

DEFAULT_BASE_URL: Final[str] = "https://api.anthropic.com"

#: Pin the wire format used by shipped builds.
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
        """Build the request body shared by blocking and streaming calls."""
        if not self._api_key:
            msg = "no Anthropic API key is configured"
            raise ProviderAuthError(msg)

        system_prompt, turns = _split_system(messages, system)

        payload: dict[str, Any] = {
            "model": self._model,
            "max_tokens": max_tokens,
            "messages": turns,
            # Automatic caching: the breakpoint goes on the last block, so the
            # next step reads this request's prompt from the cache.
            "cache_control": {"type": "ephemeral"},
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
        """Stream ``POST /v1/messages`` and collect token counts across frames."""
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
                # Keep extended thinking separate from answer text.
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
        prompt, read, written = _prompt_counts(usage)

        return Completion(
            provider=self.name,
            model=str(body.get("model", self._model)),
            text="".join(text_parts),
            thinking="".join(thinking_parts) or None,
            usage=TokenUsage(
                input_tokens=prompt,
                output_tokens=_non_negative_int(usage.get("output_tokens")),
                cache_read_tokens=read,
                cache_write_tokens=written,
            ),
            tool_calls=tuple(tool_calls),
            stop_reason=_optional_str(body.get("stop_reason")),
        )


def _split_system(
    messages: Iterable[Message], system: str | None
) -> tuple[str | None, list[dict[str, Any]]]:
    """Move ``Role.SYSTEM`` turns into Anthropic's top-level system field.

    Calls go back as ``tool_use`` blocks and results as ``tool_result`` blocks
    naming them. As plain text, a result looked like an unasked-for user turn,
    and Claude Haiku 4.5 repeated the read it had already made.
    """
    collected = [system] if system else []
    turns: list[dict[str, Any]] = []

    for message in messages:
        if message.role is Role.SYSTEM:
            collected.append(message.content)
        elif message.role is Role.ASSISTANT and message.tool_calls:
            turns.append({"role": "assistant", "content": _call_blocks(message)})
        elif message.role is Role.TOOL and message.tool_call_id:
            _answer(turns, message.tool_call_id, message.content)
        else:
            # A result naming no call can only go back as a user turn.
            role = "user" if message.role in (Role.USER, Role.TOOL) else "assistant"
            turns.append({"role": role, "content": message.content})

    return ("\n\n".join(collected) if collected else None), turns


def _call_blocks(message: Message) -> list[dict[str, Any]]:
    """Prose, if any, then each call; the API refuses a blank text block."""
    blocks: list[dict[str, Any]] = []
    if message.content.strip():
        blocks.append({"type": "text", "text": message.content})
    blocks.extend(
        {"type": "tool_use", "id": call.id, "name": call.name, "input": call.arguments}
        for call in message.tool_calls
    )
    return blocks


def _answer(turns: list[dict[str, Any]], call_id: str, content: str) -> None:
    """Add a result to the user turn that answers its call.

    Every call in one answer must be answered in the single user turn after it.
    """
    block: dict[str, Any] = {"type": "tool_result", "tool_use_id": call_id}
    if content.strip():
        # Content is optional; blank text is refused.
        block["content"] = content

    previous = turns[-1] if turns else None
    if (
        previous is not None
        and previous["role"] == "user"
        and isinstance(previous["content"], list)
    ):
        previous["content"].append(block)
    else:
        turns.append({"role": "user", "content": [block]})


def _blocks(content: Any) -> list[dict[str, Any]]:
    if not isinstance(content, list):
        return []
    return [block for block in content if isinstance(block, dict)]


#: Anthropic's three prompt counts: after the cache, read from it, written to it.
_PROMPT_FIELDS: Final[tuple[str, ...]] = (
    "input_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
)


def _prompt_counts(usage: dict[str, Any]) -> tuple[int, int, int]:
    """The whole prompt, and its parts read from and written to the cache.

    Anthropic's ``input_tokens`` counts only what follows the cached part.
    """
    read = _non_negative_int(usage.get("cache_read_input_tokens"))
    written = _non_negative_int(usage.get("cache_creation_input_tokens"))
    return _non_negative_int(usage.get("input_tokens")) + read + written, read, written


def _non_negative_int(value: Any) -> int:
    """Coerce a reported token count, defaulting to 0 rather than raising."""
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return max(0, value)


def _optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) else None


class _StreamState:
    """Fold Anthropic frames into a :class:`Completion`.

    Model and input usage arrive at start; text and tool JSON arrive in block
    deltas; output usage and stop reason arrive in the final message delta.
    """

    def __init__(self, model: str) -> None:
        self._model = model
        self._text: list[str] = []
        self._thinking: list[str] = []
        self._blocks: dict[int, dict[str, Any]] = {}
        # Anthropic's prompt counts as reported, each kept until a later frame
        # repeats it.
        self._prompt_usage: dict[str, Any] = {}
        self._output_tokens = 0
        self._stop_reason: str | None = None
        self._error: str | None = None
        self._overloaded = False

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
            error = frame.get("error")
            self._overloaded = (
                isinstance(error, dict) and error.get("type") == "overloaded_error"
            )

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
            self._prompt(usage)
            # Final ``message_delta`` reports the definitive output count.
            self._output_tokens = _non_negative_int(usage.get("output_tokens"))

    def _prompt(self, usage: dict[str, Any]) -> None:
        for field in _PROMPT_FIELDS:
            if usage.get(field) is not None:
                self._prompt_usage[field] = usage[field]

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
            # Preserve thinking without yielding it as answer text.
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
            # Counts here are cumulative: one that repeats a prompt count replaces it.
            self._prompt(usage)

    def finish(self, provider: str) -> Completion:
        """Build the response or raise an error received after HTTP success."""
        if self._error is not None:
            if self._overloaded or mentions_overload(self._error):
                msg = f"{provider} is at capacity right now, which usually passes within minutes: {self._error}"
                raise ProviderOverloadedError(msg)
            msg = f"{provider} failed mid-stream: {self._error}"
            raise ProviderError(msg)

        tool_calls = [
            ToolCall(
                id=str(block["id"]),
                name=str(block["name"]),
                arguments=arguments,
                argument_error=problem,
            )
            for _, block in sorted(self._blocks.items())
            for arguments, problem in [decode_arguments("".join(block["json"]))]
        ]
        prompt, read, written = _prompt_counts(self._prompt_usage)

        return Completion(
            provider=provider,
            model=self._model,
            text="".join(self._text),
            thinking="".join(self._thinking) or None,
            usage=TokenUsage(
                input_tokens=prompt,
                output_tokens=self._output_tokens,
                cache_read_tokens=read,
                cache_write_tokens=written,
            ),
            tool_calls=tuple(tool_calls),
            stop_reason=self._stop_reason,
        )


def _index_of(frame: dict[str, Any]) -> int:
    value = frame.get("index")
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _error_message(frame: dict[str, Any]) -> str:
    error = frame.get("error")
    if isinstance(error, dict):
        message = error.get("message")
        if isinstance(message, str):
            return message
    return "no reason given"
