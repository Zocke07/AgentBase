"""The one place that knows how to start a run.

`POST /runs` and the chat channels call the same object, so a dependency
added to `execute_run` is added here once. The prologue exists for one
reason: `channel.inbound` has to be the first event of a run, and appending
it after :meth:`RunLauncher.launch` returns would race the orchestrator task.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any

from agentspace.orchestrator import execute_run
from agentspace.store.spaces import DEFAULT_SPACE_ID, SpaceArchivedError
from agentspace.tools.sandbox import Sandbox

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
    from agentspace.store.spaces import Space, SpaceStore
    from agentspace.tools.runtime import ToolRuntime

__all__ = ["RunLauncher"]


@dataclass(slots=True)
class RunLauncher:
    """Creates a run row and hands it to the orchestrator in the background.

    Returns as soon as the row exists; every caller watches the run over the log.
    """

    store: EventStore
    settings: SettingsStore
    agents: AgentDefStore
    ledger: BudgetLedger
    secrets: SecretStore
    runtime: ToolRuntime | None = None
    #: Where a run's space (rules, roster, folder) comes from. ``None`` runs
    #: everything under the app-wide rules with whatever sandbox `runtime` carries.
    spaces: SpaceStore | None = None
    #: Overrides the configured provider for every agent; tests pass a scripted
    #: one, and `execute_run` still wraps it in the budget guard.
    provider: Provider | None = None
    #: Strong references to in-flight tasks, since `asyncio` holds only weak ones.
    tasks: set[asyncio.Task[Any]] = field(default_factory=set)
    #: The runs in flight in this process, by id, so a cancel can reach them.
    live: dict[str, Run] = field(default_factory=dict)

    async def launch(
        self,
        goal: str,
        *,
        space_id: str | None = None,
        origin: RunOrigin = "ui",
        origin_ref: str | None = None,
        prologue: Callable[[RunRow], Awaitable[None]] | None = None,
    ) -> RunRow:
        """Create the run, run ``prologue`` against it, then start it.

        :param space_id: where the run happens. ``None`` is the default space.
        :param prologue: appended to the log before the orchestrator emits anything.
        :raises SpaceNotFoundError: for an id that is not a space.
        :raises SpaceArchivedError: an archived space starts no runs.
        """
        space = await self._resolve_space(space_id)
        run = await self.store.create_run(
            goal=goal,
            origin=origin,
            origin_ref=origin_ref,
            space_id=space.id if space is not None else DEFAULT_SPACE_ID,
        )

        if prologue is not None:
            await prologue(run)

        self.spawn(self._drive(run.id, goal, space))
        return run

    async def space_exists(self, space_id: str) -> bool | None:
        """Whether ``space_id`` can start a run; ``None`` with no space store to ask."""
        if self.spaces is None:
            return None
        space = await self.spaces.get(space_id)
        return space is not None and not space.archived

    async def _resolve_space(self, space_id: str | None) -> Space | None:
        if self.spaces is None:
            return None
        space = await self.spaces.require(
            space_id if space_id is not None else DEFAULT_SPACE_ID
        )
        if space.archived:
            raise SpaceArchivedError(space.name)
        return space

    def _runtime_for(self, space: Space | None) -> ToolRuntime | None:
        """The process-wide tools and gate, rooted at this space's folder.

        The sandbox is per run, so a write from space A into space B's folder
        is refused. The folder is created on first use.
        """
        if self.runtime is None or space is None or self.spaces is None:
            return self.runtime
        folder = self.spaces.folder_for(space.id)
        folder.mkdir(parents=True, exist_ok=True)
        return replace(self.runtime, sandbox=Sandbox(folder))

    def spawn(self, coroutine: Coroutine[Any, Any, None]) -> asyncio.Task[None]:
        """Run a coroutine in the background, keeping a strong reference."""
        task = asyncio.create_task(coroutine)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

    async def cancel(self, run_id: str, reason: str) -> bool:
        """Ask a live run to stop. False if no such run is live here.

        Cooperative: the run notices at its next deadline check and writes
        `run.cancelled` itself. An agent blocked on the gate is released.
        """
        run = self.live.get(run_id)
        if run is None:
            return False
        run.request_cancel(reason)
        if self.runtime is not None:
            await self.runtime.approvals.release_run(run_id)
        return True

    async def _drive(self, run_id: str, goal: str, space: Space | None) -> None:
        """Hand one run to the orchestrator, which writes every terminal event itself."""
        await execute_run(
            self.store,
            self.settings,
            self.agents,
            self.ledger,
            self.secrets,
            run_id,
            goal,
            runtime=self._runtime_for(space),
            provider=self.provider,
            live=self.live,
            space=space,
        )
