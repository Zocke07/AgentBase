"""Tests for the in-process fan-out.

The bus is a hint that new rows exist, not a delivery guarantee — so the
behaviour worth pinning down is what happens when it *fails* to deliver:
overflow, disconnect, and out-of-order publication.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from agentspace.events.bus import EventBus, Subscription
from agentspace.events.types import Event, EventType

pytestmark = pytest.mark.anyio


def _event(seq: int, run_id: str = "run-1") -> Event:
    return Event(
        id=seq,
        run_id=run_id,
        seq=seq,
        type=EventType.AGENT_MESSAGE,
        payload={"i": seq},
        ts=datetime.now(UTC),
    )


async def test_subscriber_receives_published_events(bus: EventBus) -> None:
    with bus.subscribe("run-1") as subscription:
        bus.publish(_event(1))

        received = await subscription.get(1)

    assert received is not None
    assert received.seq == 1


async def test_events_are_only_delivered_to_their_own_run(bus: EventBus) -> None:
    with bus.subscribe("run-1") as subscription:
        bus.publish(_event(1, run_id="run-2"))

        assert await subscription.get(0.05) is None


async def test_every_subscriber_of_a_run_receives_the_event(bus: EventBus) -> None:
    """Two dashboard windows on the same run, or a webview plus a curl client."""
    with bus.subscribe("run-1") as first, bus.subscribe("run-1") as second:
        bus.publish(_event(1))

        assert (await first.get(1)) is not None
        assert (await second.get(1)) is not None


async def test_publishing_with_no_subscribers_is_not_an_error(bus: EventBus) -> None:
    bus.publish(_event(1))


async def test_subscription_is_unregistered_on_exit(bus: EventBus) -> None:
    with bus.subscribe("run-1"):
        assert bus.subscriber_count("run-1") == 1

    assert bus.subscriber_count("run-1") == 0


async def test_subscription_is_unregistered_when_the_block_raises(bus: EventBus) -> None:
    """An SSE client that disconnects mid-stream is cancelled, not returned
    from. A leak here is a slow memory leak that only shows under real use."""
    with pytest.raises(RuntimeError), bus.subscribe("run-1"):
        raise RuntimeError("client went away")

    assert bus.subscriber_count("run-1") == 0


async def test_get_returns_none_on_timeout(bus: EventBus) -> None:
    """What lets the SSE loop emit keepalives instead of blocking forever."""
    with bus.subscribe("run-1") as subscription:
        assert await subscription.get(0.05) is None


# --- backpressure -----------------------------------------------------------


async def test_overflow_marks_the_subscription_stale_instead_of_growing() -> None:
    bus = EventBus(queue_size=4)

    with bus.subscribe("run-1") as subscription:
        for seq in range(1, 20):
            bus.publish(_event(seq))

        assert subscription.stale


async def test_going_stale_releases_the_buffer() -> None:
    """The consumer is about to re-read the range from SQLite, so holding the
    buffered copies wastes memory during the one episode where it is scarce."""
    bus = EventBus(queue_size=4)

    with bus.subscribe("run-1") as subscription:
        for seq in range(1, 20):
            bus.publish(_event(seq))

        assert await subscription.get(0.05) is None


async def test_a_stale_subscription_recovers_after_the_consumer_catches_up() -> None:
    bus = EventBus(queue_size=4)

    with bus.subscribe("run-1") as subscription:
        for seq in range(1, 20):
            bus.publish(_event(seq))
        assert subscription.stale

        subscription.clear_stale()
        bus.publish(_event(20))

        received = await subscription.get(1)

    assert received is not None
    assert received.seq == 20


async def test_one_slow_subscriber_does_not_affect_a_healthy_one() -> None:
    bus = EventBus(queue_size=4)

    with bus.subscribe("run-1") as slow, bus.subscribe("run-1") as healthy:
        for seq in range(1, 20):
            bus.publish(_event(seq))
            # The healthy subscriber keeps draining; the slow one never does.
            await healthy.get(1)

        assert slow.stale
        assert not healthy.stale


async def test_subscription_queue_is_bounded_by_construction() -> None:
    subscription = Subscription("run-1", maxsize=2)

    for seq in range(1, 10):
        subscription.offer(_event(seq))

    assert subscription.stale
