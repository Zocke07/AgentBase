"""Process-wide configuration.

The bind address is fixed (§1 constraint 3) and asserted by
:func:`assert_loopback_only`. Paths use :class:`pathlib.Path`; API keys stay
in the OS keychain and arrive over stdin (§1 constraint 4).
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final

__all__ = [
    "ALLOWED_ORIGINS",
    "APP_NAME",
    "BIND_HOST",
    "DEFAULT_BIND_PORT",
    "AppPaths",
    "adopt_legacy_app_data",
    "adopt_legacy_workspace",
    "assert_loopback_only",
    "default_data_dir",
    "resolve_app_paths",
]

APP_NAME: Final[str] = "AgentBase"

#: Tauri bundle identifier from ``tauri.conf.json``; a test keeps them aligned.
#:
#: The data directory derives from this, not :data:`APP_NAME`: an
#: ``APP_NAME``-based path would fall inside the Windows NSIS installation.
#: It also matches the shell's ``app_local_data_dir()`` (not roaming
#: ``app_data_dir()``) on Windows.
APP_IDENTIFIER: Final[str] = "dev.agentbase.desktop"

#: The database filename used by AgentBase inside :func:`default_data_dir`.
DATABASE_FILENAME: Final[str] = "agentbase.sqlite3"

#: Identifiers from the preceding AgentSpace release. New installs use only
#: AgentBase names; startup may safely adopt an existing installation.
LEGACY_APP_IDENTIFIER: Final[str] = "dev.agentspace.desktop"
LEGACY_DATABASE_FILENAME: Final[str] = "agentspace.sqlite3"

_DATABASE_AUXILIARY_SUFFIXES: Final[tuple[str, ...]] = ("", "-wal", "-shm")

#: The only bind interface. Intentionally fixed; see BUILD_SPEC §1 constraint 3.
BIND_HOST: Final[str] = "127.0.0.1"

#: Default sidecar port (BUILD_SPEC §2). It may move when occupied; the host may not.
DEFAULT_BIND_PORT: Final[int] = 8787

#: Environment variable the Tauri shell uses to hand the sidecar its data directory.
DATA_DIR_ENV_VAR: Final[str] = "AGENTBASE_DATA_DIR"

#: Origins allowed to read sidecar responses. The webview has a different
#: origin; a wildcard would expose the agent workspace to any open page.
ALLOWED_ORIGINS: Final[tuple[str, ...]] = (
    "http://tauri.localhost",  # Tauri v2 on Windows
    "https://tauri.localhost",
    "tauri://localhost",  # Tauri v2 on macOS and Linux
    "http://127.0.0.1:5173",  # `just dev-desktop`
    "http://localhost:5173",
)


@dataclass(frozen=True, slots=True)
class AppPaths:
    """Resolved on-disk locations. Every field is an absolute path."""

    data_dir: Path
    db_path: Path
    logs_dir: Path
    #: Per-space folders, named by ID: sandbox roots for that space's runs.
    spaces_dir: Path
    #: Pre-spaces workspace, moved by :func:`adopt_legacy_workspace`.
    legacy_workspace: Path

    def ensure_exists(self) -> None:
        """Create application directories; never called at import time."""
        for directory in (self.data_dir, self.logs_dir, self.spaces_dir):
            directory.mkdir(parents=True, exist_ok=True)


def adopt_legacy_workspace(paths: AppPaths, default_space_folder: Path) -> bool:
    """Move the old workspace to the default space once.

    Migration 006 SQL cannot move files, so startup does this only when the
    old folder exists and the destination does not. Returns whether it moved.
    """
    if not paths.legacy_workspace.is_dir() or default_space_folder.exists():
        return False
    default_space_folder.parent.mkdir(parents=True, exist_ok=True)
    paths.legacy_workspace.rename(default_space_folder)
    return True


def _data_dir_for_identifier(identifier: str, platform_name: str) -> Path:
    """Return the per-user application data directory for one bundle identifier."""

    if platform_name == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA")
        base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
        return base / identifier

    if platform_name == "darwin":
        return Path.home() / "Library" / "Application Support" / identifier

    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg_data_home) if xdg_data_home else Path.home() / ".local" / "share"
    return base / identifier


def default_data_dir(platform_name: str = sys.platform) -> Path:
    """Return AgentBase's per-user data directory for the host OS.

    ``platform_name`` keeps all platform branches reachable to mypy and tests.
    """
    return _data_dir_for_identifier(APP_IDENTIFIER, platform_name)


def _legacy_data_dir(platform_name: str = sys.platform) -> Path:
    """Return the AgentSpace app-data directory corresponding to this host."""
    return _data_dir_for_identifier(LEGACY_APP_IDENTIFIER, platform_name)


def _database_paths(data_dir: Path, filename: str) -> tuple[Path, ...]:
    """Return a SQLite database and its possible WAL-mode companion files."""
    return tuple(data_dir / f"{filename}{suffix}" for suffix in _DATABASE_AUXILIARY_SUFFIXES)


def _adopt_legacy_database(data_dir: Path) -> bool:
    """Rename AgentSpace's SQLite database in ``data_dir`` without overwriting."""
    legacy_paths = _database_paths(data_dir, LEGACY_DATABASE_FILENAME)
    destination_paths = _database_paths(data_dir, DATABASE_FILENAME)
    if not legacy_paths[0].is_file() or any(
        path.exists() or path.is_symlink() for path in destination_paths
    ):
        return False

    moved: list[tuple[Path, Path]] = []
    try:
        for legacy_path, destination_path in zip(legacy_paths, destination_paths, strict=True):
            if legacy_path.exists():
                legacy_path.rename(destination_path)
                moved.append((legacy_path, destination_path))
    except OSError:
        # Keep both installations usable if a WAL companion move fails. These
        # existence checks keep rollback from overwriting concurrent output.
        for legacy_path, destination_path in reversed(moved):
            if destination_path.exists() and not legacy_path.exists():
                destination_path.rename(legacy_path)
        raise
    return True


