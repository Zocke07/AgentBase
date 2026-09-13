"""Verify the sidecar *inside* the produced installer is the freshly built one.

The NSIS installer can reuse a stale cached sidecar and the build log says it
succeeded either way, so this unpacks the installer and compares SHA-256s.
Skipped unless the installer, the sidecar and 7-Zip exist; `--require-build-checks`
makes a missing one a failure on the release path.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable

REPO_ROOT = Path(__file__).resolve().parents[3]
TAURI_ROOT = REPO_ROOT / "apps" / "desktop" / "src-tauri"
SIDECAR_DIR = TAURI_ROOT / "binaries"
BUNDLE_DIR = TAURI_ROOT / "target" / "release" / "bundle"


def _sidecar_source() -> Path | None:
    """The freshly built sidecar, whatever the host triple is."""
    matches = sorted(SIDECAR_DIR.glob("agentspace-sidecar-*"))
    return matches[0] if matches else None


def _installer() -> Path | None:
    matches = sorted((BUNDLE_DIR / "nsis").glob("*-setup.exe"))
    return matches[0] if matches else None


def bundled_name(source_name: str) -> str:
    """The name the sidecar has *inside* the bundle.

    Tauri's `externalBin` contract is asymmetric and this is the half that is
    easy to miss: the file on disk must carry the target triple for Tauri to
    find it, but Tauri strips that triple when it stages and installs the
    binary. So `agentspace-sidecar-x86_64-pc-windows-msvc.exe` is what gets
    built, and `agentspace-sidecar.exe` is what ships. Looking for the built
    name inside the installer finds nothing and looks exactly like a bundling
    failure.
    """
    stem, _, extension = source_name.partition(".")
    base = stem.split("-x86_64-")[0].split("-aarch64-")[0]
    return f"{base}.{extension}" if extension else base


def _seven_zip() -> Path | None:
    for candidate in (
        Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / "7-Zip" / "7z.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)"))
        / "7-Zip"
        / "7z.exe",
    ):
        if candidate.is_file():
            return candidate
    found = shutil.which("7z")
    return Path(found) if found else None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


SIDECAR = _sidecar_source()
INSTALLER = _installer()
SEVEN_ZIP = _seven_zip()

#: The platform skip stays an ordinary skip even under `--require-build-checks`.
#: The macOS CI job builds a `.app` and there is no NSIS installer there to look
#: inside; demanding one would fail the job for being macOS.
pytestmark = pytest.mark.skipif(
    sys.platform != "win32", reason="NSIS installer is a Windows artifact"
)


def _missing_prerequisite() -> str | None:
    """What stops these tests reading the installer, if anything does.

    Returned as a sentence rather than a bool so that the release path can say
    which of the three prerequisites was absent. 7-Zip belongs in this list and
    not in the bodies below: "no 7-Zip" and "no installer" are both reasons the
    staleness check did not happen, and a release must be able to tell them
    apart from the check having passed.
    """
    if SIDECAR is None:
        return f"no built sidecar in {SIDECAR_DIR}; run `just build-sidecar`"
    if INSTALLER is None:
        return f"no installer in {BUNDLE_DIR / 'nsis'}; run `just build-installer`"
    if SEVEN_ZIP is None:
        return "7-Zip is not installed, so the installer cannot be unpacked"
    return None


@pytest.fixture(autouse=True)
def _needs_a_build(build_prerequisite: Callable[[str | None], None]) -> None:
    """Skip without a build; fail if the caller asked for the check explicitly."""
    build_prerequisite(_missing_prerequisite())


def test_installer_carries_the_freshly_built_sidecar(tmp_path: Path) -> None:
    """The whole point: no stale cached binary snuck into the bundle."""
    assert SIDECAR is not None
    assert INSTALLER is not None
    wanted = bundled_name(SIDECAR.name)
    extracted = tmp_path / "unpacked"
    completed = subprocess.run(  # noqa: S603
        [str(SEVEN_ZIP), "x", str(INSTALLER), f"-o{extracted}", "-y", wanted, "-r"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, (
        f"could not unpack the installer:\n{completed.stdout}\n{completed.stderr}"
    )

    found = sorted(extracted.rglob(wanted))
    assert found, (
        f"{wanted} is not inside {INSTALLER.name}: Tauri did not bundle the "
        f"sidecar, which usually means the file in binaries/ does not carry the "
        f"target triple and so was never resolved"
    )

    expected = _sha256(SIDECAR)
    for candidate in found:
        assert _sha256(candidate) == expected, (
            f"{candidate.name} inside the installer does not match the freshly "
            f"built sidecar: a stale cached binary was bundled. Delete "
            f"{BUNDLE_DIR.parent} and rebuild."
        )
        assert candidate.stat().st_size == SIDECAR.stat().st_size


def test_installer_embeds_the_webview2_bootstrapper() -> None:
    """§5 Phase 1: WebView2 must ship inside the installer, not be downloaded.

    Windows 11 generally has the runtime already; Windows 10 machines may not,
    and a first install that silently fails on an old machine is the exact
    outcome this guards against.
    """
    assert INSTALLER is not None
    completed = subprocess.run(  # noqa: S603
        [str(SEVEN_ZIP), "l", str(INSTALLER)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0

    assert "MicrosoftEdgeWebview2Setup.exe" in completed.stdout, (
        "the WebView2 bootstrapper is not embedded: check that "
        "bundle.windows.webviewInstallMode.type is 'embedBootstrapper'"
    )


def test_staged_sidecar_matches_the_build(
    build_prerequisite: Callable[[str | None], None],
) -> None:
    """Tauri copies externalBin into target/release/; that copy can go stale too."""
    assert SIDECAR is not None
    staged = TAURI_ROOT / "target" / "release" / bundled_name(SIDECAR.name)
    build_prerequisite(None if staged.is_file() else f"no staged copy at {staged}")

    assert _sha256(staged) == _sha256(SIDECAR), (
        "the sidecar staged under target/release/ is stale relative to "
        "binaries/: Tauri will bundle the stale one"
    )


def test_bundled_name_strips_the_target_triple() -> None:
    assert bundled_name("agentspace-sidecar-x86_64-pc-windows-msvc.exe") == (
        "agentspace-sidecar.exe"
    )
    assert bundled_name("agentspace-sidecar-aarch64-apple-darwin") == "agentspace-sidecar"
