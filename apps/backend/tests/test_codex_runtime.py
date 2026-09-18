"""The Codex App Server runtime is fetched once, verified, and never bundled."""

from __future__ import annotations

import asyncio
import hashlib
import io
import os
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING

import httpx2
import pytest
from fastapi import FastAPI, Response

from agentspace.providers.codex_runtime import (
    CodexRuntimeError,
    CodexRuntimeInstaller,
    CodexRuntimeManifest,
    RuntimeWheel,
    manifest_from_lock,
    platform_tag,
)

if TYPE_CHECKING:
    from collections.abc import Callable

pytestmark = pytest.mark.anyio

REPO_ROOT = Path(__file__).resolve().parents[3]
BACKEND = REPO_ROOT / "apps" / "backend"
TAG = "macosx_11_0_arm64"


def _executable(name: str) -> zipfile.ZipInfo:
    """A member carrying the POSIX mode a real wheel records for a binary."""
    info = zipfile.ZipInfo(name)
    info.external_attr = 0o755 << 16
    info.compress_type = zipfile.ZIP_DEFLATED
    return info


def _wheel(*, with_binary: bool = True, unsafe: bool = False) -> bytes:
    """A stand-in for the real wheel: the same member layout, tiny contents."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("codex_cli_bin/__init__.py", "")
        bundle.writestr("codex_cli_bin/codex-package.json", '{"version": "0.154.0"}')
        if with_binary:
            bundle.writestr(_executable("codex_cli_bin/bin/codex"), "#!/bin/sh\necho codex\n")
        bundle.writestr("codex_cli_bin/bin/codex-code-mode-host", "unused helper")
        bundle.writestr(_executable("codex_cli_bin/codex-path/rg"), "#!/bin/sh\necho rg\n")
        bundle.writestr("codex_cli_bin/codex-resources/prompt.md", "resource")
        bundle.writestr(_executable("codex_cli_bin/codex-resources/zsh/bin/zsh"), "#!/bin/sh\n")
        if unsafe:
            bundle.writestr("codex_cli_bin/codex-path/../../escape", "no")
    return buffer.getvalue()


def _manifest(
    payload: bytes, *, sha256: str | None = None, size: int | None = None
) -> CodexRuntimeManifest:
    return CodexRuntimeManifest(
        version="0.154.0",
        wheels={
            TAG: RuntimeWheel(
                tag=TAG,
                url="http://runtime.test/wheel",
                sha256=sha256 or hashlib.sha256(payload).hexdigest(),
                size=len(payload) if size is None else size,
            )
        },
    )


def _server(payload: bytes, *, status_code: int = 200) -> Callable[[], httpx2.AsyncClient]:
    app = FastAPI()

    @app.get("/wheel")
    def wheel() -> Response:
        return Response(content=payload, status_code=status_code, media_type="application/zip")

    return lambda: httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app), base_url="http://runtime.test"
    )


def _installer(
    tmp_path: Path, payload: bytes, **manifest_overrides: object
) -> CodexRuntimeInstaller:
    manifest = _manifest(payload, **manifest_overrides)  # type: ignore[arg-type]
    return CodexRuntimeInstaller(
        root=tmp_path / "codex-runtime",
        manifest=manifest,
        tag=TAG,
        client_factory=_server(payload),
        development_codex=lambda: None,
    )


def test_the_committed_manifest_matches_the_lock_file() -> None:
    """The runtime is pinned in one place; the manifest is its projection."""
    committed = CodexRuntimeManifest.load()
    from_lock = manifest_from_lock((BACKEND / "uv.lock").read_text(encoding="utf-8"))

    assert committed == from_lock, "run `just codex-manifest` after changing openai-codex"
    assert {"macosx_11_0_arm64", "win_amd64"} <= set(committed.wheels)
    assert all(
        wheel.url.startswith("https://files.pythonhosted.org/")
        for wheel in committed.wheels.values()
    )


@pytest.mark.parametrize(
    ("system", "machine", "libc", "expected"),
    [
        ("darwin", "arm64", None, "macosx_11_0_arm64"),
        ("darwin", "x86_64", None, "macosx_10_9_x86_64"),
        ("win32", "AMD64", None, "win_amd64"),
        ("win32", "ARM64", None, "win_arm64"),
        ("linux", "x86_64", "glibc", "manylinux_2_17_x86_64"),
        ("linux", "aarch64", "", "musllinux_1_1_aarch64"),
    ],
)
def test_platform_tags_follow_the_wheel_names(
    system: str, machine: str, libc: str | None, expected: str
) -> None:
    assert platform_tag(system, machine, libc) == expected


async def test_the_runtime_is_fetched_verified_unpacked_and_reused(tmp_path: Path) -> None:
    payload = _wheel()
    installer = _installer(tmp_path, payload)
    assert installer.status().state == "missing"
    assert installer.installed_codex() is None

    codex = await installer.ensure()

    status = installer.status()
    assert status.state == "ready"
    assert status.version == "0.154.0"
    assert (
        codex
        == tmp_path / "codex-runtime" / "0.154.0" / TAG / "codex_cli_bin" / "bin" / "codex"
    )
    assert codex.read_text(encoding="utf-8").startswith("#!/bin/sh")
    assert installer.path_dirs() == (codex.parent.parent / "codex-path",)
    assert not (codex.parent / "codex-code-mode-host").exists(), (
        "the unused helper is not unpacked"
    )
    leftovers = await asyncio.to_thread(
        lambda: [*tmp_path.rglob("*.whl"), *tmp_path.rglob("*.partial-*")]
    )
    assert leftovers == [], "the archive and staging directory are gone after unpacking"
    if os.name != "nt":
        assert os.access(codex, os.X_OK)
        assert os.access(codex.parent.parent / "codex-path" / "rg", os.X_OK)
        resources = codex.parent.parent / "codex-resources"
        assert os.access(resources / "zsh" / "bin" / "zsh", os.X_OK)
        assert not os.access(resources / "prompt.md", os.X_OK)

    # A second ensure is a lookup, not a download: the server is not consulted.
    installer.client_factory = _server(b"different bytes would fail the hash")
    assert await installer.ensure() == codex


async def test_a_download_that_does_not_match_the_pin_installs_nothing(tmp_path: Path) -> None:
    payload = _wheel()
    installer = _installer(tmp_path, payload, sha256="0" * 64)

    with pytest.raises(CodexRuntimeError, match="SHA-256"):
        await installer.ensure()

    assert installer.status().state == "error"
    assert "SHA-256" in (installer.status().error or "")
    assert installer.installed_codex() is None
    assert await asyncio.to_thread(lambda: list(tmp_path.rglob("codex"))) == [], (
        "no partial install is left behind"
    )


async def test_a_short_or_oversized_download_is_refused(tmp_path: Path) -> None:
    payload = _wheel()
    short = _installer(tmp_path / "short", payload, size=len(payload) + 10)
    with pytest.raises(CodexRuntimeError, match="stopped at"):
        await short.ensure()

    long = _installer(tmp_path / "long", payload, size=len(payload) - 10)
    with pytest.raises(CodexRuntimeError, match="larger than"):
        await long.ensure()

    assert short.installed_codex() is None
    assert long.installed_codex() is None


async def test_an_http_error_and_an_unsafe_wheel_are_readable_failures(tmp_path: Path) -> None:
    payload = _wheel()
    missing = _installer(tmp_path / "missing", payload)
    missing.client_factory = _server(payload, status_code=404)
    with pytest.raises(CodexRuntimeError, match="HTTP 404"):
        await missing.ensure()

    unsafe_payload = _wheel(unsafe=True)
    unsafe = _installer(tmp_path / "unsafe", unsafe_payload)
    with pytest.raises(CodexRuntimeError, match="unsafe path"):
        await unsafe.ensure()
    assert not (tmp_path / "unsafe" / "escape").exists()

    empty = _installer(tmp_path / "empty", _wheel(with_binary=False))
    with pytest.raises(CodexRuntimeError, match="no codex executable"):
        await empty.ensure()


async def test_concurrent_callers_share_one_download_and_see_progress(tmp_path: Path) -> None:
    payload = _wheel()
    installer = _installer(tmp_path, payload)

    task = installer.start()
    first, second = await asyncio.gather(installer.ensure(), installer.ensure())

    assert first == second == await task
    final = installer.status()
    assert final.state == "ready"
    assert installer.start() is not task, "a finished task is not reused"
    assert installer.installed_codex() == first


async def test_a_development_checkout_uses_its_installed_wheel_offline(tmp_path: Path) -> None:
    local = tmp_path / "venv-codex"
    local.write_text("#!/bin/sh\n", encoding="utf-8")
    installer = CodexRuntimeInstaller(
        root=tmp_path / "codex-runtime",
        manifest=_manifest(b""),
        tag=TAG,
        client_factory=_server(b"never fetched", status_code=500),
        development_codex=lambda: local,
    )

    assert installer.status().state == "ready"
    assert await installer.ensure() == local
    assert installer.path_dirs() == ()


def test_an_unsupported_platform_is_refused_before_any_network_call(tmp_path: Path) -> None:
    installer = CodexRuntimeInstaller(
        root=tmp_path,
        manifest=_manifest(b""),
        tag="plan9_mips",
        development_codex=lambda: None,
    )

    with pytest.raises(CodexRuntimeError, match="not available on this platform"):
        installer.manifest.wheel_for(installer.tag)
