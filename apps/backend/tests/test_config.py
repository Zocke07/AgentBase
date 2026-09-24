"""Constraint tests for :mod:`agentbase.config`.

These assert BUILD_SPEC §1 constraint 3 (loopback only) as executable facts, so
that a later refactor which makes the bind address configurable fails CI rather
than shipping.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentbase import config


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
    for name in ("HOST", "BIND_HOST", "AGENTBASE_HOST", "AGENTBASE_BIND_HOST"):
        monkeypatch.setenv(name, "0.0.0.0")  # noqa: S104

    assert config.BIND_HOST == "127.0.0.1"
    config.assert_loopback_only(config.BIND_HOST)


def test_default_data_dir_is_absolute() -> None:
    assert config.default_data_dir().is_absolute()


def test_resolve_app_paths_honours_an_explicit_override(tmp_path: Path) -> None:
    paths = config.resolve_app_paths(tmp_path)

    assert paths.data_dir == tmp_path.resolve()
    assert paths.db_path == tmp_path.resolve() / "agentbase.sqlite3"
    assert paths.logs_dir.parent == paths.data_dir
    assert paths.spaces_dir.parent == paths.data_dir


def test_resolve_app_paths_reads_the_data_dir_env_var(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(config.DATA_DIR_ENV_VAR, str(tmp_path))

    assert config.resolve_app_paths().data_dir == tmp_path.resolve()


# --- AgentSpace data migration ---------------------------------------------


def test_empty_agentbase_data_dir_adopts_agentspace_data_and_database(tmp_path: Path) -> None:
    """The shell creates the new directory before the sidecar can migrate it."""
    legacy_data_dir = tmp_path / config.LEGACY_APP_IDENTIFIER
    legacy_data_dir.mkdir()
    legacy_database = legacy_data_dir / config.LEGACY_DATABASE_FILENAME
    legacy_database.write_bytes(b"database")
    (legacy_data_dir / f"{config.LEGACY_DATABASE_FILENAME}-wal").write_bytes(b"wal")
    (legacy_data_dir / "workspace").mkdir()
    (legacy_data_dir / "workspace" / "notes.md").write_text("kept", encoding="utf-8")

    data_dir = tmp_path / config.APP_IDENTIFIER
    data_dir.mkdir()

    assert config.adopt_legacy_app_data(data_dir, legacy_data_dir) is True

    assert not legacy_data_dir.exists()
    assert (data_dir / config.DATABASE_FILENAME).read_bytes() == b"database"
    assert (data_dir / f"{config.DATABASE_FILENAME}-wal").read_bytes() == b"wal"
    assert not (data_dir / config.LEGACY_DATABASE_FILENAME).exists()
    assert (data_dir / "workspace" / "notes.md").read_text(encoding="utf-8") == "kept"


def test_existing_agentbase_data_is_never_overwritten_by_agentspace_data(
    tmp_path: Path,
) -> None:
    legacy_data_dir = tmp_path / config.LEGACY_APP_IDENTIFIER
    legacy_data_dir.mkdir()
    (legacy_data_dir / config.LEGACY_DATABASE_FILENAME).write_bytes(b"legacy")

    data_dir = tmp_path / config.APP_IDENTIFIER
    data_dir.mkdir()
    (data_dir / config.DATABASE_FILENAME).write_bytes(b"new")

    assert config.adopt_legacy_app_data(data_dir, legacy_data_dir) is False

    assert (legacy_data_dir / config.LEGACY_DATABASE_FILENAME).read_bytes() == b"legacy"
    assert (data_dir / config.DATABASE_FILENAME).read_bytes() == b"new"


def test_resolve_app_paths_adopts_only_the_canonical_agentbase_location(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    legacy_data_dir = tmp_path / config.LEGACY_APP_IDENTIFIER
    legacy_data_dir.mkdir()
    (legacy_data_dir / config.LEGACY_DATABASE_FILENAME).write_bytes(b"legacy")
    canonical_data_dir = tmp_path / config.APP_IDENTIFIER
    canonical_data_dir.mkdir()
    custom_data_dir = tmp_path / "portable-agentbase"

    monkeypatch.setattr(config, "default_data_dir", lambda: canonical_data_dir)
    monkeypatch.setattr(config, "_legacy_data_dir", lambda: legacy_data_dir)
    monkeypatch.setenv(config.DATA_DIR_ENV_VAR, str(custom_data_dir))

    paths = config.resolve_app_paths()

    assert paths.data_dir == custom_data_dir.resolve()
    assert legacy_data_dir.is_dir()
    assert canonical_data_dir.is_dir()
    assert not any(canonical_data_dir.iterdir())
    assert not custom_data_dir.exists()


def test_resolve_app_paths_adopts_the_canonical_agentbase_location(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    legacy_data_dir = tmp_path / config.LEGACY_APP_IDENTIFIER
    legacy_data_dir.mkdir()
    (legacy_data_dir / config.LEGACY_DATABASE_FILENAME).write_bytes(b"legacy")
    data_dir = tmp_path / config.APP_IDENTIFIER
    data_dir.mkdir()

    monkeypatch.setattr(config, "default_data_dir", lambda: data_dir)
    monkeypatch.setattr(config, "_legacy_data_dir", lambda: legacy_data_dir)
    monkeypatch.setenv(config.DATA_DIR_ENV_VAR, str(data_dir))

    paths = config.resolve_app_paths()

    assert paths.data_dir == data_dir.resolve()
    assert paths.db_path.read_bytes() == b"legacy"
    assert not legacy_data_dir.exists()


def test_every_resolved_path_is_a_pathlib_path(tmp_path: Path) -> None:
    """§5 Phase 0: paths are Path objects, never assembled strings."""
    paths = config.resolve_app_paths(tmp_path)

    for value in (paths.data_dir, paths.db_path, paths.logs_dir, paths.spaces_dir):
        assert isinstance(value, Path)
        assert value.is_absolute()


def test_ensure_exists_creates_the_directories(tmp_path: Path) -> None:
    paths = config.resolve_app_paths(tmp_path / "fresh")
    assert not paths.data_dir.exists()

    paths.ensure_exists()

    assert paths.data_dir.is_dir()
    assert paths.logs_dir.is_dir()
    assert paths.spaces_dir.is_dir()
    # The pre-spaces workspace is never created; it is only ever adopted.
    assert not paths.legacy_workspace.exists()


def test_the_old_workspace_becomes_the_default_space_folder_once(tmp_path: Path) -> None:
    """§5 Phase 11's third acceptance criterion, the folder half: a data
    directory from before spaces keeps its files, under the default space."""
    paths = config.resolve_app_paths(tmp_path)
    paths.legacy_workspace.mkdir(parents=True)
    (paths.legacy_workspace / "notes.txt").write_text("kept", encoding="utf-8")
    target = paths.spaces_dir / "default-space"

    assert config.adopt_legacy_workspace(paths, target) is True

    assert not paths.legacy_workspace.exists()
    assert (target / "notes.txt").read_text(encoding="utf-8") == "kept"
    # A second launch finds nothing to move; a fresh directory finds nothing either.
    assert config.adopt_legacy_workspace(paths, target) is False
    assert (
        config.adopt_legacy_workspace(config.resolve_app_paths(tmp_path / "new"), target)
        is False
    )


def test_an_existing_default_space_folder_is_never_overwritten(tmp_path: Path) -> None:
    paths = config.resolve_app_paths(tmp_path)
    paths.legacy_workspace.mkdir(parents=True)
    target = paths.spaces_dir / "default-space"
    target.mkdir(parents=True)
    (target / "mine.txt").write_text("already here", encoding="utf-8")

    assert config.adopt_legacy_workspace(paths, target) is False

    assert paths.legacy_workspace.is_dir()
    assert (target / "mine.txt").read_text(encoding="utf-8") == "already here"


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
    r"""Tauri's per-user NSIS installer installs into `%LOCALAPPDATA%\AgentBase`.

    That is byte for byte where an `APP_NAME`-derived data directory resolves,
    so the SQLite event log would sit inside the installation: deleted by an
    uninstall, at risk from an upgrade. This is not theoretical: a stray
    `agentbase.sqlite3` was found in the installed application's own directory
    during Phase 2, which is what prompted the change.
    """
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\someone\AppData\Local")

    data_dir = config.default_data_dir("win32")

    assert data_dir.name == config.APP_IDENTIFIER
    assert data_dir.name != config.APP_NAME


def test_data_dir_matches_what_tauri_would_inject(monkeypatch: pytest.MonkeyPatch) -> None:
    r"""The fallback and the shell's injected value must name the same place.

    The shell resolves `app_local_data_dir()` (`%LOCALAPPDATA%\<identifier>` on
    Windows) and passes it at spawn time. If this fallback disagreed, a sidecar
    started without the variable would silently read a different, empty database
    than the one the app writes.

    Note `app_local_data_dir()`, not `app_data_dir()`: on Windows the latter is
    `%APPDATA%`, the roaming profile, and a live SQLite database must not roam.
    The first packaged build of this phase used `app_data_dir()` and put the
    database in `%APPDATA%`: caught only by installing the app and looking at
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
