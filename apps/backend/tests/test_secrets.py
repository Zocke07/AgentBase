"""Tests for the API-key handshake and the store that holds keys.

§1 constraint 4 names five places a key must never appear: `.env`, SQLite, a
config file, a log line, and `argv`. Four of those are testable from here, and
each has its own test below rather than being folded into one — a single
"secrets are safe" test would pass while three of the four channels leaked.

The fifth, `argv`, is structural: nothing in this package ever reads a key from
`sys.argv`, and `test_no_secret_is_read_from_argv` asserts that stays true.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

import pytest
import uvicorn

from agentspace import main
from agentspace.config import BIND_HOST
from agentspace.secrets import SECRET_KEYS, SecretStore, parse_secrets_line

if TYPE_CHECKING:
    from pathlib import Path

FAKE_KEY = "totally-not-a-real-key-9f3a2b"


def _server() -> uvicorn.Server:
    """A real Server instance, unstarted — only `should_exit` is inspected.

    Matches the helper in `test_main.py`: a structural stand-in would not
    satisfy `_read_stdin`'s annotation, and loosening that annotation to make a
    fake fit would weaken the production signature for the sake of a test.
    """
    return uvicorn.Server(uvicorn.Config(app=main.create_app(), host=BIND_HOST, port=0))


# --- parsing -----------------------------------------------------------------


def test_a_well_formed_handshake_yields_the_keys() -> None:
    line = json.dumps({"anthropic_api_key": FAKE_KEY, "openai_api_key": "other"})

    assert parse_secrets_line(line) == {
        "anthropic_api_key": FAKE_KEY,
        "openai_api_key": "other",
    }


def test_unknown_keys_are_ignored() -> None:
    """A shell bug must not be able to fill this process's memory with
    arbitrary content under arbitrary names."""
    line = json.dumps({"anthropic_api_key": FAKE_KEY, "root_password": "hunter2"})

    assert parse_secrets_line(line) == {"anthropic_api_key": FAKE_KEY}


def test_the_shutdown_sentinel_is_not_a_secrets_line() -> None:
    """The two uses of stdin have to coexist: `shutdown` is not JSON, so it
    parses to nothing and falls through to the watchdog."""
    assert parse_secrets_line("shutdown\n") == {}


@pytest.mark.parametrize(
    "line",
    ["", "\n", "not json", "[]", '"a string"', "null", "123", '{"anthropic_api_key": null}'],
)
def test_malformed_handshakes_yield_nothing_and_never_raise(line: str) -> None:
    """This runs on the only thread that can stop the process. An exception
    here would leave a sidecar that cannot be shut down."""
    assert parse_secrets_line(line) == {}


def test_empty_values_are_not_stored() -> None:
    """An empty key is a missing key; storing it would make `has()` lie."""
    assert parse_secrets_line(json.dumps({"anthropic_api_key": ""})) == {}


# --- the store ---------------------------------------------------------------


def test_the_store_reports_names_without_values() -> None:
    store = SecretStore({"anthropic_api_key": FAKE_KEY})

    assert store.names == ("anthropic_api_key",)
    assert store.get("anthropic_api_key") == FAKE_KEY
    assert store.has("anthropic_api_key")
    assert not store.has("openai_api_key")


def test_loading_merges_rather_than_replaces() -> None:
    store = SecretStore({"anthropic_api_key": FAKE_KEY})

    store.load({"openai_api_key": "second"})

    assert store.names == ("anthropic_api_key", "openai_api_key")


def test_repr_does_not_contain_the_key() -> None:
    """A default repr in a traceback is a real leak: the Tauri shell pipes this
    process's stderr straight into its own console."""
    store = SecretStore({"anthropic_api_key": FAKE_KEY})

    assert FAKE_KEY not in repr(store)
    assert FAKE_KEY not in str(store)
    assert FAKE_KEY not in f"{store}"


