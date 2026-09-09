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

from typing import TYPE_CHECKING, Any, Final

import httpx2

from agentspace.providers.base import (
    Completion,
    Message,
    ProviderAuthError,
    Role,
    TokenUsage,
    ToolCall,
    ToolSpec,
)
from agentspace.providers.transport import DEFAULT_TIMEOUT_SECONDS, post_json

if TYPE_CHECKING:
    from collections.abc import Iterable

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

    async def complete(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        *,
        system: str | None = None,
        max_tokens: int = 4096,
    ) -> Completion:
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

        body = await post_json(
            self._client,
            f"{self._base_url}/v1/messages",
            payload,
            {
                "x-api-key": self._api_key,
                "anthropic-version": ANTHROPIC_VERSION,
                "content-type": "application/json",
            },
            self.name,
        )

        return self._to_completion(body)

    def _to_completion(self, body: dict[str, Any]) -> Completion:
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []

        for block in _blocks(body.get("content")):
            kind = block.get("type")
            if kind == "text":
                value = block.get("text")
                if isinstance(value, str):
                    text_parts.append(value)
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
