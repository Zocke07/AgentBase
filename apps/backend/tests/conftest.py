"""Shared fixtures.

The async tests run on anyio's pytest plugin rather than pytest-asyncio.
anyio is already in the tree underneath Starlette, and it is what Starlette's
own test client uses, so this adds a declared dependency rather than a new
package.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from agentspace.budget.ledger import BudgetLedger
from agentspace.config import AppPaths
from agentspace.events.bus import EventBus
from agentspace.events.store import EventStore
from agentspace.secrets import SecretStore
from agentspace.store.agents import AgentDefStore
from agentspace.store.db import Database
from agentspace.store.settings import SettingsStore

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path


@pytest.fixture(autouse=True)
def _isolate_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point every test's data directory at `tmp_path`.

    Autouse, and deliberately not optional. `create_app()` with no explicit
    paths falls back to `resolve_app_paths()`, which consults this variable and
    then the real OS app-data directory, so a test that builds an app without
    passing paths opens a database on the developer's actual machine. That is
    not hypothetical: it is how a stray `agentspace.sqlite3` came to sit inside
    the installed application's directory during Phase 2.

    Tests that need a specific directory take the `app_paths` fixture and pass
    it explicitly; this only decides where the *unconfigured* path leads.
    """
    monkeypatch.setenv("AGENTSPACE_DATA_DIR", str(tmp_path / "data-dir-fallback"))


@pytest.fixture
def anyio_backend() -> str:
    """Run `@pytest.mark.anyio` tests on asyncio only; we do not ship trio."""
    return "asyncio"


@pytest.fixture
def app_paths(tmp_path: Path) -> AppPaths:
    """An isolated data directory, laid out exactly as the real one."""
    paths = AppPaths(
        data_dir=tmp_path,
        db_path=tmp_path / "agentspace.sqlite3",
        logs_dir=tmp_path / "logs",
        spaces_dir=tmp_path / "spaces",
        legacy_workspace=tmp_path / "workspace",
    )
    paths.ensure_exists()
    return paths


@pytest.fixture
def db(app_paths: AppPaths) -> Iterator[Database]:
    """A connected, migrated database that is closed before tmp_path is torn down.

    Closing matters on Windows: an open SQLite handle keeps the file locked and
    makes pytest's tmp_path cleanup fail with a PermissionError that has nothing
    to do with the test.
    """
    database = Database(app_paths.db_path)
    database.connect()
    try:
        yield database
    finally:
        database.close()


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


@pytest.fixture
def store(db: Database, bus: EventBus) -> EventStore:
    return EventStore(db, bus)


# --- the workspace stores ----------------------------------------------------
#
# Phase 4 defined these locally in `test_orchestrator.py`. Phase 5 added a
# second and a third module that drive runs, and three copies of the same
# four-line fixture is three places to forget when a store grows a dependency.


@pytest.fixture
def settings(db: Database) -> SettingsStore:
    return SettingsStore(db)


@pytest.fixture
def agents(db: Database, settings: SettingsStore) -> AgentDefStore:
    """The agent registry, seeded with the built-ins by migration 003."""
    return AgentDefStore(db, settings)


@pytest.fixture
def ledger(db: Database, store: EventStore, settings: SettingsStore) -> BudgetLedger:
    return BudgetLedger(db, settings, store)


@pytest.fixture
def secrets() -> SecretStore:
    return SecretStore()


# --- Phase 9: verifying built artefacts, without letting the check vanish -----


def pytest_addoption(parser: pytest.Parser) -> None:
    """Add `--require-build-checks`.

    The tests that inspect a *built* artefact (the frozen sidecar and the NSIS
    installer) skip when there is nothing built, so `just test` stays fast and
    does not depend on build order. That is right for a dev run and wrong for a
    release: a CI job that builds an installer and then skips the staleness
    check has verified nothing, and says so in the same green tick as a job that
    verified everything.

    So the release path passes this flag (see `just verify-build`) and a missing
    binary, a missing installer or a missing 7-Zip becomes a failure naming what
    was absent, instead of a skip nobody reads.
    """
    parser.addoption(
        "--require-build-checks",
        action="store_true",
        default=False,
        help=(
            "Fail, rather than skip, tests that inspect built artefacts. "
            "Used after a build so a missing artefact cannot leave a release "
            "unverified."
        ),
    )

    parser.addoption(
        "--install-smoke",
        action="store_true",
        default=False,
        help=(
            "Install the produced installer on this machine and run the installed "
            "sidecar with Python scrubbed from its environment. Off by default "
            "because it installs software; `just verify-installed` passes it."
        ),
    )


@pytest.fixture
def build_prerequisite(request: pytest.FixtureRequest) -> Callable[[str | None], None]:
    """Skip on a missing build prerequisite, or fail, if the caller demanded it.

    Takes the reason a prerequisite is missing, or ``None`` when nothing is.
    Kept as a fixture rather than a plain helper so it can read the command-line
    option, which a module-level `skipif` condition cannot: those are booleans
    evaluated at import time, before pytest has parsed its arguments.
    """

    def check(missing: str | None) -> None:
        if missing is None:
            return
        if request.config.getoption("--require-build-checks"):
            pytest.fail(
                f"--require-build-checks was given, but {missing}. "
                f"This check was asked for explicitly, so a skip would be a "
                f"release verified by nothing."
            )
        pytest.skip(missing)

    return check
