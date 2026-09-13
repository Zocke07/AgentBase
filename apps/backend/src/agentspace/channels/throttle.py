"""Outbound rate limiting for the chat reply.

The binding limit is not Discord's global 50 req/s but the per-route bucket
on editing one message, roughly five edits per five seconds. A run owns one
message and re-renders it, so traffic is bounded by this interval rather than
by how talkative the run is. A terminal event or an approval request goes out
at once, because a stale message is indistinguishable from a crashed bot.
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

#: Inside Discord's per-token edit bucket, and fast enough that a run reads as live.
DISCORD_EDIT_INTERVAL: Final[float] = 1.6


class Throttle:
    """Minimum interval between sends, with an override for events that cannot wait.

    Not a token bucket: a burst of edits to one message shows frames nobody
    reads and then stalls. A flat interval spends every edit on the latest state.
    """

    __slots__ = ("_clock", "_interval", "_last")

    def __init__(self, interval: float, *, clock: Callable[[], float] | None = None) -> None:
        self._interval = interval
        self._clock = clock if clock is not None else time.monotonic
        #: `None` rather than 0.0 so the first send is allowed whatever the clock's origin.
        self._last: float | None = None

    def due(self, *, force: bool = False) -> bool:
        """Whether to send now, marking the send if so.

        :param force: send regardless of the interval (a terminal event, an approval).
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
