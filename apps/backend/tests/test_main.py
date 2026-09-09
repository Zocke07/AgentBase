"""Tests for the sidecar entry point.

The shutdown tests matter more than the endpoint test. `/health` returning
`{"ok": true}` is the visible half of Phase 1, but the half that actually breaks
in the field is the sidecar outliving the app that spawned it.
"""

from __future__ import annotations

import io

import pytest
import uvicorn
from fastapi.testclient import TestClient

from agentspace import config, main
from agentspace.config import BIND_HOST, DEFAULT_BIND_PORT
from agentspace.secrets import SecretStore


def _server() -> uvicorn.Server:
    """A real Server instance, unstarted — we only inspect `should_exit`."""
    return uvicorn.Server(uvicorn.Config(app=main.create_app(), host=BIND_HOST, port=0))


# --- the HTTP surface -------------------------------------------------------


def test_health_returns_ok() -> None:
    with TestClient(main.create_app()) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_openapi_schema_is_served() -> None:
    """Phase 10 links /docs from the README; it costs nothing to keep it working."""
    with TestClient(main.create_app()) as client:
        response = client.get("/openapi.json")

    assert response.status_code == 200
    assert "/health" in response.json()["paths"]


def test_create_app_returns_a_fresh_instance() -> None:
    assert main.create_app() is not main.create_app()


# --- shutdown ---------------------------------------------------------------


def test_stdin_eof_stops_the_server() -> None:
    """The app being closed or killed closes the pipe; the sidecar must notice."""
    server = _server()
    assert not server.should_exit

    main._read_stdin(server, iter([]), SecretStore())

    assert server.should_exit


def test_shutdown_command_stops_the_server() -> None:
    server = _server()

    main._read_stdin(server, iter([f"{main.SHUTDOWN_COMMAND}\n"]), SecretStore())

    assert server.should_exit


def test_shutdown_command_tolerates_surrounding_whitespace() -> None:
    server = _server()

    main._read_stdin(server, iter([f"  {main.SHUTDOWN_COMMAND}  \r\n"]), SecretStore())

    assert server.should_exit


def test_unrelated_stdin_lines_do_not_stop_the_server_early() -> None:
    """Only the command or EOF ends it — not arbitrary chatter on the pipe.

    The first line is consumed as the secrets handshake, so the sentinel here
    is deliberately not in first position.
    """
    lines = iter(["hello\n", "ping\n", f"{main.SHUTDOWN_COMMAND}\n", "after\n"])
    server = _server()

    main._read_stdin(server, lines, SecretStore())

    assert server.should_exit
    # Stopped *at* the command, leaving the rest unread.
    assert next(lines) == "after\n"


def test_a_closed_stdin_stops_the_server_rather_than_raising() -> None:
    """A closed pipe raises on read; that means the parent is gone, not a bug."""
    stream = io.StringIO("irrelevant\n")
    stream.close()
    server = _server()

    main._read_stdin(server, stream, SecretStore())

    assert server.should_exit


# --- port resolution --------------------------------------------------------


def test_resolve_port_defaults_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(main.PORT_ENV_VAR, raising=False)

    assert main.resolve_port() == DEFAULT_BIND_PORT


def test_resolve_port_reads_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(main.PORT_ENV_VAR, "9123")

    assert main.resolve_port() == 9123


@pytest.mark.parametrize("raw", ["", "abc", "80", "0", "65536", "-1", "8787.5"])
def test_resolve_port_falls_back_on_unusable_values(raw: str) -> None:
    """Failing to start is worse than using the default port."""
    assert main.resolve_port(raw) == DEFAULT_BIND_PORT


@pytest.mark.parametrize("raw", ["1024", "8787", "65535"])
def test_resolve_port_accepts_the_valid_range(raw: str) -> None:
    assert main.resolve_port(raw) == int(raw)


# --- CORS -------------------------------------------------------------------
#
# The webview does not share an origin with the sidecar, so without these
# headers every request from the UI succeeds at the socket level and is then
# discarded by the browser. That failure looks exactly like the sidecar being
# down, which is why it survived a passing HTTP smoke test: curl and
# Invoke-WebRequest do not enforce CORS, and a webview does.


@pytest.mark.parametrize("origin", config.ALLOWED_ORIGINS)
def test_allowed_origins_get_cors_headers(origin: str) -> None:
    with TestClient(main.create_app()) as client:
        response = client.get("/health", headers={"Origin": origin})

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin


@pytest.mark.parametrize("origin", config.ALLOWED_ORIGINS)
def test_preflight_is_answered_for_allowed_origins(origin: str) -> None:
    with TestClient(main.create_app()) as client:
        response = client.options(
            "/health",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin


@pytest.mark.parametrize(
    "origin",
    [
        "http://evil.example",
        "https://example.com",
        "http://127.0.0.1:9999",
        "http://localhost:3000",
    ],
)
def test_unknown_origins_get_no_cors_headers(origin: str) -> None:
    """The allowlist must stay an allowlist — never a wildcard."""
    with TestClient(main.create_app()) as client:
        response = client.get("/health", headers={"Origin": origin})

    assert "access-control-allow-origin" not in response.headers


def test_the_windows_tauri_origin_is_allowed() -> None:
    """The specific origin whose absence broke the packaged app."""
    assert "http://tauri.localhost" in config.ALLOWED_ORIGINS


def test_origins_are_never_wildcarded() -> None:
    assert "*" not in config.ALLOWED_ORIGINS