def test_the_key_does_not_appear_in_logs(caplog: pytest.LogCaptureFixture) -> None:
    """§1 constraint 4: never logged."""
    store = SecretStore()

    with caplog.at_level(logging.DEBUG):
        store.load({"anthropic_api_key": FAKE_KEY})

    assert FAKE_KEY not in caplog.text
    # The *name* is logged, because a missing-credential report is undebuggable
    # without knowing whether anything arrived at all.
    assert "anthropic_api_key" in caplog.text


# --- the handshake over stdin ------------------------------------------------


def test_the_first_line_is_consumed_as_the_handshake() -> None:
    store = SecretStore()
    server = _server()
    line = json.dumps({"anthropic_api_key": FAKE_KEY})

    main._read_stdin(server, iter([line + "\n"]), store)

    assert store.get("anthropic_api_key") == FAKE_KEY
    # EOF after the handshake still stops the server.
    assert server.should_exit


def test_the_handshake_does_not_stop_the_server_by_itself() -> None:
    """The secrets line must not be mistaken for a shutdown command."""
    store = SecretStore()
    server = _server()
    lines = iter([json.dumps({"anthropic_api_key": FAKE_KEY}) + "\n", "keep going\n"])

    main._read_stdin(server, lines, store)

    assert store.has("anthropic_api_key")


def test_shutdown_still_works_when_no_handshake_is_sent() -> None:
    """`python -m agentspace` by hand sends no secrets. It must still stop."""
    store = SecretStore()
    server = _server()

    main._read_stdin(server, iter(["shutdown\n"]), store)

    assert server.should_exit
    assert store.names == ()


def test_a_shutdown_sent_first_is_honoured_not_swallowed() -> None:
    """The sentinel is checked before the handshake, so a shell that quits
    immediately is not left waiting."""
    store = SecretStore()
    server = _server()
    lines = iter(["shutdown\n", "never read\n"])

    main._read_stdin(server, lines, store)

    assert server.should_exit
    assert next(lines) == "never read\n"


def test_a_malformed_handshake_does_not_prevent_shutdown() -> None:
    store = SecretStore()
    server = _server()

    main._read_stdin(server, iter(["{{{garbage\n", "shutdown\n"]), store)

    assert server.should_exit
    assert store.names == ()


# --- the channels a key must never reach -------------------------------------


def test_no_secret_is_read_from_argv() -> None:
    """§1 constraint 4: `argv` is world-readable via `ps` / Win32_Process.

    Asserted by absence: no module in this package may read a key from the
    command line, so `sys.argv` must not be consulted anywhere near secrets.
    """
    source = (
        pathlib_source("secrets.py") + pathlib_source("main.py") + pathlib_source("config.py")
    )

    for name in SECRET_KEYS:
        # A key name appearing next to argv parsing is the shape of the bug.
        assert f'argv, "{name}"' not in source
    assert "argparse" not in source


def test_secrets_are_not_written_to_the_database(tmp_path: Path) -> None:
    """§1 constraint 4: never SQLite.

    The settings table lives in the same file as the event log and is plain
    text on disk, so this asserts the store and the database never meet.
    """
    from agentspace.store.db import Database
    from agentspace.store.settings import SettingsStore

    database = Database(tmp_path / "test.sqlite3")
    database.connect()
    try:
        store = SettingsStore(database)
        import anyio

        anyio.run(store.update, {"provider": "anthropic"})

        secrets = SecretStore({"anthropic_api_key": FAKE_KEY})
        assert secrets.has("anthropic_api_key")

        raw = (tmp_path / "test.sqlite3").read_bytes()
        assert FAKE_KEY.encode() not in raw
    finally:
        database.close()


def test_the_settings_model_has_no_field_for_a_key() -> None:
    """The type system is the guard: there is nowhere in WorkspaceSettings to
    put a key even by accident."""
    from agentspace.store.settings import WorkspaceSettings

    for field in WorkspaceSettings.model_fields:
        assert "key" not in field.lower()
        assert "secret" not in field.lower()
        assert "token" not in field.lower()


def pathlib_source(filename: str) -> str:
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentspace"
    return (root / filename).read_text(encoding="utf-8")
