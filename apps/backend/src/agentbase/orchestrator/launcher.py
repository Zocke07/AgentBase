"""Single entry point for starting runs.

`POST /runs` and chat channels share this object, so ``execute_run``
dependencies appear once. ``prologue`` ensures ``channel.inbound`` is the
first event; appending after :meth:`RunLauncher.launch` returns races the
orchestrator task.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any

from agentbase.orchestrator import execute_run
from agentbase.store.spaces import DEFAULT_SPACE_ID, SpaceArchivedError
from agentbase.tools.sandbox import Sandbox

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Coroutine

    from agentbase.budget.ledger import BudgetLedger
    from agentbase.events.store import EventStore
    from agentbase.events.types import Run as RunRow
    from agentbase.events.types import RunOrigin
    from agentbase.knowledge.store import KnowledgeStore
    from agentbase.orchestrator.power import KeepAwake
    from agentbase.orchestrator.run import Run
    from agentbase.providers.base import Provider
    from agentbase.providers.chatgpt import ChatGPTInferenceRuntime
    from agentbase.secrets import SecretStore
    from agentbase.store.agents import AgentDefStore
    from agentbase.store.settings import SettingsStore
    from agentbase.store.spaces import Space, SpaceStore
    from agentbase.tools.runtime import ToolRuntime

__all__ = ["RunLauncher"]


@dataclass(slots=True)
class RunLauncher:
    """Create a run row and start its orchestrator in the background.

    Return once the row exists; callers follow the log.
    """

    store: EventStore
    settings: SettingsStore
    agents: AgentDefStore
    ledger: BudgetLedger
    secrets: SecretStore
    runtime: ToolRuntime | None = None
    #: Run space source (rules, roster, folder). ``None`` uses app-wide rules
    #: and the sandbox carried by ``runtime``.
    spaces: SpaceStore | None = None
    #: Overrides every configured provider; tests use scripted instances still
    #: wrapped by ``execute_run``'s budget guard.
    provider: Provider | None = None
    #: Process-wide ChatGPT OAuth/model transport under the API-key Provider contract.
    chatgpt_runtime: ChatGPTInferenceRuntime | None = None
    #: Strong in-flight task references; ``asyncio`` holds only weak ones.
    tasks: set[asyncio.Task[Any]] = field(default_factory=set)
    #: In-process runs by ID, so cancellation can reach them.
    live: dict[str, Run] = field(default_factory=dict)
    #: Local Markdown retrieval and durable run memories; optional for narrow tests.
    knowledge: KnowledgeStore | None = None
    #: Rows launched here whose orchestrator task remains active.
    driving: set[str] = field(default_factory=set)
    #: Cancellations that arrive before ``execute_run`` constructs live ``Run``.
    pending_cancellations: dict[str, str] = field(default_factory=dict)
    #: Told each run id once its orchestrator has written a terminal event;
    #: the scheduler uses it to start the stages that follow a scheduled run.
    on_finished: Callable[[str], Coroutine[Any, Any, None]] | None = None
    #: Holds the computer out of idle sleep while any run is going.
    keep_awake: KeepAwake | None = None

    async def launch(
        self,
        goal: str,
        *,
        space_id: str | None = None,
        origin: RunOrigin = "ui",
        origin_ref: str | None = None,
        title: str | None = None,
        excluded_citations: tuple[str, ...] = (),
        prologue: Callable[[RunRow], Awaitable[None]] | None = None,
        max_run_seconds: int | None = None,
        supervised: bool = False,
    ) -> RunRow:
        """Create a run, append ``prologue``, then start it.

        :param space_id: run location; ``None`` selects default space.
        :param title: an automation's name for the run; a person's run has none.
        :param prologue: append before any orchestrator event.
        :param max_run_seconds: schedule-specific limit over the space limit;
            ``None`` retains the space limit.
        :param supervised: ask before every call; only a person starts one.
        :raises SpaceNotFoundError: if ID is not a space.
        :raises SpaceArchivedError: archived spaces cannot start runs.
        """
        space = await self._resolve_space(space_id)
        run = await self.store.create_run(
            goal=goal,
            origin=origin,
            origin_ref=origin_ref,
            space_id=space.id if space is not None else DEFAULT_SPACE_ID,
            title=title,
        )

        if prologue is not None:
            await prologue(run)

        self.driving.add(run.id)
        if self.keep_awake is not None:
            self.keep_awake.hold()
        task = self.spawn(
            self._drive(
                run.id, goal, space, excluded_citations, max_run_seconds, origin, supervised
            )
        )
        run_id = run.id

        def finished(_task: asyncio.Task[None]) -> None:
            self.driving.discard(run_id)
            self.pending_cancellations.pop(run_id, None)
            if self.keep_awake is not None:
                self.keep_awake.release()
            if self.on_finished is not None:
                self.spawn(self.on_finished(run_id))

        task.add_done_callback(finished)
        return run

    async def space_exists(self, space_id: str) -> bool | None:
        """Return whether ``space_id`` can run; ``None`` if no space store exists."""
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
        """Return process-wide tools/gate rooted at this space folder.

        Per-run sandboxes refuse writes from space A into B. Create folder on first use.
        """
        if self.runtime is None or space is None or self.spaces is None:
            return self.runtime
        folder = self.spaces.folder_for(space.id)
        folder.mkdir(parents=True, exist_ok=True)
        return replace(self.runtime, sandbox=Sandbox(folder))

    def spawn(self, coroutine: Coroutine[Any, Any, None]) -> asyncio.Task[None]:
        """Run a coroutine in the background and keep a strong reference."""
        task = asyncio.create_task(coroutine)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

    async def cancel(self, run_id: str, reason: str) -> bool:
        """Request a live run stop; return false if it is not live here.

        Cooperative cancellation occurs at next deadline check and writes
        ``run.cancelled``; release agents blocked at the gate.
        """
        run = self.live.get(run_id)
        if run is None:
            if run_id not in self.driving:
                return False
            self.pending_cancellations.setdefault(run_id, reason)
            return True
        run.request_cancel(reason)
        if self.runtime is not None:
            await self.runtime.approvals.release_run(run_id)
        return True

    async def _drive(
        self,
        run_id: str,
        goal: str,
        space: Space | None,
        excluded_citations: tuple[str, ...],
        max_run_seconds: int | None,
        origin: RunOrigin,
        supervised: bool,
    ) -> None:
        """Hand a run to its orchestrator, which writes every terminal event."""
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
            chatgpt_runtime=self.chatgpt_runtime,
            live=self.live,
            space=space,
            knowledge=self.knowledge,
            excluded_citations=frozenset(excluded_citations),
            on_registered=self._apply_pending_cancel,
            max_run_seconds=max_run_seconds,
            origin=origin,
            supervised=supervised,
        )

    def _apply_pending_cancel(self, run: Run) -> None:
        reason = self.pending_cancellations.pop(run.id, None)
        if reason is not None:
            run.request_cancel(reason)
