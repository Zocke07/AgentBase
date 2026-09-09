"""Constraint tests for :mod:`agentspace.config`.

These assert BUILD_SPEC §1 constraint 3 (loopback only) as executable facts, so
that a later refactor which makes the bind address configurable fails CI rather
than shipping.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentspace import config


def test_bind_host_is_loopback() -> None:
    assert config.BIND_HOST == "127.0.0.1"


@pytest.mark.parametrize(
    "host",
    ["0.0.0.0", "::", "localhost", "192.168.1.10", "", "127.0.0.2"],  # noqa: S104
)
def test_assert_loopback_only_rejects_everything_else(host: str) -> None:
    with pytest.raises(ValueError, match="refusing to bind"):
        config.assert_loopback_only(host)


def test_assert_loopback_only_accepts_the_constant() -> None:
    config.assert_loopback_only(config.BIND_HOST)


def test_bind_host_is_not_influenced_by_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No environment variable may move the bind address off loopback."""
    for name in ("HOST", "BIND_HOST", "AGENTSPACE_HOST", "AGENTSPACE_BIND_HOST"):
        monkeypatch.setenv(name, "0.0.0.0")  # noqa: S104

    assert config.BIND_HOST == "127.0.0.1"
    config.assert_loopback_only(config.BIND_HOST)


def test_default_data_dir_is_absolute() -> None:
    assert config.default_data_dir().is_absolute()


def test_resolve_app_paths_honours_an_explicit_override(tmp_path: Path) -> None:
    paths = config.resolve_app_paths(tmp_path)

    assert paths.data_dir == tmp_path.resolve()
    assert paths.db_path == tmp_path.resolve() / "agentspace.sqlite3"
    assert paths.logs_dir.parent == paths.data_dir
    assert paths.workspace_root.parent == paths.data_dir


def test_resolve_app_paths_reads_the_data_dir_env_var(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(config.DATA_DIR_ENV_VAR, str(tmp_path))

    assert config.resolve_app_paths().data_dir == tmp_path.resolve()


def test_every_resolved_path_is_a_pathlib_path(tmp_path: Path) -> None:
    """§5 Phase 0: paths are Path objects, never assembled strings."""
    paths = config.resolve_app_paths(tmp_path)

    for value in (paths.data_dir, paths.db_path, paths.logs_dir, paths.workspace_root):
        assert isinstance(value, Path)
        assert value.is_absolute()


def test_ensure_exists_creates_the_directories(tmp_path: Path) -> None:
    paths = config.resolve_app_paths(tmp_path / "fresh")
    assert not paths.data_dir.exists()

    paths.ensure_exists()

    assert paths.data_dir.is_dir()
    assert paths.logs_dir.is_dir()
    assert paths.workspace_root.is_dir()


def test_app_paths_is_frozen(tmp_path: Path) -> None:
    paths = config.resolve_app_paths(tmp_path)

    with pytest.raises(AttributeError):
        paths.data_dir = tmp_path  # type: ignore[misc]


# --- per-platform data directory -------------------------------------------
#
# `default_data_dir` takes the platform as an argument precisely so all three
# branches are reachable from whichever machine happens to be running the suite.


def test_data_dir_on_windows_uses_localappdata(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(Path("C:/Users/example/AppData/Local")))

    result = config.default_data_dir("win32")

    assert result == Path("C:/Users/example/AppData/Local") / config.APP_IDENTIFIER


def test_data_dir_on_windows_falls_back_when_localappdata_is_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LOCALAPPDATA", raising=False)

    result = config.default_data_dir("win32")

    assert result.parts[-3:] == ("AppData", "Local", config.APP_IDENTIFIER)


def test_data_dir_on_macos_uses_application_support() -> None:
    result = config.default_data_dir("darwin")

    assert result.parts[-3:] == ("Library", "Application Support", config.APP_IDENTIFIER)


def test_data_dir_on_linux_honours_xdg_data_home(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", "/home/example/.local/share")

    result = config.default_data_dir("linux")

    assert result == Path("/home/example/.local/share") / config.APP_IDENTIFIER


def test_data_dir_on_linux_falls_back_when_xdg_is_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)

    result = config.default_data_dir("linux")

    assert result.parts[-3:] == (".local", "share", config.APP_IDENTIFIER)


@pytest.mark.parametrize("platform_name", ["win32", "darwin", "linux", "freebsd"])
def test_data_dir_is_always_absolute(platform_name: str) -> None:
    assert config.default_data_dir(platform_name).is_absolute()


# --- the data directory must not land inside the installation ---------------


def test_data_dir_is_derived_from_the_identifier_not_the_product_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    r"""Tauri's per-user NSIS installer installs into `%LOCALAPPDATA%\AgentSpace`.

    That is byte for byte where an `APP_NAME`-derived data directory resolves,
    so the SQLite event log would sit inside the installation — deleted by an
    uninstall, at risk from an upgrade. This is not theoretical: a stray
    `agentspace.sqlite3` was found in the installed application's own directory
    during Phase 2, which is what prompted the change.
    """
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\someone\AppData\Local")

    data_dir = config.default_data_dir("win32")

    assert data_dir.name == config.APP_IDENTIFIER
    assert data_dir.name != config.APP_NAME


def test_data_dir_matches_what_tauri_would_inject(monkeypatch: pytest.MonkeyPatch) -> None:
    r"""The fallback and the shell's injected value must name the same place.

    The shell resolves `app_local_data_dir()` — `%LOCALAPPDATA%\<identifier>` on
    Windows — and passes it at spawn time. If this fallback disagreed, a sidecar
    started without the variable would silently read a different, empty database
    than the one the app writes.

    Note `app_local_data_dir()`, not `app_data_dir()`: on Windows the latter is
    `%APPDATA%`, the roaming profile, and a live SQLite database must not roam.
    The first packaged build of this phase used `app_data_dir()` and put the
    database in `%APPDATA%` — caught only by installing the app and looking at
    where the file landed, which is why this test names the call explicitly.
    """
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\someone\AppData\Local")

    tauri_app_data_dir = Path(r"C:\Users\someone\AppData\Local") / config.APP_IDENTIFIER

    assert config.default_data_dir("win32") == tauri_app_data_dir


def test_identifier_matches_tauri_conf() -> None:
    """`tauri.conf.json` is the source of truth; drift breaks the path above."""
    conf = json.loads(
        (
            Path(__file__).resolve().parents[3] / "apps/desktop/src-tauri/tauri.conf.json"
        ).read_text(encoding="utf-8")
    )

    assert conf["identifier"] == config.APP_IDENTIFIER
