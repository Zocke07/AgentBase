"""The chat edit throttle's arithmetic, on a clock the test holds.

The conversation tests shorten the interval so they do not wait on a real
rate limit; this is where the interval itself is held to its meaning.
"""

from __future__ import annotations

from agentbase.channels.service import _LIMITS
from agentbase.channels.throttle import DISCORD_EDIT_INTERVAL, Throttle


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_the_first_send_is_due_and_the_next_waits_out_the_interval() -> None:
    clock = Clock()
    throttle = Throttle(1.6, clock=clock)

    assert throttle.seconds_until_due() == 0.0
    assert throttle.due()

    clock.now += 0.5
    assert not throttle.due()
    assert abs(throttle.seconds_until_due() - 1.1) < 1e-9

    clock.now += 1.1
    assert throttle.due()
    assert abs(throttle.seconds_until_due() - 1.6) < 1e-9


def test_a_refused_send_does_not_restart_the_wait() -> None:
    clock = Clock()
    throttle = Throttle(1.6, clock=clock)
    assert throttle.due()

    for _ in range(3):
        clock.now += 0.5
        assert not throttle.due()

    # 1.5 seconds on: asking three times has not pushed the next send back.
    assert abs(throttle.seconds_until_due() - 0.1) < 1e-9


def test_an_urgent_send_goes_at_once_and_counts_as_the_last() -> None:
    clock = Clock()
    throttle = Throttle(1.6, clock=clock)
    assert throttle.due()

    clock.now += 0.2
    assert throttle.due(force=True)
    clock.now += 1.5
    assert not throttle.due()
    assert throttle.seconds_until_due() > 0.0
    clock.now += 5.0
    assert throttle.seconds_until_due() == 0.0


def test_discord_edits_at_the_documented_interval() -> None:
    _limit, interval = _LIMITS["discord"]
    assert interval == DISCORD_EDIT_INTERVAL
