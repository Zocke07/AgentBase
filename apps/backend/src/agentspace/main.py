"""FastAPI sidecar entry point.

Phase 1 is the packaging spike, so the HTTP surface here is deliberately tiny:
enough to prove a PyInstaller ``--onefile`` binary launched by Tauri as an
``externalBin`` actually serves requests to the webview. The orchestrator
arrives in Phase 4.

The part of this module that is *not* trivial is shutdown. With ``--onefile``,
PyInstaller's bootloader unpacks to a temp directory and execs the real Python
process as a child. Tauri only ever learns the bootloader's PID, so killing that
PID leaves the actual server running and holding port 8787 — the orphan-process
trap called out in BUILD_SPEC §5 Phase 1.

The fix is to not rely on signals at all. The shell holds the sidecar's stdin
open for the lifetime of the app. When the app quits — cleanly or by being
killed — that pipe closes, the reader thread sees EOF, and the server stops
itself from the inside. Writing the line ``shutdown`` does the same thing
deliberately, which is the path used on a clean quit.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
from typing import TYPE_CHECKING, Final

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agentspace.config import (
    ALLOWED_ORIGINS,
    BIND_HOST,
    DEFAULT_BIND_PORT,
    assert_loopback_only,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

__all__ = ["SHUTDOWN_COMMAND", "create_app", "resolve_port", "run"]

logger = logging.getLogger("agentspace")

#: Written to the sidecar's stdin by the Tauri shell to request a clean stop.
SHUTDOWN_COMMAND: Final[str] = "shutdown"

#: Environment variable the shell uses to pin the sidecar's port.
PORT_ENV_VAR: Final[str] = "AGENTSPACE_PORT"


def create_app() -> FastAPI:
    """Build the ASGI application.

    A factory rather than a module-level singleton so tests can build an
    isolated instance, and so importing this module never starts anything.
    """
    app = FastAPI(
        title="AgentSpace sidecar",
        version="0.1.0",
        docs_url="/docs",
        openapi_url="/openapi.json",
    )

    # Without this the webview's fetch succeeds at the socket level and is then
    # discarded by the browser, which looks identical to the sidecar being down.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(ALLOWED_ORIGINS),
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Last-Event-ID"],
    )

    @app.get("/health")
    def health() -> dict[str, bool]:
        """Liveness probe. The shell polls this to decide the sidecar is up."""
        return {"ok": True}

    return app


def resolve_port(raw: str | None = None) -> int:
    """Resolve the port to bind, falling back to the default when unusable.

    The shell picks a free port and passes it in. A malformed or out-of-range
    value falls back rather than crashing: failing to start is a worse outcome
    than using the default port, and the shell discovers the real port by
    polling ``/health`` regardless.
    """
    if raw is None:
        raw = os.environ.get(PORT_ENV_VAR)
    if raw is None:
        return DEFAULT_BIND_PORT

    try:
        port = int(raw)
    except ValueError:
        logger.warning("ignoring non-numeric %s=%r", PORT_ENV_VAR, raw)
        return DEFAULT_BIND_PORT

    if not (1024 <= port <= 65535):
        logger.warning("ignoring out-of-range %s=%r", PORT_ENV_VAR, raw)
        return DEFAULT_BIND_PORT

    return port


def _stop_on_stdin_close(server: uvicorn.Server, stream: Iterator[str]) -> None:
    """Stop ``server`` when ``stream`` yields ``shutdown`` or reaches EOF.

    Both endings matter. EOF is the app being closed or killed; the explicit
    command is a clean quit. Either way the decision to stop is made inside this
    process, which is the only process that reliably knows it is the real server.
    """
    try:
        for line in stream:
            if line.strip() == SHUTDOWN_COMMAND:
                logger.info("shutdown requested over stdin")
                break
    except (OSError, ValueError):
        # stdin was closed underneath us — same meaning as EOF.
        logger.info("stdin closed unexpectedly; shutting down")
    else:
        logger.info("stdin reached EOF; shutting down")

    server.should_exit = True


def run() -> None:
    """Serve until stdin closes. The process entry point."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    assert_loopback_only(BIND_HOST)
    port = resolve_port()

    config = uvicorn.Config(
        app=create_app(),
        host=BIND_HOST,
        port=port,
        log_level="info",
        access_log=False,
    )
    server = uvicorn.Server(config)

    watcher = threading.Thread(
        target=_stop_on_stdin_close,
        args=(server, sys.stdin),
        name="stdin-watchdog",
        daemon=True,
    )
    watcher.start()

    server.run()


if __name__ == "__main__":
    run()