def adopt_legacy_app_data(data_dir: Path, legacy_data_dir: Path) -> bool:
    """Move AgentSpace data to AgentBase's location once.

    Tauri creates ``data_dir`` before the sidecar starts, so an empty
    destination is uninitialized and replaced. Never merge a non-empty
    destination. Rename its legacy database afterward. Returns whether the
    directory moved.
    """
    if (
        data_dir == legacy_data_dir
        or not legacy_data_dir.is_dir()
        or legacy_data_dir.is_symlink()
    ):
        return False

    if data_dir.exists() or data_dir.is_symlink():
        if not data_dir.is_dir() or data_dir.is_symlink() or any(data_dir.iterdir()):
            return False
        data_dir.rmdir()

    legacy_data_dir.rename(data_dir)
    _adopt_legacy_database(data_dir)
    return True


def resolve_app_paths(data_dir: Path | None = None) -> AppPaths:
    """Resolve application paths.

    :param data_dir: explicit override, as passed by the Tauri shell. When
        omitted, ``AGENTBASE_DATA_DIR`` is consulted, then the OS default.
    """
    if data_dir is None:
        from_env = os.environ.get(DATA_DIR_ENV_VAR)
        data_dir = Path(from_env) if from_env else default_data_dir()

    resolved = data_dir.expanduser().resolve()
    # Only the canonical location may absorb the old install. Overrides also
    # serve tests, portable/dev runs, and deliberate separate workspaces.
    try:
        at_canonical_location = resolved == default_data_dir().expanduser().resolve()
    except RuntimeError:
        # Without LOCALAPPDATA or a resolvable home, cannot confirm the
        # canonical location. Keep an explicit override working; skip adoption.
        at_canonical_location = False
    if at_canonical_location:
        adopt_legacy_app_data(resolved, _legacy_data_dir().expanduser().resolve())
        # Also recover a directory move completed before the database rename.
        _adopt_legacy_database(resolved)

    return AppPaths(
        data_dir=resolved,
        db_path=resolved / DATABASE_FILENAME,
        logs_dir=resolved / "logs",
        spaces_dir=resolved / "spaces",
        legacy_workspace=resolved / "workspace",
    )


def assert_loopback_only(host: str) -> None:
    """Raise unless ``host`` is the fixed loopback address; call at every bind."""
    if host != BIND_HOST:
        msg = (
            f"refusing to bind {host!r}: this application binds {BIND_HOST!r} only "
            f"(BUILD_SPEC §1 constraint 3)"
        )
        raise ValueError(msg)
