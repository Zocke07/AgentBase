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
    TokenUsage,
    ToolCall,
    ToolSpec,
)
from agentspace.providers.transport import DEFAULT_TIMEOUT_SECONDS, post_json

if TYPE_CHECKING:
    from collections.abc import Iterable

__all__ = ["DEFAULT_BASE_URL", "MODEL_PREFIX", "OllamaProvider"]

#: The daemon's default address. Loopback, consistent with §1 constraint 3 —
#: though note this is an *outbound* address, not a bind.
DEFAULT_BASE_URL: Final[str] = "http://127.0.0.1:11434"

#: Model ids are namespaced so pricing can recognise them as free without
#: enumerating every model a user might have pulled.
MODEL_PREFIX: Final[str] = "ollama/"


class OllamaProvider:
    """Calls `POST /api/chat` with streaming disabled."""

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

    async def complete(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        *,
        system: str | None = None,
        max_tokens: int = 4096,
    ) -> Completion:
        payload: dict[str, Any] = {
            "model": self.remote_model,
            "messages": _to_ollama_messages(messages, system),
            # The protocol returns one Completion; a streamed body would have
            # to be reassembled here for no benefit. Token streaming to the UI
            # is an orchestrator concern (Phase 4's `llm.token` events).
            "stream": False,
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

        # No auth header: there is no key, and inventing one would be the
        # cloud assumption this provider exists to rule out.
        body = await post_json(
            self._client,
            f"{self._base_url}/api/chat",
            payload,
            {"content-type": "application/json"},
            self.name,
        )

        return self._to_completion(body)

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
