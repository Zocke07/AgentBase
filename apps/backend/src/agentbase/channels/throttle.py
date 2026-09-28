"""Outbound chat-reply rate limiting.

Discord's limiting bucket applies to one-message edits, roughly five per five
seconds, not its global 50 req/s. Rerender a run's single message at this
interval regardless of activity; send terminal events and approval requests
immediately because stale status resembles a crashed bot.
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

#: Within Discord's edit bucket while keeping runs visibly live.
DISCORD_EDIT_INTERVAL: Final[float] = 1.6


class Throttle:
    """Minimum send interval with an override for urgent events.

    Avoid token buckets: a burst shows unread frames then stalls. A flat
    interval spends each edit on current state.
    """

    __slots__ = ("_clock", "_interval", "_last")

    def __init__(self, interval: float, *, clock: Callable[[], float] | None = None) -> None:
        self._interval = interval
        self._clock = clock if clock is not None else time.monotonic
        #: Use ``None``, not 0.0, so the first send works for every clock origin.
        self._last: float | None = None

    def due(self, *, force: bool = False) -> bool:
        """Return and mark whether to send now.

        :param force: bypass interval for a terminal event or approval.
        """
        now = self._clock()
        if force or self._last is None or now - self._last >= self._interval:
            self._last = now
            return True
        return False

    def seconds_until_due(self) -> float:
        """Return seconds until :meth:`due` succeeds; never negative."""
        if self._last is None:
            return 0.0
        return max(0.0, self._interval - (self._clock() - self._last))
