"""Smoke tests for the frozen PyInstaller sidecar.

This is the BUILD_SPEC §5 Phase 1 acceptance criterion expressed as a test:
the built binary serves, and closing its stdin leaves *zero* surviving
processes.

Why this needs testing at the binary level rather than in-process: with
``--onefile`` the bootloader unpacks to a temp directory and execs the real
interpreter as a child. Two processes exist. Anything that kills only the
bootloader — which is the only PID the Tauri shell knows — leaves the server
alive and holding the port. The in-process tests in ``test_main.py`` cannot
observe that, because in-process there is only ever one process.

Skipped when the binary has not been built, so `just test` stays fast and does
not silently depend on build order. Pass `--require-build-checks` — as
`just verify-build` does after a freeze — to turn that skip into a failure, so a
release cannot go out green on a binary nothing ever launched.
"""

from __future__ import annotations

import contextlib
import json
import os
import platform
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

REPO_ROOT = Path(__file__).resolve().parents[3]

#: Deliberately not 8787, so a running dev instance cannot make this pass or
#: fail for the wrong reason.
TEST_PORT = 8899

STARTUP_TIMEOUT_S = 30.0
SHUTDOWN_TIMEOUT_S = 20.0


def _target_triple(platform_name: str = sys.platform, machine: str | None = None) -> str:
    """Mirror the triple the justfile builds the sidecar under.

    Parameterized for the same reason as `agentspace.config.default_data_dir`:
    mypy narrows a literal `sys.platform` comparison to the host it runs on, so
    `warn_unreachable` would call the other branches dead code — and the macOS
    branch is one CI builds but no one here can execute.
    """
    if platform_name == "win32":
        return "x86_64-pc-windows-msvc"

    if machine is None:
        machine = platform.machine()
    normalized = "aarch64" if machine.lower() in {"arm64", "aarch64"} else "x86_64"

    if platform_name == "darwin":
        return f"{normalized}-apple-darwin"
    return f"{normalized}-unknown-linux-gnu"


def _sidecar_path() -> Path:
    suffix = ".exe" if sys.platform == "win32" else ""
    name = f"agentspace-sidecar-{_target_triple()}{suffix}"
    return REPO_ROOT / "apps" / "desktop" / "src-tauri" / "binaries" / name


SIDECAR = _sidecar_path()


@pytest.fixture(autouse=True)
def _needs_the_frozen_binary(build_prerequisite: Callable[[str | None], None]) -> None:
    """Skip without a build; fail if the caller asked for the check explicitly.

    `just verify-build` passes `--require-build-checks` after freezing, so a
    release cannot report a green tick for a binary these tests never launched.
    This module is the Phase 1 acceptance criterion expressed as a test, and it
    is the one thing that has to hold on every platform that ships.
    """
    build_prerequisite(
        None
        if SIDECAR.is_file()
        else f"sidecar not built ({SIDECAR.name}); run `just build-sidecar`"
    )


