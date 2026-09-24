"""The provider protocol every model backend implements.

Nothing above this module can tell which provider it is talking to: vendor
shapes stop here, and every provider's token counts arrive as
:class:`TokenUsage`. A provider may have no API key and no cost (Ollama).
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
    """A tool the model asked to call. Nothing here executes it."""

    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TokenUsage:
    """Normalized token counts: integers, non-negative, zero rather than ``None``."""

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
    #: What this call cost, in integer micros, filled in by the budget wrapper
    #: as it records the spend. ``None`` from a provider that was not wrapped.
    cost_micros: int | None = None
    #: Reasoning the provider exposed beside its answer (Ollama's
    #: ``message.thinking``, Anthropic's thinking blocks). ``None`` when none
    #: was exposed, distinct from ``""``, so a replay can tell silence from
    #: thought. Never part of ``text`` and never a :class:`TextDelta`.
    thinking: str | None = None


@dataclass(frozen=True, slots=True)
class TextDelta:
    """One incremental chunk of assistant text from a streaming call.

    Only text: partial tool calls are accumulated inside each adapter and
    surface complete on the final :class:`Completion`, since nobody can act
    on two thirds of an argument object.
    """

    text: str


#: What :meth:`Provider.stream` yields: zero or more :class:`TextDelta`, then
#: exactly one :class:`Completion`, which carries usage, tool calls and the stop reason.
StreamEvent = TextDelta | Completion


class ProviderError(RuntimeError):
    """Base class for every provider failure. Callers catch this and nothing vendor-specific."""


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
    """What the orchestrator is allowed to know about a model."""

    @property
    def name(self) -> str:
        """Stable identifier: ``anthropic``, ``openai``, ``ollama``."""
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

    def stream(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        *,
        system: str | None = None,
        max_tokens: int = 4096,
    ) -> AsyncIterator[StreamEvent]:
        """Send one request and yield the response as it arrives.

        Zero or more :class:`TextDelta`, then exactly one :class:`Completion`
        equivalent to what :meth:`complete` would have returned. Declared
        ``def`` because calling an async generator returns the iterator.
        """
        ...
