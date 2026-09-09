"""The provider protocol every model backend implements.

BUILD_SPEC §5 Phase 3 asks for ``complete(messages, tools) -> Response`` with
*normalized* token usage, and the acceptance criterion is that switching
provider is a settings change with no code change. That only holds if nothing
above this module can tell which provider it is talking to — so the vendor
shapes stop here. Anthropic's ``input_tokens``/``output_tokens``, OpenAI's
``prompt_tokens``/``completion_tokens`` and Ollama's ``prompt_eval_count``/
``eval_count`` all arrive as :class:`TokenUsage`.

The abstraction deliberately does not assume cloud (§7): a provider may have no
API key and no cost. Ollama is the case that keeps that honest.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

__all__ = [
    "Completion",
    "Message",
    "Provider",
    "ProviderAuthError",
    "ProviderError",
    "ProviderRateLimitedError",
    "ProviderUnavailableError",
    "Role",
    "TokenUsage",
    "ToolCall",
    "ToolSpec",
]


class Role(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass(frozen=True, slots=True)
class Message:
    """One conversation turn, in the neutral shape."""

    role: Role
    content: str
    #: Set on ``TOOL`` messages: which tool call this is the result of.
    tool_call_id: str | None = None


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """A tool offered to the model. JSON Schema, because all three take that."""

    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ToolCall:
    """A tool the model asked to call. Nothing here executes it — Phase 6 does,
    and only through the approval gate."""

    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TokenUsage:
    """Normalized token counts.

    Integers, and non-negative. The budget ledger multiplies these by a price,
    so a provider that reports nothing must report zero rather than ``None`` —
    an unknown cost that silently becomes no cost is how a cap stops working.
    """

    input_tokens: int = 0
    output_tokens: int = 0

    def __post_init__(self) -> None:
        if self.input_tokens < 0 or self.output_tokens < 0:
            msg = f"token counts cannot be negative: {self!r}"
            raise ValueError(msg)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass(frozen=True, slots=True)
class Completion:
    """One model response, normalized."""

    provider: str
    model: str
    text: str
    usage: TokenUsage
    tool_calls: tuple[ToolCall, ...] = ()
    stop_reason: str | None = None


class ProviderError(RuntimeError):
    """Base class for every provider failure.

    Callers above this layer catch this and nothing vendor-specific; that is
    part of what "no code change to switch provider" means.
    """


class ProviderAuthError(ProviderError):
    """Missing, rejected or expired credentials. Not retryable."""


class ProviderRateLimitedError(ProviderError):
    """429 or equivalent. Retryable after a delay."""

    def __init__(self, message: str, retry_after_seconds: float | None = None) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class ProviderUnavailableError(ProviderError):
    """Transport failure or a 5xx. Retryable."""


@runtime_checkable
class Provider(Protocol):
    """What the orchestrator (Phase 4) is allowed to know about a model."""

    @property
    def name(self) -> str:
        """Stable identifier — ``anthropic``, ``openai``, ``ollama``."""
        ...

    @property
    def model(self) -> str:
        """The model this instance calls."""
        ...

    async def complete(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        *,
        system: str | None = None,
        max_tokens: int = 4096,
    ) -> Completion:
        """Send one request and return the normalized response."""
        ...
