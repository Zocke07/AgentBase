"""Exercise the downloaded shape: a ditto archive, with executable app binaries.

upload-artifact strips file modes from a raw .app. The release therefore ships
a zip, and these checks unpack that zip before inspecting or running anything.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import plistlib
import shutil
import socket
import stat
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable

REPO_ROOT = Path(__file__).resolve().parents[3]
TAURI_ROOT = REPO_ROOT / "apps" / "desktop" / "src-tauri"
BUNDLE_DIR = TAURI_ROOT / "target" / "release" / "bundle" / "macos"
VERSION = json.loads((TAURI_ROOT / "tauri.conf.json").read_text(encoding="utf-8"))["version"]
ARCH = "aarch64" if platform.machine().lower() in {"arm64", "aarch64"} else "x86_64"
TRIPLE = f"{ARCH}-apple-darwin"
ARCHIVE = BUNDLE_DIR / f"AgentSpace_{VERSION}_{TRIPLE}.app.zip"
SIDECAR = TAURI_ROOT / "binaries" / f"agentspace-sidecar-{TRIPLE}"
TEST_PORT = 8898

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="macOS app archive")


@pytest.fixture
def extracted_app(tmp_path: Path, build_prerequisite: Callable[[str | None], None]) -> Path:
    for required in (ARCHIVE, SIDECAR, BUNDLE_DIR / "AgentSpace.app"):
        build_prerequisite(
            None
            if required.exists()
            else f"missing {required}; run `just build-installer` then `just package-macos`"
        )
    extracted = tmp_path / "unpacked"
    subprocess.run(  # noqa: S603
        ["/usr/bin/ditto", "-x", "-k", str(ARCHIVE), str(extracted)], check=True
    )
    app = extracted / "AgentSpace.app"
    assert app.is_dir(), "the archive lost its AgentSpace.app root directory"
    return app


def _sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _sha256_without_signature(source: Path, destination: Path) -> str:
    """Compare Mach-O content while allowing Tauri to replace its signature."""
    shutil.copy2(source, destination)
    subprocess.run(  # noqa: S603
        ["/usr/bin/codesign", "--remove-signature", str(destination)], check=True
    )
    return _sha256(destination)


def test_archive_preserves_the_current_app_and_executable_modes(
    extracted_app: Path, tmp_path: Path
) -> None:
    with (extracted_app / "Contents" / "Info.plist").open("rb") as handle:
        info = plistlib.load(handle)
    assert info["CFBundleShortVersionString"] == VERSION
    assert info["CFBundleIdentifier"] == "dev.agentspace.desktop"

    executables = {
        str(info["CFBundleExecutable"]): BUNDLE_DIR
        / "AgentSpace.app"
        / "Contents"
        / "MacOS"
        / str(info["CFBundleExecutable"]),
        "agentspace-sidecar": SIDECAR,
    }
    with zipfile.ZipFile(ARCHIVE) as archive:
        for name, source in executables.items():
            entry = archive.getinfo(f"AgentSpace.app/Contents/MacOS/{name}")
            assert stat.S_IMODE(entry.external_attr >> 16) & stat.S_IXUSR, (
                f"{name} has no executable mode in the archive"
            )
            extracted = extracted_app / "Contents" / "MacOS" / name
            assert os.access(extracted, os.X_OK), f"{name} is not executable after extraction"
            assert _sha256_without_signature(
                extracted, tmp_path / f"{name}-archive"
            ) == _sha256_without_signature(source, tmp_path / f"{name}-source"), (
                f"the archive carries stale {name}"
            )


def test_extracted_app_has_a_valid_complete_signature(extracted_app: Path) -> None:
    """A linker-signed executable is not a valid signature for the app bundle.

    Gatekeeper reports that incomplete shape as a damaged application after a
    browser adds quarantine. Tauri must ad-hoc sign the complete bundle before
    it is archived.
    """
    verified = subprocess.run(  # noqa: S603
        [
            "/usr/bin/codesign",
            "--verify",
            "--deep",
            "--strict",
            "--verbose=4",
            str(extracted_app),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    output = "\n".join(part for part in (verified.stdout, verified.stderr) if part)
    assert verified.returncode == 0, (
        "the archived app has an invalid or incomplete macOS signature:\n" + output
    )


def _wait_for_port(open_: bool, timeout: float = 20) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket() as sock:
            sock.settimeout(0.5)
            if (sock.connect_ex(("127.0.0.1", TEST_PORT)) == 0) == open_:
                return True
        time.sleep(0.1)
    return False


def test_extracted_sidecar_serves_and_stops_without_python(
    extracted_app: Path, tmp_path: Path
) -> None:
    """Launch the archive's bytes, migrate a fresh DB, then close the shell's pipe."""
    assert _wait_for_port(False, timeout=1), f"port {TEST_PORT} is already occupied"
    data_dir = tmp_path / "data"
    environment = {k: v for k, v in os.environ.items() if not k.upper().startswith("PYTHON")}
    environment.update(
        PATH=str(tmp_path / "no-interpreters"),
        AGENTSPACE_PORT=str(TEST_PORT),
        AGENTSPACE_DATA_DIR=str(data_dir),
    )
    # The absent PATH directory prevents an OS-provided Python satisfying the test.
    binary = extracted_app / "Contents" / "MacOS" / "agentspace-sidecar"
    with (tmp_path / "sidecar.log").open("w+") as log:
        process = subprocess.Popen(  # noqa: S603
            [str(binary)],
            stdin=subprocess.PIPE,
            stdout=log,
            stderr=subprocess.STDOUT,
            env=environment,
        )
        try:
            ready = _wait_for_port(True, timeout=30)
            log.seek(0)
            assert ready, f"extracted sidecar did not start:\n{log.read()}"
            with urllib.request.urlopen(
                f"http://127.0.0.1:{TEST_PORT}/health", timeout=5
            ) as response:
                assert json.loads(response.read()) == {"ok": True, "instance": None}
            with urllib.request.urlopen(
                f"http://127.0.0.1:{TEST_PORT}/spaces", timeout=5
            ) as response:
                assert response.status == 200
            assert (data_dir / "agentspace.sqlite3").is_file()
            assert process.stdin is not None
            process.stdin.close()
            assert process.wait(timeout=20) == 0
            assert _wait_for_port(False), "the extracted sidecar orphaned its server"
            survivors = subprocess.run(  # noqa: S603
                ["/usr/bin/pgrep", "-f", str(binary)],
                capture_output=True,
                text=True,
                check=False,
            )
            assert survivors.returncode == 1, f"surviving processes: {survivors.stdout}"
        finally:
            if process.stdin is not None and not process.stdin.closed:
                process.stdin.close()
            if process.poll() is None:
                try:
                    process.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
