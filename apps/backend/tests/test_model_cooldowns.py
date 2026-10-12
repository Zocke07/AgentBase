"""Exercise cooldowns through the agent's real streamed model boundary."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

import pytest

from agentbase.events.types import EventType
from agentbase.orchestrator.agent import Agent, AgentSpec
from agentbase.orchestrator.limits import RunLimits
from agentbase.orchestrator.run import Mailbox, Run, RunCancelledError, RunCostExceededError
from agentbase.providers.base import (
    Completion,
    Message,
    ProviderRateLimitedError,
    Role,
    TextDelta,
    TokenUsage,
)

if TYPE_CHECKING:
    from agentbase.events.store import EventStore
    from agentbase.providers.base import StreamEvent, ToolSpec

pytestmark = pytest.mark.anyio


class ThrottledProvider:
    name = "openai"
    model = "gpt-5.6-luna"

    def __init__(self, errors: list[ProviderRateLimitedError], *, partial: bool = False):
        self.errors = list(errors)
        self.partial = partial
        self.calls = 0
        self.closed = 0

    async def stream(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        *,
        system: str | None = None,
        max_tokens: int = 4096,
    ) -> AsyncIterator[StreamEvent]:
        self.calls += 1
        try:
            if self.errors:
                if self.partial:
                    yield TextDelta(text="Already visible")
                raise self.errors.pop(0)
            yield Completion(
                provider=self.name,
                model=self.model,
                text="Done",
                usage=TokenUsage(input_tokens=10, output_tokens=2),
            )
        finally:
            self.closed += 1

    async def complete(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        *,
        system: str | None = None,
        max_tokens: int = 4096,
    ) -> Completion:
        async for event in self.stream(messages, tools, system=system, max_tokens=max_tokens):
            if isinstance(event, Completion):
                return event
        raise AssertionError("No completion")


async def make_agent(
    store: EventStore,
    provider: ThrottledProvider,
    *,
    seconds: int = 600,
    cancel_on_sleep: bool = False,
) -> tuple[Agent, Run, list[float]]:
    row = await store.create_run(goal="Test cooldown", origin="ui")
    now = [0.0]
    waits: list[float] = []
    run = Run(store, row.id, row.goal, RunLimits(max_run_seconds=seconds), clock=lambda: now[0])
    await run.start()

    async def sleep(delay: float) -> None:
        waits.append(delay)
        now[0] += delay
        if cancel_on_sleep:
            run.request_cancel("Stopped by the user")

    agent = Agent(
        run,
        Mailbox(run),
        provider,
        AgentSpec(name="worker", role="Test", system_prompt="Test"),
        [],
        "supervisor",
        sleep=sleep,
        retry_jitter=lambda: 0.0,
    )
    return agent, run, waits


async def test_temporary_429_cools_down_then_returns_one_completion(store: EventStore) -> None:
    provider = ThrottledProvider([ProviderRateLimitedError("Slow down")])
    agent, run, waits = await make_agent(store, provider)
    result = await agent._call_model([Message(role=Role.USER, content="test")], 1)
    events = await store.read(run.id)
    assert result.text == "Done"
    assert provider.calls == provider.closed == 2
    assert sum(waits) == 60
    assert [e.payload["attempt"] for e in events if e.type == EventType.LLM_REQUEST] == [1, 2]
    errors = [e.payload for e in events if e.type == EventType.LLM_ERROR]
    assert errors[0]["will_retry"] is True and errors[0]["retry_after_seconds"] == 60
    assert sum(e.type == EventType.LLM_RESPONSE for e in events) == 1


async def test_retry_attempts_are_bounded(store: EventStore) -> None:
    provider = ThrottledProvider([ProviderRateLimitedError("Slow down") for _ in range(4)])
    agent, run, waits = await make_agent(store, provider)
    with pytest.raises(ProviderRateLimitedError):
        await agent._call_model([], 1)
    assert provider.calls == provider.closed == 3
    assert sum(waits) == 180
    errors = [e.payload for e in await store.read(run.id) if e.type == EventType.LLM_ERROR]
    assert [e["will_retry"] for e in errors] == [True, True, False]


@pytest.mark.parametrize(
    ("error", "seconds", "partial"),
    [
        (ProviderRateLimitedError("Quota reached", retryable=False), 600, False),
        (ProviderRateLimitedError("Retry tomorrow", retry_after_seconds=3600), 600, False),
        (ProviderRateLimitedError("Slow down"), 60, False),
        (ProviderRateLimitedError("Slow down"), 600, True),
    ],
)
async def test_quota_long_hints_short_deadlines_and_partial_output_are_not_retried(
    store: EventStore,
    error: ProviderRateLimitedError,
    seconds: int,
    partial: bool,
) -> None:
    provider = ThrottledProvider([error], partial=partial)
    agent, run, waits = await make_agent(store, provider, seconds=seconds)
    with pytest.raises(ProviderRateLimitedError):
        await agent._call_model([], 1)
    assert provider.calls == provider.closed == 1 and waits == []
    errors = [e.payload for e in await store.read(run.id) if e.type == EventType.LLM_ERROR]
    assert errors[0]["will_retry"] is False


async def test_server_hint_is_the_minimum_wait(store: EventStore) -> None:
    provider = ThrottledProvider(
        [ProviderRateLimitedError("Slow down", retry_after_seconds=90)]
    )
    agent, _, waits = await make_agent(store, provider)
    await agent._call_model([], 1)
    assert sum(waits) == 90


async def test_user_stop_interrupts_cooldown_before_another_call(store: EventStore) -> None:
    provider = ThrottledProvider([ProviderRateLimitedError("Slow down")])
    agent, _, waits = await make_agent(store, provider, cancel_on_sleep=True)
    with pytest.raises(RunCancelledError, match="Stopped by the user"):
        await agent._call_model([], 1)
    assert provider.calls == 1 and sum(waits) == 1


async def test_cooldown_rechecks_the_run_budget_before_retrying(store: EventStore) -> None:
    provider = ThrottledProvider([ProviderRateLimitedError("Slow down")])
    agent, run, waits = await make_agent(store, provider)
    checks = 0

    async def spent() -> int:
        nonlocal checks
        checks += 1
        return 0 if checks == 1 else run.limits.max_run_cost_micros

    run.spent_so_far = spent
    with pytest.raises(RunCostExceededError):
        await agent._call_model([], 1)
    assert checks == 2 and provider.calls == 1 and sum(waits) == 60


class BrokenCloseStream:
    def __aiter__(self) -> BrokenCloseStream:
        return self

    async def __anext__(self) -> StreamEvent:
        raise ProviderRateLimitedError("Original usage limit", retryable=False)

    async def aclose(self) -> None:
        raise RuntimeError("Cleanup failed")


class ClosingFailureProvider(ThrottledProvider):
    def stream(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        *,
        system: str | None = None,
        max_tokens: int = 4096,
    ) -> AsyncIterator[StreamEvent]:
        return BrokenCloseStream()


async def test_stream_cleanup_does_not_hide_the_original_provider_error(
    store: EventStore,
) -> None:
    provider = ClosingFailureProvider([])
    agent, _, waits = await make_agent(store, provider)
    with pytest.raises(ProviderRateLimitedError, match="Original usage limit"):
        await agent._call_model([], 1)
    assert waits == []
