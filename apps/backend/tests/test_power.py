"""The computer's sleep as automations see it (2026-10-13 dark-wake crawl)."""

from __future__ import annotations

import os
import subprocess
from typing import Any

import pytest

from agentbase.orchestrator.power import KeepAwake, Wakefulness


class _Clock:
    def __init__(self) -> None:
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now


def test_the_app_starts_settled_and_a_sleep_makes_it_wait_two_minutes() -> None:
    clock = _Clock()
    awake = Wakefulness(clock=clock)
    assert awake.settled()

    # The lid closed for an hour: the next look sees the wall clock jump.
    clock.now += 3600
    assert not awake.settled()
    assert awake.seconds_until_settled() == pytest.approx(120)

    # Awake and looking every five seconds for two minutes: a person's wake.
    for _ in range(24):
        clock.now += 5
        awake.observe()
    assert awake.settled()


def test_a_dark_wake_of_a_few_seconds_never_settles() -> None:
    clock = _Clock()
    awake = Wakefulness(clock=clock)
    for _ in range(10):
        clock.now += 900  # a quarter hour asleep
        awake.observe()
        clock.now += 5  # five seconds of maintenance wake
        assert not awake.settled()


class _Process:
    def __init__(self) -> None:
        self.terminated = False

    def terminate(self) -> None:
        self.terminated = True

    def wait(self, timeout: float) -> int:
        return 0


def test_runs_hold_the_mac_awake_with_caffeinate_until_the_last_one_ends() -> None:
    spawned: list[list[str]] = []
    processes: list[_Process] = []

    def spawn(command: list[str]) -> Any:
        spawned.append(command)
        processes.append(_Process())
        return processes[-1]

    awake = KeepAwake(platform="darwin", spawn=spawn)
    awake.hold()
    awake.hold()
    assert spawned == [["/usr/bin/caffeinate", "-i", "-w", str(os.getpid())]]

    awake.release()
    assert [process.terminated for process in processes] == [False]  # one run still going
    awake.release()
    assert [process.terminated for process in processes] == [True]
    awake.release()  # one too many changes nothing
    assert not awake.holding


def test_windows_sets_and_clears_the_thread_execution_state() -> None:
    states: list[int] = []
    awake = KeepAwake(platform="win32", set_state=states.append)
    awake.hold()
    awake.close()
    assert states == [0x80000001, 0x80000000]


def test_a_failure_to_hold_the_computer_awake_never_stops_a_run(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def refuse(_command: list[str]) -> subprocess.Popen[bytes]:
        msg = "no caffeinate here"
        raise OSError(msg)

    awake = KeepAwake(platform="darwin", spawn=refuse)
    awake.hold()
    awake.release()
    assert "could not keep the computer awake" in caplog.text
    KeepAwake(platform="linux").hold()  # elsewhere it does nothing
