"""Process-wide configuration.

Two BUILD_SPEC constraints are enforced here rather than documented elsewhere:

* **§1 constraint 3** — the bind address is a module constant. There is no
  setting, no environment variable and no CLI flag that moves it off the
  loopback interface. :func:`assert_loopback_only` exists so a test can assert
  that fact rather than trusting a comment.
* **§5 Phase 0** — every path is a :class:`pathlib.Path`. There is no string
  concatenation of paths anywhere in this package; ruff's ``PTH`` rules are on
  to keep it that way.

API keys are deliberately absent from this module. They live in the OS keychain
and reach the sidecar over stdin at spawn time (§1 constraint 4, §5 Phase 3).
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
    "assert_loopback_only",
    "default_data_dir",
    "resolve_app_paths",
]

APP_NAME: Final[str] = "AgentSpace"

#: The only interface this application ever binds. Hardcoded on purpose — see
#: BUILD_SPEC §1 constraint 3. Do not make this configurable.
BIND_HOST: Final[str] = "127.0.0.1"

#: Default sidecar port (BUILD_SPEC §2). The port *may* move if it is occupied;
#: the host may not.
DEFAULT_BIND_PORT: Final[int] = 8787

#: Environment variable the Tauri shell uses to hand the sidecar its data
#: directory, resolved there through Tauri's own path API (§5 Phase 2).
DATA_DIR_ENV_VAR: Final[str] = "AGENTSPACE_DATA_DIR"

#: Page origins allowed to read responses from the sidecar.
#:
#: The webview does not share an origin with the sidecar — Tauri serves the app
#: from ``http://tauri.localhost`` on Windows and ``tauri://localhost``
#: elsewhere — so every request from the UI is cross-origin and the browser
#: withholds the response without these headers. Binding loopback stops other
#: *machines* reaching the sidecar; it does nothing about which page origins a
#: browser will hand the body to.
#:
#: This is an explicit allowlist and must stay one. A wildcard would let any
#: web page the user happens to have open read from their agent workspace.
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
    workspace_root: Path

    def ensure_exists(self) -> None:
        """Create the directories this application owns.

        Not called at import time — a module import must never touch the disk.
        """
        for directory in (self.data_dir, self.logs_dir, self.workspace_root):
            directory.mkdir(parents=True, exist_ok=True)


def default_data_dir(platform_name: str = sys.platform) -> Path:
    """Return the per-user application data directory for the host OS.

    Windows is the primary target (§1 constraint 7); macOS is kept correct so it
    builds in CI from day one. Linux is here because CI runs there.

    ``platform_name`` is a parameter rather than a direct :data:`sys.platform`
    read for two reasons: mypy narrows a literal ``sys.platform`` comparison to
    the host it is running on, so ``warn_unreachable`` would flag the other two
    branches as dead code; and every branch stays reachable from a test on any
    one machine, which is the only way this gets exercised before CI.
    """
    if platform_name == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA")
        base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
        return base / APP_NAME

    if platform_name == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME

    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg_data_home) if xdg_data_home else Path.home() / ".local" / "share"
    return base / APP_NAME.lower()


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
        workspace_root=resolved / "workspace",
    )


def assert_loopback_only(host: str) -> None:
    """Raise unless ``host`` is the hardcoded loopback address.

    Called at every point a socket is bound, so that a future refactor which
    threads a host through from configuration fails loudly instead of quietly
    exposing the sidecar to the network.
    """
    if host != BIND_HOST:
        msg = (
            f"refusing to bind {host!r}: this application binds {BIND_HOST!r} only "
            f"(BUILD_SPEC §1 constraint 3)"
        )
        raise ValueError(msg)
