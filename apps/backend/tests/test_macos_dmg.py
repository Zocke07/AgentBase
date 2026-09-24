"""Exercise the downloaded shape: a disk image holding the app and an Applications link.

upload-artifact strips file modes from a raw .app, and a bare zip left users
running the app from Downloads, where Gatekeeper translocates it on every
launch and Spotlight never lists it. The release therefore ships a `.dmg`, and
these checks mount that image and copy the app out of it, as dragging it to
Applications does, before inspecting or running anything.
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
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

REPO_ROOT = Path(__file__).resolve().parents[3]
TAURI_ROOT = REPO_ROOT / "apps" / "desktop" / "src-tauri"
BUNDLE_DIR = TAURI_ROOT / "target" / "release" / "bundle" / "macos"
VERSION = json.loads((TAURI_ROOT / "tauri.conf.json").read_text(encoding="utf-8"))["version"]
ARCH = "aarch64" if platform.machine().lower() in {"arm64", "aarch64"} else "x86_64"
TRIPLE = f"{ARCH}-apple-darwin"
#: Tauri names the image after the product, version and architecture, no triple.
DISK_IMAGE = (
    TAURI_ROOT / "target" / "release" / "bundle" / "dmg" / f"AgentBase_{VERSION}_{ARCH}.dmg"
)
SIDECAR = TAURI_ROOT / "binaries" / f"agentbase-sidecar-{TRIPLE}"
TEST_PORT = 8898

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="macOS disk image")


@pytest.fixture
def mounted_image(
    tmp_path: Path, build_prerequisite: Callable[[str | None], None]
) -> Iterator[Path]:
    """The image's contents, mounted read-only and detached afterwards."""
    for required in (DISK_IMAGE, SIDECAR, BUNDLE_DIR / "AgentBase.app"):
        build_prerequisite(
            None if required.exists() else f"missing {required}; run `just build-installer`"
        )
    mount_point = tmp_path / "volume"
    subprocess.run(  # noqa: S603
        [
            "/usr/bin/hdiutil",
            "attach",
            str(DISK_IMAGE),
            "-readonly",
            "-nobrowse",
            "-noautoopen",
            "-mountpoint",
            str(mount_point),
        ],
        check=True,
        capture_output=True,
    )
    try:
        yield mount_point
    finally:
        subprocess.run(  # noqa: S603
            ["/usr/bin/hdiutil", "detach", str(mount_point), "-force"],
            check=False,
            capture_output=True,
        )


@pytest.fixture
def extracted_app(mounted_image: Path, tmp_path: Path) -> Path:
    """The app as a drag to Applications leaves it: copied out with its modes."""
    app = mounted_image / "AgentBase.app"
    assert app.is_dir(), f"the image holds {sorted(p.name for p in mounted_image.iterdir())}"
    copied = tmp_path / "Applications" / "AgentBase.app"
    subprocess.run(  # noqa: S603
        ["/usr/bin/ditto", str(app), str(copied)], check=True
    )
    return copied


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


def test_the_image_offers_the_app_beside_an_applications_link(mounted_image: Path) -> None:
    """The install step is a drag: the window shows the app and where it goes."""
    entries = {
        entry.name for entry in mounted_image.iterdir() if not entry.name.startswith(".")
    }
    assert entries == {"AgentBase.app", "Applications"}, entries
    applications = mounted_image / "Applications"
    assert applications.is_symlink(), "Applications must be a link, not a copied folder"
    assert applications.readlink() == Path("/Applications")


def test_image_preserves_the_current_app_and_executable_modes(
    mounted_image: Path, extracted_app: Path, tmp_path: Path
) -> None:
    with (extracted_app / "Contents" / "Info.plist").open("rb") as handle:
        info = plistlib.load(handle)
    assert info["CFBundleShortVersionString"] == VERSION
    assert info["CFBundleIdentifier"] == "dev.agentbase.desktop"

    executables = {
        str(info["CFBundleExecutable"]): BUNDLE_DIR
        / "AgentBase.app"
        / "Contents"
        / "MacOS"
        / str(info["CFBundleExecutable"]),
        "agentbase-sidecar": SIDECAR,
    }
    for name, source in executables.items():
        on_image = mounted_image / "AgentBase.app" / "Contents" / "MacOS" / name
        assert stat.S_IMODE(on_image.stat().st_mode) & stat.S_IXUSR, (
            f"{name} has no executable mode on the image"
        )
        extracted = extracted_app / "Contents" / "MacOS" / name
        assert os.access(extracted, os.X_OK), f"{name} is not executable after copying"
        assert _sha256_without_signature(
            extracted, tmp_path / f"{name}-image"
        ) == _sha256_without_signature(source, tmp_path / f"{name}-source"), (
            f"the image carries stale {name}"
        )


def test_extracted_app_has_a_valid_complete_signature(extracted_app: Path) -> None:
    """A linker-signed executable is not a valid signature for the app bundle.

    Gatekeeper reports that incomplete shape as a damaged application after a
    browser adds quarantine. Tauri must ad-hoc sign the complete bundle before
    it goes on the image.
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
        "the app on the image has an invalid or incomplete macOS signature:\n" + output
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
    """Launch the image's bytes, migrate a fresh DB, then close the shell's pipe."""
    assert _wait_for_port(False, timeout=1), f"port {TEST_PORT} is already occupied"
    data_dir = tmp_path / "data"
    environment = {k: v for k, v in os.environ.items() if not k.upper().startswith("PYTHON")}
    environment.update(
        PATH=str(tmp_path / "no-interpreters"),
        AGENTBASE_PORT=str(TEST_PORT),
        AGENTBASE_DATA_DIR=str(data_dir),
    )
    # The absent PATH directory prevents an OS-provided Python satisfying the test.
    binary = extracted_app / "Contents" / "MacOS" / "agentbase-sidecar"
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
            assert (data_dir / "agentbase.sqlite3").is_file()
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
