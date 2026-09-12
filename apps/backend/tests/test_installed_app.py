"""The installed app, launched on a machine that has no Python.

This is BUILD_SPEC §5 Phase 9's acceptance criterion, adapted because its literal
form cannot be met: "a green CI run produces a downloadable installer that runs on
a second Windows machine with no Python installed". There is one Windows machine
here and there will not be a second — see CLAUDE.md's "The machine reality".

The property the criterion is really protecting is narrow and testable without a
second machine: **the frozen sidecar must not depend on the development machine's
Python installation.** `--onefile` embeds an interpreter, and the failure mode is a
binary that works everywhere a Python install happens to sit and nowhere else. The
symptom on a user's machine is an app that starts and immediately dies.

So this module installs the produced installer and launches the *installed*
sidecar with Python removed from its environment. On a GitHub `windows-latest`
runner that is a genuinely different machine — a clean VM with no `.venv`, no
`node_modules`, no repository and no toolchain — which is weaker than a friend's
laptop in one respect and stronger in another: it runs on every release rather
than once.

**It is not part of `just test`.** It installs software, which no test run should
do behind a developer's back, so it is skipped unless `--install-smoke` is passed
and `just verify-installed` is the recipe that passes it.

Two things this deliberately does not claim. It does not launch the GUI: a Tauri
window on a headless runner is unreliable, and the Rust shell is not the half that
could need Python. And "no Python installed" is approximated by a scrubbed
environment rather than by an uninstalled Python, which
`test_the_scrubbed_environment_really_has_no_python` exists to keep honest — a
scrub that silently failed would make everything below it vacuous.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

#: Where the per-user NSIS installer puts the app. Tauri's `currentUser` install
#: mode uses `%LOCALAPPDATA%\<productName>`, which Phase 2 confirmed empirically
#: and which is why the data directory is deliberately *not* derived from
#: `APP_NAME` — it would have resolved inside the installation.
INSTALL_DIR = Path(os.environ.get("LOCALAPPDATA", "C:/")) / "AgentSpace"

#: Deliberately none of 8787 (dev), 8899 (`test_sidecar_binary`), so a running
#: instance of either cannot make this pass or fail for the wrong reason.
TEST_PORT = 8901

STARTUP_TIMEOUT_S = 40.0
SHUTDOWN_TIMEOUT_S = 20.0

pytestmark = pytest.mark.skipif(
    sys.platform != "win32", reason="the NSIS installer is a Windows artefact"
)


def _installer() -> Path | None:
    """The installer to exercise.

    `AGENTSPACE_INSTALLER_DIR` is what CI sets, pointing at the artefact it
    downloaded from the build job — the actual bytes a user would get, rather than
    a local rebuild of them. Falling back to the bundle directory keeps the recipe
    usable straight after `just build-installer`.
    """
    configured = os.environ.get("AGENTSPACE_INSTALLER_DIR")
    directory = (
        Path(configured)
        if configured
        else REPO_ROOT / "apps/desktop/src-tauri/target/release/bundle/nsis"
    )
    if not directory.is_dir():
        return None
    found = sorted(directory.glob("*-setup.exe"))
    return found[0] if found else None


def _skip_unless_requested(request: pytest.FixtureRequest) -> None:
    if not request.config.getoption("--install-smoke"):
        pytest.skip("needs --install-smoke (see `just verify-installed`)")


@pytest.fixture(autouse=True, scope="module")
def _requested(request: pytest.FixtureRequest) -> None:
    """Never run unless asked: this module installs software on the host.

    Module-scoped, and that scope is load-bearing. The first version was
    function-scoped, and pytest instantiates higher-scoped fixtures first — so the
    module-scoped `installed` fixture below ran *before* this skip ever executed,
    on every plain `just test`. Locally that silently reinstalled the app, because
    an installer was sitting in the bundle directory; on the CI runner it failed
    loudly, because there was none. A check that gates a side effect has to run
    before the side effect, and with fixtures that means matching or exceeding its
    scope.
    """
    _skip_unless_requested(request)


def _python_free_environment() -> dict[str, str]:
    """A child environment with no Python on `PATH` and no `PYTHON*` variables.

    Built from nothing rather than filtered from ours, for the same reason
    `run_shell` builds its child environment from an allowlist: the interesting
    variable is always the one nobody thought to remove.

    What is kept is what every Windows machine has and the process cannot start
    without. The two system directories on `PATH`, because nothing loads without
    them. And `TEMP`/`TMP`, because a `--onefile` binary extracts itself there
    before running a line of Python — the first version of this scrub dropped them
    and the installed sidecar died with `[PYI-32164:ERROR] Could not create
    temporary directory!`, which is not the dependency this test is hunting. A
    machine with no Python still has a temp directory; `run_shell`'s allowlist
    keeps these two for the identical reason.
    """
    system_root = os.environ.get("SYSTEMROOT", r"C:\Windows")
    temp = os.environ.get("TEMP") or os.environ.get("TMP") or str(Path(system_root) / "Temp")
    return {
        "SYSTEMROOT": system_root,
        "SystemRoot": system_root,
        "PATH": os.pathsep.join([str(Path(system_root) / "System32"), system_root]),
        "TEMP": temp,
        "TMP": temp,
        "AGENTSPACE_PORT": str(TEST_PORT),
        "AGENTSPACE_DATA_DIR": "",  # replaced per-test with a temporary directory
    }


def _port_is_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _wait_for(port: int, *, open_: bool, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _port_is_open(port) is open_:
            return True
        time.sleep(0.25)
    return False


def _surviving_processes() -> list[str]:
    completed = subprocess.run(  # noqa: S603
        [
            str(Path(os.environ.get("SYSTEMROOT", "C:/Windows")) / "System32" / "tasklist.exe"),
            "/FI",
            "IMAGENAME eq agentspace-sidecar.exe",
            "/NH",
            "/FO",
            "CSV",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return [
        line for line in completed.stdout.splitlines() if "agentspace-sidecar" in line.lower()
    ]


@pytest.fixture(scope="module")
def installed(request: pytest.FixtureRequest) -> Path:
    """Install the produced installer, and return the installed sidecar.

    Module-scoped: installing once and asserting several things about the result
    is the point, and `/S` twice would only prove the installer is idempotent,
    which Phase 1 already covers.

    It checks the option itself rather than trusting `_requested` to have run
    first. The fixture that performs a side effect is the one that must refuse
    to, whatever the instantiation order turns out to be — relying on a separate
    autouse fixture is exactly what installed the app behind `just test`'s back.
    Once past that check, a missing installer is a failure rather than a skip:
    the check was asked for explicitly, and a skip would be a release verified by
    nothing.
    """
    _skip_unless_requested(request)

    installer = _installer()
    if installer is None:
        pytest.fail(
            "--install-smoke was given but there is no *-setup.exe to install. "
            "Run `just build-installer`, or set AGENTSPACE_INSTALLER_DIR."
        )

    completed = subprocess.run([str(installer), "/S"], check=False)  # noqa: S603
    assert completed.returncode == 0, (
        f"{installer.name} exited {completed.returncode}; a silent per-user install should succeed"
    )

    sidecar = INSTALL_DIR / "agentspace-sidecar.exe"
    assert sidecar.is_file(), (
        f"{sidecar} is missing after installing {installer.name} — the installer "
        f"ran but did not place the sidecar where a per-user install puts it"
    )
    return sidecar


def test_the_scrubbed_environment_really_has_no_python() -> None:
    """Keeps every test below it from being vacuous.

    If the scrub silently failed, the sidecar would run *because* a Python
    installation was still reachable, and this module would report success while
    proving nothing at all. So the absence is asserted directly, before anything
    is launched.

    `py.exe` is not checked: the Python launcher installs into the Windows
    directory itself on an all-users install, so removing it would mean removing
    `System32` and no process could start. It is irrelevant here because a frozen
    binary embeds its interpreter and never shells out to a launcher — what would
    break the app is an interpreter it expected to *find*, which is what `PATH`
    and `PYTHON*` control.
    """
    environment = _python_free_environment()

    for interpreter in ("python", "python3", "pythonw"):
        found = shutil.which(interpreter, path=environment["PATH"])
        assert found is None, (
            f"{interpreter} is still reachable at {found}; the scrub did not work"
        )

    leaked = sorted(name for name in environment if name.upper().startswith("PYTHON"))
    assert leaked == [], f"Python variables leaked into the child environment: {leaked}"

    # And the scrub has to be a real change, or the host simply had no Python and
    # the test proves nothing about scrubbing.
    assert shutil.which("python") is not None or shutil.which("python3") is not None, (
        "this host has no Python on PATH at all, so the scrub is untested here; "
        "run this where a Python installation exists"
    )


def test_the_installed_sidecar_serves_with_no_python_available(
    installed: Path, tmp_path: Path
) -> None:
    """The criterion, as closely as one machine can state it.

    A `--onefile` binary that quietly relies on the developer's Python fails here
    and nowhere else in this suite.
    """
    assert _wait_for(TEST_PORT, open_=False, timeout=5), (
        f"port {TEST_PORT} is already in use before starting"
    )

    environment = _python_free_environment()
    environment["AGENTSPACE_DATA_DIR"] = str(tmp_path / "data")

    process = subprocess.Popen(  # noqa: S603
        [str(installed)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=environment,
    )
    try:
        if not _wait_for(TEST_PORT, open_=True, timeout=STARTUP_TIMEOUT_S):
            process.kill()
            output = process.communicate(timeout=10)[0]
            pytest.fail(
                "\n".join(
                    [
                        f"the installed sidecar never bound {TEST_PORT} with no Python "
                        f"on PATH — which is the failure this test exists to catch.",
                        f"exit code: {process.returncode}",
                        "--- output ---",
                        output or "<none>",
                    ]
                )
            )

        with urllib.request.urlopen(
            f"http://127.0.0.1:{TEST_PORT}/health", timeout=10
        ) as response:
            assert response.status == 200
            assert json.loads(response.read()) == {"ok": True, "instance": None}

        # The database too: `--onefile` collects bytecode automatically and data
        # files only because the justfile passes `--add-data`, so a migration
        # missing from the bundle presents as an app that answers /health and then
        # dies on first use. Reaching an endpoint that touches SQLite is what
        # separates "the binary starts" from "the binary works".
        request = urllib.request.Request(
            f"http://127.0.0.1:{TEST_PORT}/debug/fake_run?step_ms=0", method="POST", data=b""
        )
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            run = json.loads(response.read())
        assert run["id"]
        assert (tmp_path / "data" / "agentspace.sqlite3").is_file(), (
            "the installed sidecar did not create its database; the bundled "
            "migration SQL is most likely missing from the installed binary"
        )
    finally:
        _stop(process)


def test_closing_stdin_leaves_no_orphan_process(installed: Path, tmp_path: Path) -> None:
    """Phase 1's criterion, on the installed artefact, in a scrubbed environment.

    With `--onefile` the PID a parent holds is the bootloader's, not the server's,
    so this is the one guarantee that cannot be inferred from the process exiting.
    """
    environment = _python_free_environment()
    environment["AGENTSPACE_DATA_DIR"] = str(tmp_path / "data")

    process = subprocess.Popen(  # noqa: S603
        [str(installed)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=environment,
    )
    try:
        assert _wait_for(TEST_PORT, open_=True, timeout=STARTUP_TIMEOUT_S), "never bound"
        assert process.stdin is not None

        process.stdin.close()

        assert process.wait(timeout=SHUTDOWN_TIMEOUT_S) is not None
        assert _wait_for(TEST_PORT, open_=False, timeout=SHUTDOWN_TIMEOUT_S), (
            "the port is still held after stdin closed — the real server was orphaned"
        )
        assert _surviving_processes() == [], (
            f"orphaned processes remain: {_surviving_processes()}"
        )
    finally:
        _stop(process)


def _stop(process: subprocess.Popen[str]) -> None:
    """Close stdin and wait, killing only as a last resort (see Phase 1)."""
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

    _wait_for(TEST_PORT, open_=False, timeout=SHUTDOWN_TIMEOUT_S)
