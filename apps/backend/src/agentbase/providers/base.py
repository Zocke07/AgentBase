"""Protocol implemented by every model backend.

Vendor shapes stop here: callers receive :class:`TokenUsage` regardless of
provider. Some providers, such as Ollama, have neither API keys nor cost.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

__all__ = [
    "Completion",
    "Message",
    "Provider",
    "ProviderAuthError",
    "ProviderError",
    "ProviderRateLimitedError",
    "ProviderUnavailableError",
    "Role",
    "StreamEvent",
    "TextDelta",
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
    """Provider-neutral conversation turn."""

    role: Role
    content: str
    #: Tool call whose result this ``TOOL`` message carries.
    tool_call_id: str | None = None


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """Tool offered to the model; all providers take JSON Schema."""

    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ToolCall:
    """Tool call requested by model; this object never executes it."""

    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TokenUsage:
    """Normalized nonnegative integer token counts; use zero, not ``None``."""

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
    """Normalized model response."""

    provider: str
    model: str
    text: str
    usage: TokenUsage
    tool_calls: tuple[ToolCall, ...] = ()
    stop_reason: str | None = None
    #: Integer micros recorded by budget wrapper; ``None`` from unwrapped provider.
    cost_micros: int | None = None
    #: Provider reasoning (Ollama ``message.thinking``, Anthropic blocks), or
    #: ``None`` when absent, distinct from ``""`` for replay. Never in ``text``
    #: or :class:`TextDelta`.
    thinking: str | None = None


@dataclass(frozen=True, slots=True)
class TextDelta:
    """Incremental assistant-text chunk from a stream.

    Adapters accumulate partial tool calls and surface complete ones only in
    final :class:`Completion`; callers cannot act on partial argument objects.
    """

    text: str


#: :meth:`Provider.stream` yields zero or more :class:`TextDelta`, then exactly
#: one :class:`Completion` with usage, tool calls, and stop reason.
StreamEvent = TextDelta | Completion


class ProviderError(RuntimeError):
    """Base provider failure; callers catch this, never vendor-specific types."""


class ProviderAuthError(ProviderError):
    """Missing, rejected, or expired credentials; not retryable."""


class ProviderRateLimitedError(ProviderError):
    """429 or equivalent; retryable after delay."""

    def __init__(self, message: str, retry_after_seconds: float | None = None) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class ProviderUnavailableError(ProviderError):
    """Transport failure or 5xx; retryable."""


class ProviderModelUnavailableError(ProviderError):
    """The account cannot use the requested model; not retryable.

    The model is never swapped for another: the person chooses one.
    """


@runtime_checkable
class Provider(Protocol):
    """Model information and operations visible to orchestrator."""

    @property
    def name(self) -> str:
        """Stable identifier: ``anthropic``, ``openai``, ``ollama``."""
        ...

    @property
    def model(self) -> str:
        """Model this instance calls."""
        ...

    async def complete(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        *,
        system: str | None = None,
        max_tokens: int = 4096,
    ) -> Completion:
        """Send a request and return normalized response."""
        ...

    def stream(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        *,
        system: str | None = None,
        max_tokens: int = 4096,
    ) -> AsyncIterator[StreamEvent]:
        """Send request and yield response as it arrives.

        Yield zero or more :class:`TextDelta`, then one :class:`Completion`
        equivalent to :meth:`complete`. Use ``def`` because async-generator
        calls return the iterator.
        """
        ...
