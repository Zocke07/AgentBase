"""The Codex App Server runtime, fetched once instead of frozen into the sidecar.

The runtime is a 220 MB signed binary. Bundling it made every launch of the
one-file sidecar unpack it, so it lives in the app data directory instead:
downloaded on the first ChatGPT sign-in from the exact wheel `uv.lock` pins,
verified against that wheel's SHA-256 and size before anything is unpacked,
and reused on every later launch. API-key users never fetch it.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import importlib
import importlib.resources
import json
import os
import platform
import shutil
import stat
import sys
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Final, Literal

import httpx2

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

__all__ = [
    "CodexRuntimeError",
    "CodexRuntimeInstaller",
    "CodexRuntimeManifest",
    "CodexRuntimeStatus",
    "RuntimeWheel",
    "manifest_from_lock",
    "platform_tag",
]

MANIFEST_RESOURCE: Final[str] = "codex_runtime.json"
RUNTIME_PACKAGE: Final[str] = "openai-codex-cli-bin"
#: The wheel members the SDK uses. `bin/codex-code-mode-host` is not one of them.
_WANTED_PREFIXES: Final[tuple[str, ...]] = (
    "codex_cli_bin/codex-package.json",
    "codex_cli_bin/bin/codex",
    "codex_cli_bin/codex-path/",
    "codex_cli_bin/codex-resources/",
)
_UNWANTED_PREFIXES: Final[tuple[str, ...]] = ("codex_cli_bin/bin/codex-code-mode-host",)
_MAX_MEMBER_BYTES: Final[int] = 1_000_000_000
_CHUNK_BYTES: Final[int] = 1 << 20

RuntimeState = Literal["ready", "missing", "downloading", "error"]


class CodexRuntimeError(RuntimeError):
    """The runtime could not be fetched or verified; nothing was installed."""


@dataclass(frozen=True, slots=True)
class RuntimeWheel:
    tag: str
    url: str
    sha256: str
    size: int


@dataclass(frozen=True, slots=True)
class CodexRuntimeStatus:
    """What the UI may know about the runtime. Never a path outside the data dir."""

    state: RuntimeState
    version: str
    downloaded_bytes: int = 0
    total_bytes: int = 0
    error: str | None = None


@dataclass(frozen=True, slots=True)
class CodexRuntimeManifest:
    version: str
    wheels: Mapping[str, RuntimeWheel]

    @classmethod
    def load(cls) -> CodexRuntimeManifest:
        text = importlib.resources.files("agentspace.providers").joinpath(MANIFEST_RESOURCE)
        return cls.from_json(text.read_text(encoding="utf-8"))

    @classmethod
    def from_json(cls, text: str) -> CodexRuntimeManifest:
        raw = json.loads(text)
        wheels = {
            tag: RuntimeWheel(
                tag=tag, url=entry["url"], sha256=entry["sha256"], size=int(entry["size"])
            )
            for tag, entry in raw["wheels"].items()
        }
        return cls(version=str(raw["version"]), wheels=wheels)

    def to_json(self) -> str:
        return (
            json.dumps(
                {
                    "package": RUNTIME_PACKAGE,
                    "version": self.version,
                    "wheels": {
                        tag: {"url": wheel.url, "sha256": wheel.sha256, "size": wheel.size}
                        for tag, wheel in sorted(self.wheels.items())
                    },
                },
                indent=2,
            )
            + "\n"
        )

    def wheel_for(self, tag: str) -> RuntimeWheel:
        try:
            return self.wheels[tag]
        except KeyError as exc:
            raise CodexRuntimeError(
                f"ChatGPT sign-in is not available on this platform ({tag})."
            ) from exc


def manifest_from_lock(lock_text: str) -> CodexRuntimeManifest:
    """Read the pinned wheels out of `uv.lock`, the single source of the pin."""
    import tomllib

    lock = tomllib.loads(lock_text)
    for package in lock.get("package", []):
        if package.get("name") != RUNTIME_PACKAGE:
            continue
        wheels: dict[str, RuntimeWheel] = {}
        for wheel in package.get("wheels", []):
            filename = wheel["url"].rsplit("/", 1)[-1]
            tag = filename.removesuffix(".whl").split("-py3-none-", 1)[1]
            wheels[tag] = RuntimeWheel(
                tag=tag,
                url=wheel["url"],
                sha256=wheel["hash"].removeprefix("sha256:"),
                size=int(wheel["size"]),
            )
        return CodexRuntimeManifest(version=str(package["version"]), wheels=wheels)
    raise CodexRuntimeError(f"{RUNTIME_PACKAGE} is not in the lock file.")


def platform_tag(
    system: str = sys.platform, machine: str = platform.machine(), libc: str | None = None
) -> str:
    """The wheel tag this process needs, in the lock file's spelling."""
    arch = machine.lower()
    if system == "darwin":
        return "macosx_11_0_arm64" if arch in {"arm64", "aarch64"} else "macosx_10_9_x86_64"
    if system == "win32":
        return "win_arm64" if arch in {"arm64", "aarch64"} else "win_amd64"
    flavour = "musllinux_1_1" if (libc or platform.libc_ver()[0]) == "" else "manylinux_2_17"
    return f"{flavour}_{'aarch64' if arch in {'arm64', 'aarch64'} else 'x86_64'}"


