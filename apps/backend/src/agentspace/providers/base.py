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
    #: What this call cost, in integer micros. Filled in by the budget wrapper
    #: the moment it records the spend, so the figure in the event log is the
    #: figure in the ledger. ``None`` from a provider that was not wrapped.
    cost_micros: int | None = None
    #: Reasoning the provider exposed separately from its answer — Ollama's
    #: ``message.thinking``, Anthropic's thinking blocks. ``None`` when the
    #: provider exposed none, which is different from ``""``: a model that
    #: reasoned at length and answered with nothing is the case this exists
    #: for. Phase 5 watched a local model do exactly that five times running
    #: and the log said it had produced nothing. Not part of ``text`` and
    #: never a :class:`TextDelta` — reasoning is not the answer — but it rides
    #: in ``llm.response`` so a replay can tell silence from thought.
    thinking: str | None = None


@dataclass(frozen=True, slots=True)
class TextDelta:
    """One incremental chunk of assistant text from a streaming call.

    Deliberately *only* text. Tool-call arguments also arrive incrementally
    from every vendor, but a half-parsed argument object is not something any
    caller can act on — the orchestrator cannot request approval for a tool
    call it can only see two thirds of. Partial tool calls are therefore
    accumulated inside each adapter and surface once, complete, on the final
    :class:`Completion`.
    """

    text: str


#: What :meth:`Provider.stream` yields.
#:
#: The contract is: zero or more :class:`TextDelta`, then **exactly one**
#: :class:`Completion` as the final item. The terminal ``Completion`` is what
#: carries usage, tool calls and the stop reason, so a consumer that stops
#: iterating early gets no usage — which is precisely why the budget ledger
#: records spend from the terminal item rather than from the deltas.
StreamEvent = TextDelta | Completion


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

    def stream(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        *,
        system: str | None = None,
        max_tokens: int = 4096,
    ) -> AsyncIterator[StreamEvent]:
        """Send one request and yield the response as it arrives.

        Yields zero or more :class:`TextDelta`, then exactly one
        :class:`Completion`. Implementations are async generators, which is why
        this is declared ``def`` returning an ``AsyncIterator`` rather than
        ``async def`` — calling an async generator function returns the
        iterator, it does not await it.

        The final :class:`Completion` must be equivalent to what
        :meth:`complete` would have returned for the same arguments. Anything
        else makes the choice to stream a behavioural change rather than a
        transport one, and the orchestrator would have to care which it used.
        """
        ...
