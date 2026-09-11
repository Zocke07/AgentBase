"""The one place that knows how to start a run.

Phase 4 put this inline in `POST /runs`, which was right while there was one
caller. Phase 8 adds two more — a Discord command and a Telegram command — and
this project has been bitten seven times by the same shape: a list of things
duplicated at two call sites, correct at both on the day it was written, and
silently divergent afterwards. Phase 1's CORS origins, Phase 2's named SSE
events, Phase 3's `*.sql` glob, Phase 4's settings fields, Phase 5's `max_steps`
default, Phase 6's `auto_approve`, Phase 7's `qualified_model`. Assembling
`execute_run`'s seven arguments in three places would be the eighth.

So a channel does not "also" start runs; it calls the same object the HTTP
endpoint calls, and a dependency added to `execute_run` is added here once.

**The prologue is not a hook for general use.** It exists because
`channel.inbound` has to be the first event of the run: §5 Phase 8 says an
adapter emits it, and a message that arrived *before* the run started must not
be recorded after `run.started`. Appending it from the caller after
:meth:`RunLauncher.launch` returns would race the orchestrator task, which is
already emitting. Running it before that task is created makes the ordering a
fact rather than a hope.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from agentspace.orchestrator import execute_run

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Coroutine

    from agentspace.budget.ledger import BudgetLedger
    from agentspace.events.store import EventStore
    from agentspace.events.types import Run as RunRow
    from agentspace.events.types import RunOrigin
    from agentspace.orchestrator.run import Run
    from agentspace.providers.base import Provider
    from agentspace.secrets import SecretStore
    from agentspace.store.agents import AgentDefStore
    from agentspace.store.settings import SettingsStore
    from agentspace.tools.runtime import ToolRuntime

__all__ = ["RunLauncher"]


@dataclass(slots=True)
class RunLauncher:
    """Creates a run row and hands it to the orchestrator in the background.

    Returns as soon as the row exists. A run takes minutes and every caller
    watches it over the event log, so waiting for completion would make the
    return value a second way to learn what the log already says — and would put
    a proxy's idle timeout, or Discord's three-second interaction deadline, in
    charge of when a run may end.
    """

    store: EventStore
    settings: SettingsStore
    agents: AgentDefStore
    ledger: BudgetLedger
    secrets: SecretStore
    runtime: ToolRuntime | None = None
    #: Overrides the configured provider for every agent. Tests pass a scripted
    #: one; nothing in the shipped app sets it, and `execute_run` still wraps it
    #: in the budget guard — so a test cannot accidentally prove the cap holds
    #: on a path that bypasses it.
    provider: Provider | None = None
    #: Strong references to in-flight work. `asyncio` holds only a weak
    #: reference to a bare task, so without this the loop may garbage-collect a
    #: run that is still going. Drained by the lifespan handler on shutdown.
    tasks: set[asyncio.Task[Any]] = field(default_factory=set)
    #: The runs in flight in this process, by id. `execute_run` registers
    #: each on entry and removes it on exit, so a cancel can reach a run that
    #: is actually going and nothing else.
    live: dict[str, Run] = field(default_factory=dict)

    async def launch(
        self,
        goal: str,
        *,
        origin: RunOrigin = "ui",
        origin_ref: str | None = None,
        prologue: Callable[[RunRow], Awaitable[None]] | None = None,
    ) -> RunRow:
        """Create the run, run ``prologue`` against it, then start it.

        :param prologue: appended to the log before the orchestrator emits
            anything, so a caller can guarantee its event is first. See the
            module docstring for why this is not a general-purpose hook.
        """
        run = await self.store.create_run(goal=goal, origin=origin, origin_ref=origin_ref)

        if prologue is not None:
            await prologue(run)

        self.spawn(self._drive(run.id, goal))
        return run

    def spawn(self, coroutine: Coroutine[Any, Any, None]) -> asyncio.Task[None]:
        """Run a coroutine in the background, keeping a strong reference."""
        task = asyncio.create_task(coroutine)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

    async def cancel(self, run_id: str, reason: str) -> bool:
        """Ask a live run to stop. False if no such run is live here.

        Cooperative: the run notices at its next deadline check, before its
        next model call, and writes `run.cancelled` itself — nothing here
        appends a terminal event, for the reason `_drive` gives. An agent
        blocked on the approval gate is released so it does not wait for the
        wall clock.
        """
        run = self.live.get(run_id)
        if run is None:
            return False
        run.request_cancel(reason)
        if self.runtime is not None:
            await self.runtime.approvals.release_run(run_id)
        return True

    async def _drive(self, run_id: str, goal: str) -> None:
        """Hand one run to the orchestrator.

        Every failure path inside `execute_run` writes its own terminal event,
        so nothing here does — and nothing here should, because a second opinion
        about how a run ended is exactly the drift §2 rules out.
        """
        await execute_run(
            self.store,
            self.settings,
            self.agents,
            self.ledger,
            self.secrets,
            run_id,
            goal,
            runtime=self.runtime,
            provider=self.provider,
            live=self.live,
        )
