"""FastAPI sidecar entry point.

Shutdown never relies on signals. With PyInstaller's ``--onefile`` the PID the
shell holds is the bootloader's, not the server's, so killing it orphans the
server on port 8787. Instead the shell holds stdin open for the life of the
app: EOF (a close or a kill) and the line ``shutdown`` (a clean quit) both make
the reader thread stop the server from inside the process that is the server.

stdin also carries the API keys, as one JSON line written right after spawn.
`argv` is readable by any process (§1 constraint 4); stdin is a private pipe.
The handshake is the first line and is JSON, the sentinel is a bare word, and
one reader thread consumes both, so a launch that sends no handshake still
starts and still stops.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import threading
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Final

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from agentspace import __version__
from agentspace.api.agents import router as agents_router
from agentspace.api.approvals import router as approvals_router
from agentspace.api.auth import router as auth_router
from agentspace.api.channels import router as channels_router
from agentspace.api.knowledge import router as knowledge_router
from agentspace.api.runs import router as runs_router
from agentspace.api.settings import router as settings_router
from agentspace.api.spaces import router as spaces_router
from agentspace.budget.ledger import BudgetLedger
from agentspace.channels.service import ChannelDeps, ChannelService
from agentspace.config import (
    ALLOWED_ORIGINS,
    BIND_HOST,
    DEFAULT_BIND_PORT,
    AppPaths,
    adopt_legacy_workspace,
    assert_loopback_only,
    resolve_app_paths,
)
from agentspace.events.bus import EventBus
from agentspace.events.store import EventStore
from agentspace.knowledge.store import KnowledgeStore
from agentspace.orchestrator.launcher import RunLauncher
from agentspace.providers.chatgpt import ChatGPTRuntime, CodexAppServerRuntime
from agentspace.providers.codex_runtime import CodexRuntimeInstaller
from agentspace.secrets import SecretStore, parse_secrets_line
from agentspace.store.agents import AgentDefStore
from agentspace.store.db import Database
from agentspace.store.settings import SettingsStore
from agentspace.store.spaces import DEFAULT_SPACE_ID, SpaceStore
from agentspace.tools.approval import ApprovalService, ApprovalStore
from agentspace.tools.runtime import ToolRuntime
from agentspace.tools.sandbox import Sandbox

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator

__all__ = ["SHUTDOWN_COMMAND", "create_app", "resolve_port", "run"]

logger = logging.getLogger("agentspace")

#: Written to the sidecar's stdin by the Tauri shell to request a clean stop.
SHUTDOWN_COMMAND: Final[str] = "shutdown"

#: Environment variable the shell uses to pin the sidecar's port.
PORT_ENV_VAR: Final[str] = "AGENTSPACE_PORT"

#: Environment variable carrying the shell's tag for this launch, echoed by
#: `/health` so the shell can tell its own sidecar from a stranger on the port.
INSTANCE_ENV_VAR: Final[str] = "AGENTSPACE_INSTANCE"


class HealthResponse(BaseModel):
    """What `/health` says. The shell polls it to decide the sidecar is up."""

    ok: bool
    #: The tag the shell launched this process with, or ``None`` for a sidecar
    #: run by hand. Whatever holds the fixed port answers `/health`; this is
    #: how the shell tells its own from a leftover dev sidecar.
    instance: str | None


def create_app(
    paths: AppPaths | None = None,
    secrets: SecretStore | None = None,
    instance: str | None = None,
    chatgpt_runtime: ChatGPTRuntime | None = None,
) -> FastAPI:
    """Build the ASGI application.

    A factory so tests can build an isolated instance and importing this
    module starts nothing.

    :param paths: explicit data locations. Omitted, the directory is resolved
        the way the shipped app resolves it: ``AGENTSPACE_DATA_DIR``, then the
        OS app-data dir.
    :param secrets: the API keys delivered over stdin; the reader thread
        writes into the same instance.
    :param instance: the shell's tag for this launch, echoed by `/health`.
    """
    resolved = paths if paths is not None else resolve_app_paths()
    secret_store = secrets if secrets is not None else SecretStore()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """Own the database handle for the process's lifetime.

        Closed on the way out so the SQLite file is not left locked, which on
        Windows blocks the installer from replacing it.
        """
        resolved.ensure_exists()

        database = Database(resolved.db_path)
        database.connect()
        logger.info("database ready at %s (schema v%d)", database.path, database.schema_version)

        app.state.paths = resolved
        app.state.db = database
        app.state.bus = EventBus()
        app.state.store = EventStore(database, app.state.bus)
        app.state.background_tasks = set()
        app.state.secrets = secret_store
        app.state.settings = SettingsStore(database)
        app.state.agents = AgentDefStore(database, app.state.settings)
        app.state.ledger = BudgetLedger(database, app.state.settings, app.state.store)
        app.state.chatgpt_runtime = chatgpt_runtime or CodexAppServerRuntime(
            resolved.data_dir / "codex",
            installer=CodexRuntimeInstaller(resolved.data_dir / "codex-runtime"),
        )

        approval_store = ApprovalStore(database)
        app.state.approvals = ApprovalService(approval_store, app.state.store)
        app.state.spaces = SpaceStore(database, resolved.spaces_dir)
        app.state.knowledge = KnowledgeStore(app.state.spaces)
        # The pre-spaces workspace folder becomes the default space's, once;
        # migration 006's SQL cannot move a directory.
        default_folder = app.state.spaces.folder_for(DEFAULT_SPACE_ID)
        if adopt_legacy_workspace(resolved, default_folder):
            logger.info("moved the workspace folder to %s", default_folder)
        default_folder.mkdir(parents=True, exist_ok=True)
        # The tools and the gate are process-wide; the launcher rebinds the
        # sandbox root to the run's own space per run.
        app.state.tool_runtime = ToolRuntime.build(Sandbox(default_folder), app.state.approvals)

        # One object knows how to start a run; the HTTP endpoint and the
        # channels all use it.
        app.state.launcher = RunLauncher(
            store=app.state.store,
            settings=app.state.settings,
            agents=app.state.agents,
            ledger=app.state.ledger,
            secrets=secret_store,
            runtime=app.state.tool_runtime,
            spaces=app.state.spaces,
            chatgpt_runtime=app.state.chatgpt_runtime,
            tasks=app.state.background_tasks,
            knowledge=app.state.knowledge,
        )

        # A pending approval's waiter died with the process that created it;
        # left alone it would show as a live question about a dead run.
        orphaned = await approval_store.expire_orphaned_pending()
        if orphaned:
            logger.info("expired %d approval(s) left pending by a previous run", orphaned)

        # Likewise every run the last process left unfinished: nothing will
        # ever append its terminal event. After the approval sweep, so the log
        # reads in the order it happened: question expired, run failed.
        interrupted = await app.state.store.fail_orphaned_runs(
            "The app closed while this run was in progress, so it did not finish."
        )
        if interrupted:
            logger.info(
                "failed %d run(s) left unfinished by a previous process", len(interrupted)
            )

        # After the sweep, so a channel cannot surface a stale question as live.
        app.state.channels = ChannelService(
            ChannelDeps(
                store=app.state.store,
                bus=app.state.bus,
                settings=app.state.settings,
                approvals=app.state.approvals,
                launcher=app.state.launcher,
            ),
            secret_store,
        )
        await app.state.channels.start()

        try:
            yield
        finally:
            # Channels first: an adapter outliving the database would report
            # against a closed handle.
            await app.state.channels.aclose()
            for task in tuple(app.state.background_tasks):
                task.cancel()
            if app.state.background_tasks:
                await asyncio.gather(*app.state.background_tasks, return_exceptions=True)
            await app.state.chatgpt_runtime.aclose()
            database.close()

    app = FastAPI(
        title="AgentSpace sidecar",
        version=__version__,
        docs_url="/docs",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # Without CORS the webview's fetch succeeds and the browser discards the
    # body, which looks identical to the sidecar being down.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(ALLOWED_ORIGINS),
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Last-Event-ID"],
    )

    @app.get("/health")
    def health() -> HealthResponse:
        """Liveness probe, carrying the launch tag so the shell knows it is us."""
        return HealthResponse(ok=True, instance=instance)

    app.include_router(agents_router)
    app.include_router(approvals_router)
    app.include_router(auth_router)
    app.include_router(channels_router)
    app.include_router(knowledge_router)
    app.include_router(runs_router)
    app.include_router(settings_router)
    app.include_router(spaces_router)

    return app


def resolve_port(raw: str | None = None) -> int:
    """Resolve the port to bind. A malformed or out-of-range value falls back to the default."""
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


def _read_stdin(
    server: uvicorn.Server,
    stream: Iterator[str],
    secrets: SecretStore,
) -> None:
    """Consume the secrets handshake, then watch for shutdown.

    The first line is the key handshake; every later line is watched for the
    sentinel, and EOF stops the process either way. On a thread rather than
    at startup so a launch that sends no handshake still binds its port.
    """
    handshake_consumed = False

    try:
        for line in stream:
            if line.strip() == SHUTDOWN_COMMAND:
                logger.info("shutdown requested over stdin")
                break

            if not handshake_consumed:
                handshake_consumed = True
                # Never raises and never logs the line: a malformed handshake
                # must not crash the only thread that can stop this process.
                secrets.load(parse_secrets_line(line))
                continue
    except (OSError, ValueError):
        # stdin was closed underneath us, same meaning as EOF.
        logger.info("stdin closed unexpectedly; shutting down")
    else:
        logger.info("stdin reached EOF; shutting down")

    server.should_exit = True


def resolve_instance() -> str | None:
    """The shell's tag for this launch, or ``None`` when there is no shell.

    Empty is ``None``.
    """
    return os.environ.get(INSTANCE_ENV_VAR) or None


def run() -> None:
    """Serve until stdin closes. The process entry point."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    assert_loopback_only(BIND_HOST)
    port = resolve_port()
    instance = resolve_instance()
    if instance is not None:
        logger.info("launched as instance %s", instance)

    secrets = SecretStore()

    config = uvicorn.Config(
        app=create_app(secrets=secrets, instance=instance),
        host=BIND_HOST,
        port=port,
        log_level="info",
        access_log=False,
    )
    server = uvicorn.Server(config)

    watcher = threading.Thread(
        target=_read_stdin,
        args=(server, sys.stdin, secrets),
        name="stdin-reader",
        daemon=True,
    )
    watcher.start()

    server.run()


if __name__ == "__main__":
    run()
