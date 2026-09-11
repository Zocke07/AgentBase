"""Outbound rate limiting, per §5 Phase 8.

The spec asks to "throttle outbound through the adapter", naming Discord's
global 50 req/s. That number is far above anything this application can
produce, and quoting it is slightly misleading about where the real limit is:
the binding constraint is the *per-route* bucket on editing a message, which
on Discord is roughly five edits per five seconds for one webhook token.

A run streams hundreds of events. Editing the message on each one would exhaust
that bucket in the first second of a run, and the platform's response is a 429
whose retry-after grows — so the message would stop updating at exactly the
moment the run got interesting, which is the failure this module exists to
prevent.

**The design that makes the limits nearly moot is not this module.** It is that
a run owns exactly one message and re-renders it, so the traffic is bounded by
the throttle interval rather than by how talkative the run is. This class is
what turns "an event arrived" into "it is worth spending an edit now", and its
one subtlety is :meth:`due`'s ``force``: a terminal event and an approval
request must go out immediately, because a user staring at a stale message has
no way to tell a throttled render from a crashed bot.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = [
    "DISCORD_EDIT_INTERVAL",
    "Throttle",
]

#: Comfortably inside Discord's per-token edit bucket, and fast enough that a
#: run reads as live.
DISCORD_EDIT_INTERVAL: Final[float] = 1.6


class Throttle:
    """Minimum interval between sends, with an override for events that cannot wait.

    Not a token bucket. A bucket permits a burst and then stalls, which is the
    wrong shape here: this is one message being edited, so a burst of five edits
    in a second shows the user four frames they will never read and then leaves
    them staring at a stale one when the bucket is empty. A flat minimum
    interval spends every edit on the most recent state.
    """

    __slots__ = ("_clock", "_interval", "_last")

    def __init__(self, interval: float, *, clock: Callable[[], float] | None = None) -> None:
        self._interval = interval
        self._clock = clock if clock is not None else time.monotonic
        #: `None` rather than 0.0 so the first send is always allowed, whatever
        #: the clock's origin happens to be. A monotonic clock starting near
        #: zero would otherwise make the very first edit wait a full interval.
        self._last: float | None = None

    def due(self, *, force: bool = False) -> bool:
        """Whether to send now, marking the send if so.

        :param force: send regardless of the interval. For the two cases where
            waiting is worse than a rate-limit risk — a terminal event, and an
            approval the run is suspended on. A user who cannot tell "throttled"
            from "crashed" will assume crashed.
        """
        now = self._clock()
        if force or self._last is None or now - self._last >= self._interval:
            self._last = now
            return True
        return False

    def seconds_until_due(self) -> float:
        """How long until :meth:`due` would return true. Never negative."""
        if self._last is None:
            return 0.0
        return max(0.0, self._interval - (self._clock() - self._last))
