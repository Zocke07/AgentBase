"""The computer's sleep, as automations see it.

On 2026-10-13 the maintainer's Mac slept with the lid closed. Its brief
maintenance "dark wakes", a few seconds every quarter hour, were enough for
the scheduler to start the morning collection, which then crept through those
seconds for five hours; a run started before an idle sleep stalled the same
way. Two things follow from that:

* :class:`Wakefulness` tells a person's wake from a dark wake by how long the
  process has run since it was last suspended. The wall clock jumps across a
  sleep; a heartbeat sees the jump. Work waits until the computer has been
  awake for a couple of minutes, which no dark wake lasts.
* :class:`KeepAwake` holds the computer out of *idle* sleep while any run is
  going. Closing the lid still sleeps it, as it should.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import subprocess
import sys
import time
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = ["KeepAwake", "Wakefulness"]

logger = logging.getLogger("agentbase.power")

#: How often the heartbeat looks at the clock while the process runs.
HEARTBEAT_SECONDS: Final[float] = 5.0
#: A wall-clock jump this much longer than the heartbeat means a suspension.
SUSPENSION_GAP_SECONDS: Final[float] = 30.0
#: Awake this long without a suspension is a person's wake, not a dark wake.
SETTLE_SECONDS: Final[float] = 120.0

_CAFFEINATE: Final[str] = "/usr/bin/caffeinate"
#: Windows ``SetThreadExecutionState`` flags.
_ES_CONTINUOUS: Final[int] = 0x80000000
_ES_SYSTEM_REQUIRED: Final[int] = 0x00000001


class Wakefulness:
    """Whether the computer has been awake long enough to start work.

    The process starts settled: launching the app is a person at the
    computer. ``observe`` is cheap and may be called from anywhere; the
    heartbeat calls it while the process runs, so any gap longer than
    :data:`SUSPENSION_GAP_SECONDS` between two observations was a sleep.
    """

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.time,
        settle_seconds: float = SETTLE_SECONDS,
        gap_seconds: float = SUSPENSION_GAP_SECONDS,
    ) -> None:
        self._clock = clock
        self._settle = settle_seconds
        self._gap = gap_seconds
        self._last = clock()
        self._woke_at: float | None = None
        self._task: asyncio.Task[None] | None = None

    def observe(self) -> None:
        now = self._clock()
        if now - self._last > self._gap:
            if self._woke_at is None or now - self._woke_at >= self._settle:
                logger.info("the computer woke after %.0f seconds asleep", now - self._last)
            self._woke_at = now
        self._last = now

    def settled(self) -> bool:
        self.observe()
        return self._woke_at is None or self._clock() - self._woke_at >= self._settle

    def seconds_until_settled(self) -> float:
        if self.settled() or self._woke_at is None:
            return 0.0
        return self._settle - (self._clock() - self._woke_at)

    async def start(self) -> None:
        self._task = asyncio.create_task(self._beat(), name="wakefulness")

    async def aclose(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def _beat(self) -> None:
        while True:
            self.observe()
            await asyncio.sleep(HEARTBEAT_SECONDS)


class KeepAwake:
    """Keep the computer out of idle sleep while at least one run is going.

    macOS runs the system ``caffeinate -i`` tied to this process, so it ends
    with the sidecar even if the sidecar is killed; Windows sets the thread's
    execution state. Elsewhere it does nothing. A failure to hold the
    computer awake is logged and never stops a run.
    """

    def __init__(
        self,
        *,
        platform: str = sys.platform,
        spawn: Callable[[list[str]], subprocess.Popen[bytes]] | None = None,
        set_state: Callable[[int], object] | None = None,
    ) -> None:
        self._platform = platform
        self._spawn = spawn or _spawn
        self._set_state = set_state
        self._holders = 0
        self._process: subprocess.Popen[bytes] | None = None

    @property
    def holding(self) -> bool:
        return self._holders > 0

    def hold(self) -> None:
        self._holders += 1
        if self._holders == 1:
            self._acquire()

    def release(self) -> None:
        if self._holders == 0:
            return
        self._holders -= 1
        if self._holders == 0:
            self._drop()

    def close(self) -> None:
        if self._holders:
            self._holders = 0
            self._drop()

    def _acquire(self) -> None:
        try:
            if self._platform == "darwin":
                self._process = self._spawn([_CAFFEINATE, "-i", "-w", str(os.getpid())])
            elif self._platform == "win32":
                self._windows(_ES_CONTINUOUS | _ES_SYSTEM_REQUIRED)
        except (OSError, AttributeError) as exc:
            logger.warning("could not keep the computer awake during a run: %s", exc)

    def _drop(self) -> None:
        try:
            if self._process is not None:
                process, self._process = self._process, None
                process.terminate()
                with contextlib.suppress(subprocess.TimeoutExpired):
                    process.wait(timeout=2)
            elif self._platform == "win32":
                self._windows(_ES_CONTINUOUS)
        except (OSError, AttributeError) as exc:
            logger.warning("could not let the computer sleep again: %s", exc)

    def _windows(self, flags: int) -> None:
        if self._set_state is not None:
            self._set_state(flags)
            return
        if sys.platform == "win32":
            import ctypes

            ctypes.windll.kernel32.SetThreadExecutionState(flags)


def _spawn(command: list[str]) -> subprocess.Popen[bytes]:
    # Only the fixed system caffeinate with this process's pid; no shell.
    return subprocess.Popen(  # noqa: S603
        command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