def development_codex_path() -> Path | None:
    """A checkout with the runtime wheel installed uses it directly, offline.

    The frozen sidecar excludes `codex_cli_bin`, so there the import fails and
    the installer's own copy is the only one.
    """
    try:
        module = importlib.import_module("codex_cli_bin")
        found = module.bundled_codex_path()
    except (ImportError, FileNotFoundError):
        return None
    return Path(str(found))


@dataclass
class CodexRuntimeInstaller:
    """Owns `<data dir>/codex-runtime/<version>/<tag>/`, one install at a time."""

    root: Path
    manifest: CodexRuntimeManifest = field(default_factory=CodexRuntimeManifest.load)
    tag: str = field(default_factory=platform_tag)
    #: Swapped in tests for a client bound to a local server.
    client_factory: Callable[[], httpx2.AsyncClient] = field(
        default=lambda: httpx2.AsyncClient(timeout=httpx2.Timeout(30.0, read=120.0))
    )
    #: The runtime a development checkout already has installed, if importable.
    development_codex: Callable[[], Path | None] | None = development_codex_path
    _task: asyncio.Task[Path] | None = field(default=None, init=False)
    _downloaded: int = field(default=0, init=False)
    _total: int = field(default=0, init=False)
    _error: str | None = field(default=None, init=False)

    @property
    def install_dir(self) -> Path:
        return self.root / self.manifest.version / self.tag

    def _binary_name(self) -> str:
        return "codex.exe" if self.tag.startswith("win") else "codex"

    def installed_codex(self) -> Path | None:
        """The verified runtime's executable, or None until one is installed."""
        if self.development_codex is not None:
            found = self.development_codex()
            if found is not None:
                return found
        marker = self.install_dir / ".complete"
        binary = self.install_dir / "codex_cli_bin" / "bin" / self._binary_name()
        return binary if marker.is_file() and binary.is_file() else None

    def path_dirs(self) -> tuple[Path, ...]:
        """Directories the SDK would put on PATH when it resolved the bundle itself."""
        codex = self.installed_codex()
        if codex is None:
            return ()
        extra = codex.parent.parent / "codex-path"
        return (extra,) if extra.is_dir() else ()

    def status(self) -> CodexRuntimeStatus:
        version = self.manifest.version
        if self.installed_codex() is not None:
            return CodexRuntimeStatus(state="ready", version=version)
        if self._task is not None and not self._task.done():
            return CodexRuntimeStatus(
                state="downloading",
                version=version,
                downloaded_bytes=self._downloaded,
                total_bytes=self._total,
            )
        if self._error is not None:
            return CodexRuntimeStatus(state="error", version=version, error=self._error)
        return CodexRuntimeStatus(state="missing", version=version)

    def start(self) -> asyncio.Task[Path]:
        """Begin the fetch once; every caller shares the same task."""
        if self._task is None or self._task.done():
            self._error = None
            self._task = asyncio.create_task(self._install(), name="codex-runtime-install")
        return self._task

    async def ensure(self) -> Path:
        installed = self.installed_codex()
        if installed is not None:
            return installed
        return await self.start()

    async def aclose(self) -> None:
        task = self._task
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, CodexRuntimeError):
                await task

    async def _install(self) -> Path:
        installed = self.installed_codex()
        if installed is not None:
            return installed
        wheel = self.manifest.wheel_for(self.tag)
        self._downloaded, self._total = 0, wheel.size
        staging = self.root / self.manifest.version / f"{self.tag}.partial-{os.getpid()}"
        try:
            await asyncio.to_thread(self._reset, staging)
            archive = staging / "runtime.whl"
            await self._download(wheel, archive)
            await asyncio.to_thread(self._unpack, archive, staging)
            await asyncio.to_thread(self._commit, staging)
        except asyncio.CancelledError:
            await asyncio.to_thread(shutil.rmtree, staging, True)
            raise
        except CodexRuntimeError as exc:
            self._error = str(exc)
            await asyncio.to_thread(shutil.rmtree, staging, True)
            raise
        except (OSError, httpx2.HTTPError, zipfile.BadZipFile) as exc:
            self._error = f"The ChatGPT runtime could not be installed: {exc}"
            await asyncio.to_thread(shutil.rmtree, staging, True)
            raise CodexRuntimeError(self._error) from exc
        codex = self.installed_codex()
        if codex is None:  # pragma: no cover - commit wrote the marker
            raise CodexRuntimeError("The ChatGPT runtime install did not complete.")
        return codex

    @staticmethod
    def _reset(staging: Path) -> None:
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True)

    async def _download(self, wheel: RuntimeWheel, archive: Path) -> None:
        digest = hashlib.sha256()
        received = 0
        async with (
            self.client_factory() as client,
            client.stream("GET", wheel.url) as response,
        ):
            if response.status_code != 200:
                raise CodexRuntimeError(
                    f"The ChatGPT runtime download answered HTTP {response.status_code}."
                )
            with archive.open("wb") as handle:
                async for chunk in response.aiter_bytes(_CHUNK_BYTES):
                    received += len(chunk)
                    if received > wheel.size:
                        raise CodexRuntimeError(
                            "The ChatGPT runtime download is larger than the pinned wheel."
                        )
                    digest.update(chunk)
                    handle.write(chunk)
                    self._downloaded = received
        if received != wheel.size:
            raise CodexRuntimeError(
                f"The ChatGPT runtime download stopped at {received:,} of {wheel.size:,} bytes."
            )
        if digest.hexdigest() != wheel.sha256:
            raise CodexRuntimeError(
                "The ChatGPT runtime download did not match the pinned SHA-256 and was discarded."
            )
        self._downloaded = received

    def _unpack(self, archive: Path, staging: Path) -> None:
        with zipfile.ZipFile(archive) as bundle:
            members = [
                info
                for info in bundle.infolist()
                if info.filename.startswith(_WANTED_PREFIXES)
                and not info.filename.startswith(_UNWANTED_PREFIXES)
                and not info.is_dir()
            ]
            if not any(
                info.filename == f"codex_cli_bin/bin/{self._binary_name()}" for info in members
            ):
                raise CodexRuntimeError("The ChatGPT runtime wheel has no codex executable.")
            for info in members:
                relative = Path(info.filename)
                if relative.is_absolute() or ".." in relative.parts:
                    raise CodexRuntimeError("The ChatGPT runtime wheel has an unsafe path.")
                if info.file_size > _MAX_MEMBER_BYTES:
                    raise CodexRuntimeError(
                        "The ChatGPT runtime wheel has an oversized member."
                    )
                target = staging / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(info) as source, target.open("wb") as sink:
                    shutil.copyfileobj(source, sink, _CHUNK_BYTES)
                # The wheel records POSIX modes; restore its executables as they were.
                if os.name != "nt" and (info.external_attr >> 16) & stat.S_IXUSR:
                    target.chmod(
                        target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
                    )
        archive.unlink()

    def _commit(self, staging: Path) -> None:
        (staging / ".complete").write_text(self.manifest.version + "\n", encoding="utf-8")
        final = self.install_dir
        shutil.rmtree(final, ignore_errors=True)
        final.parent.mkdir(parents=True, exist_ok=True)
        staging.replace(final)


def write_manifest(lock_path: Path, manifest_path: Path) -> None:
    manifest = manifest_from_lock(lock_path.read_text(encoding="utf-8"))
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=manifest_path.parent, delete=False
    ) as handle:
        handle.write(manifest.to_json())
        temporary = Path(handle.name)
    temporary.replace(manifest_path)


if __name__ == "__main__":  # pragma: no cover - `just codex-manifest`
    write_manifest(Path(sys.argv[1]), Path(sys.argv[2]))
