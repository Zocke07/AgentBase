"""Process-wide configuration.

The bind address is a module constant with no setting, variable or flag that
moves it (§1 constraint 3); :func:`assert_loopback_only` lets a test assert
that. Every path is a :class:`pathlib.Path`. API keys are absent by design:
they live in the OS keychain and arrive over stdin (§1 constraint 4).
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

#: The Tauri bundle identifier, from ``tauri.conf.json``; a test keeps them in step.
#:
#: The data directory derives from this, not :data:`APP_NAME`: the NSIS
#: installer installs into ``%LOCALAPPDATA%\\AgentBase``, which is exactly
#: where an ``APP_NAME``-based data directory would land, inside the
#: installation. ``%LOCALAPPDATA%\\dev.agentbase.desktop`` is also what the
#: shell's ``app_local_data_dir()`` gives (not ``app_data_dir()``, which on
#: Windows is the roaming profile), so the two name the same place.
APP_IDENTIFIER: Final[str] = "dev.agentbase.desktop"

#: The database filename used by AgentBase inside :func:`default_data_dir`.
DATABASE_FILENAME: Final[str] = "agentbase.sqlite3"

#: Identifiers from the immediately preceding AgentSpace release. They are
#: deliberately separate from the AgentBase constants above: new installs use
#: only the AgentBase names, while startup can safely adopt an existing install.
LEGACY_APP_IDENTIFIER: Final[str] = "dev.agentspace.desktop"
LEGACY_DATABASE_FILENAME: Final[str] = "agentspace.sqlite3"

_DATABASE_AUXILIARY_SUFFIXES: Final[tuple[str, ...]] = ("", "-wal", "-shm")

#: The only interface this application ever binds. Hardcoded on purpose; see
#: BUILD_SPEC §1 constraint 3. Do not make this configurable.
BIND_HOST: Final[str] = "127.0.0.1"

#: Default sidecar port (BUILD_SPEC §2). The port *may* move if it is occupied;
#: the host may not.
DEFAULT_BIND_PORT: Final[int] = 8787

#: Environment variable the Tauri shell uses to hand the sidecar its data directory.
DATA_DIR_ENV_VAR: Final[str] = "AGENTBASE_DATA_DIR"

#: Page origins allowed to read responses from the sidecar. The webview does
#: not share the sidecar's origin, so without these headers the browser
#: withholds every response. An explicit allowlist, never a wildcard: that
#: would let any page the user has open read from their agent workspace.
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
    #: One folder per space under here, named by id: the sandbox root for that
    #: space's runs (:meth:`~agentbase.store.spaces.SpaceStore.folder_for`).
    spaces_dir: Path
    #: Where the single workspace lived before spaces; :func:`adopt_legacy_workspace` moves it.
    legacy_workspace: Path

    def ensure_exists(self) -> None:
        """Create the directories this application owns. Never called at import time."""
        for directory in (self.data_dir, self.logs_dir, self.spaces_dir):
            directory.mkdir(parents=True, exist_ok=True)


def adopt_legacy_workspace(paths: AppPaths, default_space_folder: Path) -> bool:
    """Make the old single workspace the default space's folder, once.

    Migration 006's SQL cannot touch the disk, so this runs beside it at
    startup, only while the old folder exists and the new one does not.
    Returns whether a move happened.
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
    """Return AgentBase's per-user application data directory for the host OS.

    ``platform_name`` is a parameter so mypy does not prune the other
    platforms' branches as unreachable, and so a test can reach every branch.
    """
    return _data_dir_for_identifier(APP_IDENTIFIER, platform_name)


def _legacy_data_dir(platform_name: str = sys.platform) -> Path:
    """Return the AgentSpace app-data directory corresponding to this host."""
    return _data_dir_for_identifier(LEGACY_APP_IDENTIFIER, platform_name)


def _database_paths(data_dir: Path, filename: str) -> tuple[Path, ...]:
    """Return a SQLite database and its possible WAL-mode companion files."""
    return tuple(data_dir / f"{filename}{suffix}" for suffix in _DATABASE_AUXILIARY_SUFFIXES)


def _adopt_legacy_database(data_dir: Path) -> bool:
    """Rename AgentSpace's SQLite database in ``data_dir`` without overwriting data."""
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
        # Leave both installations usable if moving a WAL companion fails
        # halfway through. The existence checks prevent a rollback from
        # overwriting anything created concurrently.
        for legacy_path, destination_path in reversed(moved):
            if destination_path.exists() and not legacy_path.exists():
                destination_path.rename(legacy_path)
        raise
    return True


def adopt_legacy_app_data(data_dir: Path, legacy_data_dir: Path) -> bool:
    """Move AgentSpace's data directory to AgentBase's location once.

    Tauri creates ``data_dir`` before it starts the sidecar, so an empty
    destination is treated as uninitialized and is replaced. Any non-empty
    destination is left untouched rather than merging two installations.
    The legacy database is renamed after the directory move. Returns whether
    the directory itself moved.
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
    """Resolve every path this application uses.

    :param data_dir: explicit override, as passed by the Tauri shell. When
        omitted, ``AGENTBASE_DATA_DIR`` is consulted, then the OS default.
    """
    if data_dir is None:
        from_env = os.environ.get(DATA_DIR_ENV_VAR)
        data_dir = Path(from_env) if from_env else default_data_dir()

    resolved = data_dir.expanduser().resolve()
    # Only the canonical AgentBase location may absorb the old install. The
    # environment override is also used by tests, portable/dev runs, and
    # callers that intentionally choose a separate workspace; moving an OS
    # profile into one of those paths would be surprising despite being safe.
    try:
        at_canonical_location = resolved == default_data_dir().expanduser().resolve()
    except RuntimeError:
        # No LOCALAPPDATA and no resolvable home directory (`Path.home()`
        # raises this exact message): the canonical location cannot be
        # computed, so `resolved` cannot be confirmed to be it. An explicit
        # override must still work here; only legacy adoption is skipped.
        at_canonical_location = False
    if at_canonical_location:
        adopt_legacy_app_data(resolved, _legacy_data_dir().expanduser().resolve())
        # Also recover a prior directory move that completed before the
        # database filename changed.
        _adopt_legacy_database(resolved)

    return AppPaths(
        data_dir=resolved,
        db_path=resolved / DATABASE_FILENAME,
        logs_dir=resolved / "logs",
        spaces_dir=resolved / "spaces",
        legacy_workspace=resolved / "workspace",
    )


def assert_loopback_only(host: str) -> None:
    """Raise unless ``host`` is the hardcoded loopback address. Called at every bind."""
    if host != BIND_HOST:
        msg = (
            f"refusing to bind {host!r}: this application binds {BIND_HOST!r} only "
            f"(BUILD_SPEC §1 constraint 3)"
        )
        raise ValueError(msg)