def _port_is_open(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


def _wait_for_port(port: int, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _port_is_open(port):
            return True
        time.sleep(0.2)
    return False


def _wait_for_port_release(port: int, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _port_is_open(port):
            return True
        time.sleep(0.2)
    return False


def _process_list_command(image_name: str, platform_name: str = sys.platform) -> list[str]:
    """The command that lists live processes matching ``image_name``."""
    if platform_name == "win32":
        system_root = os.environ.get("SYSTEMROOT", "C:/Windows")
        return [
            str(Path(system_root) / "System32" / "tasklist.exe"),
            "/FI",
            f"IMAGENAME eq {image_name}",
            "/NH",
            "/FO",
            "CSV",
        ]
    return ["/usr/bin/pgrep", "-af", image_name]


def _surviving_sidecar_processes() -> list[str]:
    """Every live process whose image is our sidecar binary."""
    completed = subprocess.run(  # noqa: S603
        _process_list_command(SIDECAR.name),
        capture_output=True,
        text=True,
        check=False,
    )
    return [
        line for line in completed.stdout.splitlines() if SIDECAR.name.lower() in line.lower()
    ]


def _require_ready(process: subprocess.Popen[str]) -> None:
    """Wait for the sidecar to bind, or fail with its own output attached."""
    if _wait_for_port(TEST_PORT, STARTUP_TIMEOUT_S):
        return

    process.kill()
    try:
        output = process.communicate(timeout=10)[0]
    except subprocess.TimeoutExpired:
        output = "<could not read child output>"

    pytest.fail(
        "\n".join(
            [
                f"sidecar never bound port {TEST_PORT} within {STARTUP_TIMEOUT_S}s.",
                f"exit code: {process.returncode}",
                "--- child output ---",
                output,
            ]
        )
    )


@pytest.fixture
def sidecar(tmp_path: Path) -> Iterator[subprocess.Popen[str]]:
    """Launch the frozen binary with a live stdin pipe, as Tauri does.

    The data directory is redirected into `tmp_path` so these tests exercise a
    first-launch database — schema creation included — instead of reusing, and
    growing, the developer's own `.dev/data`.
    """
    assert _wait_for_port_release(TEST_PORT, 5), (
        f"port {TEST_PORT} is already in use; a previous run may have leaked a sidecar process"
    )

    process = subprocess.Popen(  # noqa: S603
        [str(SIDECAR)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env={
            **os.environ,
            "AGENTSPACE_PORT": str(TEST_PORT),
            "AGENTSPACE_DATA_DIR": str(tmp_path),
        },
    )
    try:
        yield process
    finally:
        _terminate(process)


def _terminate(process: subprocess.Popen[str]) -> None:
    """Stop the sidecar the way the shell must: by closing stdin.

    Killing the process is deliberately the last resort rather than the first
    move. With ``--onefile`` the PID we hold is the bootloader's, and killing it
    leaves the real server running — worse, it keeps running until *our* end of
    the stdin pipe is released, because until then the child never sees EOF.
    That is the orphan this whole mechanism exists to prevent, and a teardown
    that reached for kill() first would leak a port between tests instead of
    exercising the real shutdown path.
    """
    if process.stdin is not None and not process.stdin.closed:
        with contextlib.suppress(OSError):
            process.stdin.close()

    if process.poll() is None:
        try:
            process.wait(timeout=SHUTDOWN_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)

    if process.stdout is not None and not process.stdout.closed:
        process.stdout.close()

    _wait_for_port_release(TEST_PORT, SHUTDOWN_TIMEOUT_S)


def test_frozen_sidecar_serves_health(sidecar: subprocess.Popen[str]) -> None:
    _require_ready(sidecar)

    with urllib.request.urlopen(f"http://127.0.0.1:{TEST_PORT}/health", timeout=5) as response:
        assert response.status == 200
        # No shell launched this one, so it carries no instance tag.
        assert json.loads(response.read()) == {"ok": True, "instance": None}


def test_closing_stdin_leaves_no_orphan_process(sidecar: subprocess.Popen[str]) -> None:
    """The Phase 1 acceptance criterion, verbatim: zero surviving processes."""
    _require_ready(sidecar)
    assert sidecar.stdin is not None

    sidecar.stdin.close()

    exit_code = sidecar.wait(timeout=SHUTDOWN_TIMEOUT_S)
    assert exit_code is not None

    assert _wait_for_port_release(TEST_PORT, SHUTDOWN_TIMEOUT_S), (
        "port still held after stdin closed — the real server was orphaned"
    )

    survivors = _surviving_sidecar_processes()
    assert survivors == [], f"orphaned sidecar processes remain: {survivors}"


def test_explicit_shutdown_command_stops_the_binary(
    sidecar: subprocess.Popen[str],
) -> None:
    """The clean-quit path: the shell writes `shutdown` before closing."""
    _require_ready(sidecar)
    assert sidecar.stdin is not None

    sidecar.stdin.write("shutdown\n")
    sidecar.stdin.flush()

    exit_code = sidecar.wait(timeout=SHUTDOWN_TIMEOUT_S)
    assert exit_code is not None
    assert _wait_for_port_release(TEST_PORT, SHUTDOWN_TIMEOUT_S)
    assert _surviving_sidecar_processes() == []


def test_sidecar_filename_carries_the_target_triple() -> None:
    """Tauri resolves `externalBin` by appending the triple; a plain name fails."""
    assert _target_triple() in SIDECAR.name
    if sys.platform == "win32":
        assert SIDECAR.name.endswith("-x86_64-pc-windows-msvc.exe")


@pytest.mark.parametrize(
    ("platform_name", "machine", "expected"),
    [
        ("win32", "AMD64", "x86_64-pc-windows-msvc"),
        ("darwin", "arm64", "aarch64-apple-darwin"),
        ("darwin", "x86_64", "x86_64-apple-darwin"),
        ("linux", "x86_64", "x86_64-unknown-linux-gnu"),
        ("linux", "aarch64", "aarch64-unknown-linux-gnu"),
    ],
)
def test_target_triple_matches_the_justfile(
    platform_name: str, machine: str, expected: str
) -> None:
    """Must agree with the justfile, or Tauri will not find the sidecar.

    The macOS rows are the point of parameterizing: CI builds them from day one
    (BUILD_SPEC §1 constraint 7) and nothing here can execute that path.
    """
    assert _target_triple(platform_name, machine) == expected


def test_process_list_command_targets_the_right_image() -> None:
    windows = _process_list_command("thing.exe", "win32")
    assert windows[0].lower().endswith("tasklist.exe")
    assert "IMAGENAME eq thing.exe" in windows

    unix = _process_list_command("thing", "linux")
    assert unix[-1] == "thing"


# --- Phase 2: the event spine inside the frozen binary ----------------------


def _post(path: str, timeout: float = 10) -> dict[str, object]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{TEST_PORT}{path}", method="POST", data=b""
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        parsed: dict[str, object] = json.loads(response.read())
        return parsed


def test_frozen_sidecar_creates_its_database(
    sidecar: subprocess.Popen[str], tmp_path: Path
) -> None:
    """`--onefile` collects bytecode automatically but not data files.

    `schema.sql` reaches the binary only because the justfile passes
    `--add-data`. Without it the sidecar starts, answers `/health`, and then
    fails the moment anything touches the database — which is exactly the shape
    of the Phase 1 bug that looked healthy and was not. Asserting on a real
    database file is the cheapest way to keep that from recurring.
    """
    _require_ready(sidecar)

    _post("/debug/fake_run?step_ms=0")

    assert (tmp_path / "agentspace.sqlite3").is_file(), (
        "the frozen sidecar did not create its database; "
        "schema.sql is most likely missing from the bundle"
    )


def test_frozen_sidecar_streams_a_debug_run(sidecar: subprocess.Popen[str]) -> None:
    """End to end through the real binary: migrate, append, and stream SSE."""
    _require_ready(sidecar)

    run = _post("/debug/fake_run?step_ms=0")

    with urllib.request.urlopen(
        f"http://127.0.0.1:{TEST_PORT}/runs/{run['id']}/events", timeout=30
    ) as response:
        body = response.read().decode("utf-8")

    seqs = [
        json.loads(line.removeprefix("data: "))["seq"]
        for line in body.splitlines()
        if line.startswith("data: ")
    ]

    assert seqs == list(range(1, 21))
