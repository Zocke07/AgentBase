"""The orchestration loop, hand-written (§1 constraint 1).

:func:`execute_run` resolves the run's limits, roster and providers, drives
the supervisor, and guarantees a terminal event whatever happens: a run that
stops without one is unreadable from the log, and a stream waiting on it
never ends.
"""

from __future__ import annotations

import logging
import time
from dataclasses import replace
from typing import TYPE_CHECKING

from agentspace.budget.ledger import BudgetedProvider, BudgetExceededError
from agentspace.events.types import EventType
from agentspace.orchestrator.agent import Agent, AgentSpec, StepOutcome
from agentspace.orchestrator.limits import RunLimits
from agentspace.orchestrator.registry import AgentRegistry, ProviderPool
from agentspace.orchestrator.run import (
    Mailbox,
    Run,
    RunCancelledError,
    RunDeadlineExceededError,
)
from agentspace.orchestrator.supervisor import SUPERVISOR_NAME, Supervisor
from agentspace.providers.base import ProviderError
from agentspace.providers.factory import UnknownProviderError
from agentspace.store.spaces import DEFAULT_SPACE_ID

if TYPE_CHECKING:
    from collections.abc import Callable, MutableMapping

    import httpx2

    from agentspace.budget.ledger import BudgetLedger
    from agentspace.events.store import EventStore
    from agentspace.providers.base import Provider
    from agentspace.providers.chatgpt import ChatGPTInferenceRuntime
    from agentspace.secrets import SecretStore
    from agentspace.store.agents import AgentDefStore
    from agentspace.store.settings import SettingsStore, WorkspaceSettings
    from agentspace.store.spaces import Space
    from agentspace.tools.runtime import ToolRuntime

__all__ = [
    "SUPERVISOR_NAME",
    "Agent",
    "AgentRegistry",
    "AgentSpec",
    "Mailbox",
    "ProviderPool",
    "Run",
    "RunLimits",
    "StepOutcome",
    "Supervisor",
    "execute_run",
]

logger = logging.getLogger("agentspace.orchestrator")


async def execute_run(
    store: EventStore,
    settings: SettingsStore,
    agents: AgentDefStore,
    ledger: BudgetLedger,
    secrets: SecretStore,
    run_id: str,
    goal: str,
    *,
    runtime: ToolRuntime | None = None,
    client: httpx2.AsyncClient | None = None,
    provider: Provider | None = None,
    chatgpt_runtime: ChatGPTInferenceRuntime | None = None,
    clock: Callable[[], float] | None = None,
    live: MutableMapping[str, Run] | None = None,
    space: Space | None = None,
) -> None:
    """Drive one run from `run.started` to a terminal event.

    :param agents: the definitions, read once into a frozen registry.
    :param provider: overrides the configured provider for every agent (tests
        pass a scripted one); still wrapped in the budget guard.
    :param runtime: the tools, sandbox and gate. ``None`` means no catalogue
        tool can be called, which is what orchestration tests want.
    :param clock: monotonic time source, injected so the wall-clock limit is testable.
    :param live: where the :class:`Run` is registered for its duration, so a
        cancel can reach it.
    :param space: the space the run happens in; its rules are laid over the
        app-wide settings before anything reads them. ``None`` runs under the
        app-wide rules with the default space's roster.
    """
    workspace = await settings.get()
    if space is not None:
        workspace = space.apply_to(workspace)
    limits = RunLimits.from_settings(workspace)

    run = Run(
        store=store,
        id=run_id,
        goal=goal,
        limits=limits,
        clock=clock if clock is not None else time.monotonic,
        space=space,
    )

    if live is not None:
        live[run_id] = run
    try:
        await _execute(
            run,
            agents,
            ledger,
            secrets,
            workspace,
            runtime,
            client,
            provider,
            chatgpt_runtime,
        )
    finally:
        if live is not None:
            live.pop(run_id, None)


async def _execute(
    run: Run,
    agents: AgentDefStore,
    ledger: BudgetLedger,
    secrets: SecretStore,
    workspace: WorkspaceSettings,
    runtime: ToolRuntime | None,
    client: httpx2.AsyncClient | None,
    provider: Provider | None,
    chatgpt_runtime: ChatGPTInferenceRuntime | None,
) -> None:
    """`execute_run` proper, once the run is registered as live."""
    run_id = run.id
    goal = run.goal
    limits = run.limits

    await run.start()

    registry = await AgentRegistry.load(
        agents, limits, space_id=run.space.id if run.space is not None else DEFAULT_SPACE_ID
    )
    providers = ProviderPool(
        workspace,
        secrets,
        ledger,
        run_id,
        client,
        chatgpt_runtime,
        override=BudgetedProvider(provider, ledger, run_id) if provider is not None else None,
    )

    try:
        guarded = providers.default()
    except (UnknownProviderError, ProviderError) as exc:
        # A configuration problem, reported as a readable run failure. A
        # definition's own provider failing is the supervisor's to handle.
        await run.fail(str(exc))
        return

    mailbox = Mailbox(run)

    run.register_agent(SUPERVISOR_NAME)
    supervisor = Supervisor(
        run=run,
        mailbox=mailbox,
        provider=guarded,
        goal=goal,
        registry=registry,
        providers=providers,
        runtime=_with_workspace_policy(runtime, workspace),
    )
    await run.emit(
        EventType.AGENT_SPAWNED,
        {
            **supervisor.spec.as_payload(),
            "provider": guarded.name,
            "model": guarded.model,
        },
        agent_id=SUPERVISOR_NAME,
    )

    try:
        outcome = await supervisor.execute(goal)
    except RunCancelledError as exc:
        await run.cancel(exc.reason)
    except RunDeadlineExceededError as exc:
        await run.fail(exc.reason)
    except BudgetExceededError as exc:
        # The ledger already appended `budget.exceeded`; this is the terminal event.
        await run.fail(exc.reason)
    except ProviderError as exc:
        await run.fail(str(exc))
    except Exception as exc:
        logger.exception("run %s failed", run_id)
        await run.fail(f"The run stopped unexpectedly: {exc}")
    else:
        await _finish(run, outcome)


def _with_workspace_policy(
    runtime: ToolRuntime | None, workspace: WorkspaceSettings
) -> ToolRuntime | None:
    """Snapshot the workspace approval policy onto the run's tool runtime.

    Like the limits and the roster: a policy widened mid-run would loosen the
    gate while work is in flight.
    """
    if runtime is None:
        return None
    return replace(runtime, workspace_auto_approve=tuple(workspace.auto_approve))


async def _finish(run: Run, outcome: StepOutcome) -> None:
    """Write the run's terminal event from how the supervisor actually stopped.

    A supervisor out of steps *completes* as an agent (§4 has no
    `agent.failed`) but did not answer the goal, so the run fails. A worker
    out of steps is different: the supervisor can finish around it.
    """
    if outcome.reason == "finished":
        await run.complete(outcome.result)
        return

    await run.fail(
        f"The supervisor stopped after {outcome.steps} steps without finishing "
        f"the task. Anything its workers produced is in this run's event log. "
        f"Raise 'max steps per agent' in settings to give it more room."
    )
