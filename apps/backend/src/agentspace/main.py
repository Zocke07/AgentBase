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

**Phase 3 gives stdin a second job.** The shell writes one line of JSON holding
the API keys it read from the OS keychain, immediately after spawn, before
anything else. Keys must not travel as command-line arguments — `argv` is
readable by any process on the machine (§1 constraint 4) — and stdin is already
a private pipe between exactly these two processes.

The two uses share one stream without ambiguity: the handshake is the first
line and is JSON, the shutdown sentinel is the bare word ``shutdown``. Both are
consumed by the same reader thread, so a launch that never sends a secrets line
— ``python -m agentspace`` by hand — still starts and still shuts down cleanly.
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

from agentspace.api.agents import router as agents_router
from agentspace.api.approvals import router as approvals_router
from agentspace.api.channels import router as channels_router
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
from agentspace.orchestrator.launcher import RunLauncher
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
#: `/health`. Not a secret — a label, so the shell can tell the sidecar it
#: spawned from whatever else is listening on the fixed port.
INSTANCE_ENV_VAR: Final[str] = "AGENTSPACE_INSTANCE"


class HealthResponse(BaseModel):
    """What `/health` says. The shell polls it to decide the sidecar is up."""

    ok: bool
    #: The tag the shell launched this process with, or ``None`` for a sidecar
    #: run by hand. The port is fixed, so the process answering `/health` is
    #: whatever holds it — a previous copy of the app still shutting down, a
    #: dev sidecar in a terminal — and this is how the shell tells its own
    #: apart. The packaged app once attached to the dev sidecar and showed the
    #: dev data directory's runs with nothing anywhere saying so.
    instance: str | None


def create_app(
    paths: AppPaths | None = None,
    secrets: SecretStore | None = None,
    instance: str | None = None,
) -> FastAPI:
    """Build the ASGI application.

    A factory rather than a module-level singleton so tests can build an
    isolated instance, and so importing this module never starts anything.

    :param paths: explicit data locations, as a test supplies. When omitted the
        directory is resolved the way the shipped app resolves it — the Tauri
        shell's ``AGENTSPACE_DATA_DIR``, then the OS app-data dir.
    :param secrets: the API keys delivered over stdin. Passed in rather than
        constructed here because the stdin reader thread — which owns the other
        end of the handshake — must write into the same instance.
    :param instance: the shell's tag for this launch, echoed by `/health`.
    """
    resolved = paths if paths is not None else resolve_app_paths()
    secret_store = secrets if secrets is not None else SecretStore()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """Own the database handle for the process's lifetime.

        Opened here rather than at import so that importing this module still
        touches nothing, and closed on the way out so the SQLite file is not
        left locked — which on Windows blocks the installer from replacing it.
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

        approval_store = ApprovalStore(database)
        app.state.approvals = ApprovalService(approval_store, app.state.store)
        app.state.spaces = SpaceStore(database, resolved.spaces_dir)
        # The single workspace from before spaces becomes the default space's
        # folder, once. The SQL half of migration 006 cannot move a directory.
        default_folder = app.state.spaces.folder_for(DEFAULT_SPACE_ID)
        if adopt_legacy_workspace(resolved, default_folder):
            logger.info("moved the workspace folder to %s", default_folder)
        default_folder.mkdir(parents=True, exist_ok=True)
        # Built once over the default space's folder; the launcher rebinds the
        # sandbox to the run's own space per run. The tools and the gate are
        # process-wide, the root is not.
        app.state.tool_runtime = ToolRuntime.build(Sandbox(default_folder), app.state.approvals)

        # One object knows how to start a run, and every caller uses it — the
        # HTTP endpoint and both chat channels. See `orchestrator/launcher.py`
        # for why three copies of `execute_run`'s argument list would have been
        # the eighth instance of this project's recurring bug.
        app.state.launcher = RunLauncher(
            store=app.state.store,
            settings=app.state.settings,
            agents=app.state.agents,
            ledger=app.state.ledger,
            secrets=secret_store,
            runtime=app.state.tool_runtime,
            spaces=app.state.spaces,
            tasks=app.state.background_tasks,
        )

        # A pending approval's waiter was an `asyncio.Future` in whichever
        # process created it, so nothing survives a restart to answer these.
        # Left alone they would show up in the Phase 7 dialog as live questions
        # about runs that ended when the app last closed.
        orphaned = await approval_store.expire_orphaned_pending()
        if orphaned:
            logger.info("expired %d approval(s) left pending by a previous run", orphaned)

        # And the runs those approvals belonged to, along with every other run
        # the last process left unfinished. Their orchestrators were tasks in
        # that process; nothing will ever append their terminal event, so the
        # dashboard said "live" about runs dead since the app last closed.
        # After the approval sweep, so the log reads: question expired, run
        # failed — the order it happened in.
        interrupted = await app.state.store.fail_orphaned_runs(
            "The app closed while this run was in progress, so it did not finish."
        )
        if interrupted:
            logger.info(
                "failed %d run(s) left unfinished by a previous process", len(interrupted)
            )

        # Started after the approval sweep above, so a channel cannot surface a
        # question left over from the last process as though it were live.
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
            # Channels first: an adapter torn down after the database is closed
            # would try to report a run against a handle that is gone.
            await app.state.channels.aclose()
            for task in tuple(app.state.background_tasks):
                task.cancel()
            if app.state.background_tasks:
                await asyncio.gather(*app.state.background_tasks, return_exceptions=True)
            database.close()

    app = FastAPI(
        title="AgentSpace sidecar",
        version="0.1.0",
        docs_url="/docs",
        openapi_url="/openapi.json",
        lifespan=lifespan,
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
    def health() -> HealthResponse:
        """Liveness probe, carrying the launch tag so the shell knows it is us."""
        return HealthResponse(ok=True, instance=instance)

    app.include_router(agents_router)
    app.include_router(approvals_router)
    app.include_router(channels_router)
    app.include_router(runs_router)
    app.include_router(settings_router)
    app.include_router(spaces_router)

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


def _read_stdin(
    server: uvicorn.Server,
    stream: Iterator[str],
    secrets: SecretStore,
) -> None:
    """Consume the secrets handshake, then watch for shutdown.

    The first line is the API-key handshake (§1 constraint 4). Every line after
    it is watched for the shutdown sentinel, and EOF ends the process either
    way.

    Both endings matter. EOF is the app being closed or killed; the explicit
    command is a clean quit. Either way the decision to stop is made inside this
    process, which is the only process that reliably knows it is the real server.

    Running on this thread rather than blocking startup is deliberate: a launch
    that sends no handshake at all must still bind its port. See the module
    docstring.
    """
    handshake_consumed = False

    try:
        for line in stream:
            if line.strip() == SHUTDOWN_COMMAND:
                logger.info("shutdown requested over stdin")
                break

            if not handshake_consumed:
                handshake_consumed = True
                # `parse_secrets_line` never raises and never logs the line;
                # a malformed handshake yields nothing rather than crashing the
                # only thread that can stop this process.
                secrets.load(parse_secrets_line(line))
                continue
    except (OSError, ValueError):
        # stdin was closed underneath us — same meaning as EOF.
        logger.info("stdin closed unexpectedly; shutting down")
    else:
        logger.info("stdin reached EOF; shutting down")

    server.should_exit = True


def resolve_instance() -> str | None:
    """The shell's tag for this launch, or ``None`` when there is no shell.

    Empty is ``None``: a variable exported with nothing in it must not make
    every ``/health`` match an empty expectation.
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
