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
    "adopt_legacy_workspace",
    "assert_loopback_only",
    "default_data_dir",
    "resolve_app_paths",
]

APP_NAME: Final[str] = "AgentSpace"

#: The Tauri bundle identifier, from ``tauri.conf.json``; a test keeps them in step.
#:
#: The data directory derives from this, not :data:`APP_NAME`: the NSIS
#: installer installs into ``%LOCALAPPDATA%\\AgentSpace``, which is exactly
#: where an ``APP_NAME``-based data directory would land, inside the
#: installation. ``%LOCALAPPDATA%\\dev.agentspace.desktop`` is also what the
#: shell's ``app_local_data_dir()`` gives (not ``app_data_dir()``, which on
#: Windows is the roaming profile), so the two name the same place.
APP_IDENTIFIER: Final[str] = "dev.agentspace.desktop"

#: The only interface this application ever binds. Hardcoded on purpose; see
#: BUILD_SPEC §1 constraint 3. Do not make this configurable.
BIND_HOST: Final[str] = "127.0.0.1"

#: Default sidecar port (BUILD_SPEC §2). The port *may* move if it is occupied;
#: the host may not.
DEFAULT_BIND_PORT: Final[int] = 8787

#: Environment variable the Tauri shell uses to hand the sidecar its data directory.
DATA_DIR_ENV_VAR: Final[str] = "AGENTSPACE_DATA_DIR"

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
    #: space's runs (:meth:`~agentspace.store.spaces.SpaceStore.folder_for`).
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


def default_data_dir(platform_name: str = sys.platform) -> Path:
    """Return the per-user application data directory for the host OS.

    ``platform_name`` is a parameter so mypy does not prune the other
    platforms' branches as unreachable, and so a test can reach every branch.
    """
    if platform_name == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA")
        base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
        return base / APP_IDENTIFIER

    if platform_name == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_IDENTIFIER

    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg_data_home) if xdg_data_home else Path.home() / ".local" / "share"
    return base / APP_IDENTIFIER


def resolve_app_paths(data_dir: Path | None = None) -> AppPaths:
    """Resolve every path this application uses.

    :param data_dir: explicit override, as passed by the Tauri shell. When
        omitted, ``AGENTSPACE_DATA_DIR`` is consulted, then the OS default.
    """
    if data_dir is None:
        from_env = os.environ.get(DATA_DIR_ENV_VAR)
        data_dir = Path(from_env) if from_env else default_data_dir()

    resolved = data_dir.expanduser().resolve()
    return AppPaths(
        data_dir=resolved,
        db_path=resolved / "agentspace.sqlite3",
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
