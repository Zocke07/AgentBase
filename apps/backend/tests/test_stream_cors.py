"""CORS on the SSE endpoint.

This file exists because of the Phase 1 bug recorded in CLAUDE.md: the sidecar
answered a webview `fetch` perfectly, and the browser threw the response away
because no `Access-Control-Allow-Origin` header came back. A terminal client
proved nothing, because **curl and `Invoke-WebRequest` do not enforce CORS; a
webview does.** The `curl` run that satisfies §5 Phase 2's acceptance criterion
has exactly that blind spot, so the headers are asserted here instead.

`EventSource` adds a second trap that plain `fetch` does not have. The initial
connection is a simple GET and is not preflighted, but on reconnect the
browser adds `Last-Event-ID`, which is not a CORS-safelisted request header, so
the resume request *is* preflighted. A configuration that allows the origin but
not that header yields a stream which works once and then dies silently at the
first reconnect: the exact case Phase 2 is built to handle.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from agentspace import main
from agentspace.config import ALLOWED_ORIGINS

if TYPE_CHECKING:
    from collections.abc import Iterator

    from agentspace.config import AppPaths

#: The origin the *packaged* Windows app runs from. The dev server origin is
#: not a substitute: it is same-site enough to hide a misconfiguration that
#: only bites after `tauri build`.
TAURI_WINDOWS_ORIGIN = "http://tauri.localhost"

#: The origin the packaged app runs from on macOS and Linux: a custom
#: scheme, not an `http` one. Pinned by name: the parametrised test below runs
#: for every allowlisted origin, so removing this one would only shrink that
#: parametrisation and stay green, and nothing on this machine can open the
#: macOS webview to notice.
TAURI_MACOS_ORIGIN = "tauri://localhost"


@pytest.fixture
def client(app_paths: AppPaths) -> Iterator[TestClient]:
    with TestClient(main.create_app(app_paths)) as test_client:
        yield test_client


def test_the_packaged_app_origin_is_allowlisted() -> None:
    assert TAURI_WINDOWS_ORIGIN in ALLOWED_ORIGINS


def test_the_macos_packaged_app_origin_is_allowlisted() -> None:
    assert TAURI_MACOS_ORIGIN in ALLOWED_ORIGINS


def test_the_macos_origin_survives_the_reconnect_preflight(client: TestClient) -> None:
    """Phase 1's CORS bug on Windows was found by installing the app and
    looking. Nobody can look on macOS from here, so the one thing a test can
    do is hold the two origins to the same contract: including the
    preflighted reconnect, which is where a stream that worked once dies."""
    run = client.post("/runs", json={"goal": "g"}).json()

    response = client.options(
        f"/runs/{run['id']}/events",
        headers={
            "Origin": TAURI_MACOS_ORIGIN,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "last-event-id",
        },
    )

    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == TAURI_MACOS_ORIGIN
    assert "last-event-id" in response.headers.get("access-control-allow-headers", "").lower()


def test_sse_response_carries_allow_origin_for_the_webview(client: TestClient) -> None:
    """Without this header the browser discards a perfectly good stream."""
    run = client.post("/debug/fake_run?step_ms=0").json()

    response = client.get(
        f"/runs/{run['id']}/events",
        headers={"Origin": TAURI_WINDOWS_ORIGIN},
    )

    assert response.headers.get("access-control-allow-origin") == TAURI_WINDOWS_ORIGIN


def test_preflight_permits_last_event_id_so_reconnects_work(client: TestClient) -> None:
    """The resume request is preflighted; the first connection is not.

    Getting this wrong produces a stream that works until the first reconnect
    and then fails silently, which is indistinguishable, from the UI, from a
    run that simply stopped emitting.
    """
    run = client.post("/runs", json={"goal": "g"}).json()

    response = client.options(
        f"/runs/{run['id']}/events",
        headers={
            "Origin": TAURI_WINDOWS_ORIGIN,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "last-event-id",
        },
    )

    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == TAURI_WINDOWS_ORIGIN
    allowed = response.headers.get("access-control-allow-headers", "").lower()
    assert "last-event-id" in allowed


def test_an_unlisted_origin_is_refused(client: TestClient) -> None:
    """The allowlist must stay an allowlist (CLAUDE.md, §1).

    A wildcard would let any page the user happens to have open read from their
    agent workspace: including the event log, which carries tool arguments and
    model output.
    """
    run = client.post("/debug/fake_run?step_ms=0").json()

    response = client.get(
        f"/runs/{run['id']}/events",
        headers={"Origin": "https://evil.example"},
    )

    assert response.headers.get("access-control-allow-origin") != "https://evil.example"
    assert response.headers.get("access-control-allow-origin") != "*"


@pytest.mark.parametrize("origin", ALLOWED_ORIGINS)
def test_every_allowlisted_origin_can_read_the_stream(client: TestClient, origin: str) -> None:
    run = client.post("/debug/fake_run?step_ms=0").json()

    response = client.get(f"/runs/{run['id']}/events", headers={"Origin": origin})

    assert response.headers.get("access-control-allow-origin") == origin
