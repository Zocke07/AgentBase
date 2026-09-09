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
    TokenUsage,
    ToolCall,
    ToolSpec,
)
from agentspace.providers.transport import DEFAULT_TIMEOUT_SECONDS, post_json

if TYPE_CHECKING:
    from collections.abc import Iterable

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

    async def complete(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        *,
        system: str | None = None,
        max_tokens: int = 4096,
    ) -> Completion:
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

        body = await post_json(
            self._client,
            f"{self._base_url}/v1/chat/completions",
            payload,
            {
                "authorization": f"Bearer {self._api_key}",
                "content-type": "application/json",
            },
            self.name,
        )

        return self._to_completion(body)

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


def _tool_calls(raw: Any) -> list[ToolCall]:
    """Parse `tool_calls`, whose `arguments` is a JSON *string*.

    A model can emit arguments that are not valid JSON. That is a bad tool
    call, not a crashed run, so it degrades to empty arguments and lets the
    approval gate and the tool itself reject it with a legible message.
    """
    if not isinstance(raw, list):
        return []

    calls: list[ToolCall] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        function = entry.get("function")
        function = function if isinstance(function, dict) else {}

        arguments: dict[str, Any] = {}
        encoded = function.get("arguments")
        if isinstance(encoded, str) and encoded.strip():
            try:
                decoded = json.loads(encoded)
            except json.JSONDecodeError:
                decoded = None
            if isinstance(decoded, dict):
                arguments = decoded

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
