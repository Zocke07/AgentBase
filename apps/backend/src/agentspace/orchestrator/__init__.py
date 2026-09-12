"""The orchestration loop, hand-written (§1 constraint 1).

:func:`execute_run` is the entry point: it resolves the run's limits, roster and
providers, drives the supervisor, and guarantees a terminal event whatever
happens. Assembling those pieces here rather than in `run.py` keeps `run.py`
ignorant of agents: a `Run` owns lifecycle and the event sequence, and does
not need to know what a supervisor is.

**Every exit writes a terminal event.** A run that stops without `run.completed`
or `run.failed` is unreadable from the log, and the log is the only thing the UI
gets (§2). The stream also relies on it: a client resuming past the head of a
finished run waits for a terminal event that never comes, which is the hang
`pytest-timeout` caught during Phase 2.
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
    clock: Callable[[], float] | None = None,
    live: MutableMapping[str, Run] | None = None,
    space: Space | None = None,
) -> None:
    """Drive one run from `run.started` to a terminal event.

    :param agents: the agent definitions. Read once, here, into a frozen
        registry: §5 Phase 5 requires that editing a definition mid-run leaves
        the in-flight run alone.
    :param provider: overrides the configured provider, for every agent. Tests
        pass a scripted one; nothing in the shipped app does. It is still
        wrapped by :class:`~agentspace.budget.ledger.BudgetedProvider`, so a
        test cannot accidentally prove the cap holds on a path that bypasses it.
    :param runtime: the tools, sandbox and approval gate workers execute
        through. ``None`` gives a run in which no catalogue tool can be called,
        which is what every test that only exercises orchestration wants, and
        is never what the application passes.
    :param clock: monotonic time source, injected so the wall-clock limit can
        be tested without a test that actually waits.
    :param live: where the :class:`Run` is registered for the duration of the
        run, so that `POST /runs/{id}/cancel` can reach it. Removed on the way
        out, whatever the outcome.
    :param space: the space the run happens in. Its rules are laid over the
        app-wide settings before anything reads them (the limits, the
        provider pool, the gate's policy), and its roster is the one the
        supervisor is offered. ``None`` runs under the app-wide rules with the
        default space's roster, which is what every orchestration test wants.
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
        await _execute(run, agents, ledger, secrets, workspace, runtime, client, provider)
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
        override=BudgetedProvider(provider, ledger, run_id) if provider is not None else None,
    )

    try:
        guarded = providers.default()
    except (UnknownProviderError, ProviderError) as exc:
        # A missing key or an unknown provider name is a configuration problem,
        # not a crash: it has to reach the user as a readable run failure.
        # A *definition's* own provider failing is different and is handled by
        # the supervisor, because one bad row should not end a working run.
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
        # `budget.exceeded` was already appended by the ledger; this is the
        # run's own terminal event, not a duplicate of it.
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
    """Freeze the workspace approval policy onto the run's tool runtime.

    The runtime is built once, at application start, and the policy is a
    setting the user can change at any moment, including in the middle of a
    run. Reading it live would hold a run to different rules at step 1 and step
    12, exactly as a live roster or a live `max_steps` would, so it is
    snapshotted here alongside :class:`~agentspace.orchestrator.limits.RunLimits`
    and the roster.

    The direction of the mistake matters: a policy *widened* mid-run would
    auto-approve a call the user had not pre-authorized when the run started,
    which is the gate silently loosening while work is in flight.
    """
    if runtime is None:
        return None
    return replace(runtime, workspace_auto_approve=tuple(workspace.auto_approve))


async def _finish(run: Run, outcome: StepOutcome) -> None:
    """Write the run's terminal event from how the supervisor actually stopped.

    **A supervisor that ran out of steps did not complete the run.** §4 has no
    `agent.failed`, so an agent out of steps *completes* with a reason, but
    that is a fact about the agent, not about the run. Treating the two as the
    same thing marks the run `completed` and hands the user a summary reading
    "supervisor stopped after 4 steps with no result": a terminal event that
    says the run worked when it did not, which is precisely the drift between
    the log and reality that §2 exists to prevent.

    A worker running out of steps is different and stays a completion: the
    supervisor still sees its partial result and can finish the goal around it.
    Only the supervisor giving up means the run gave up.

    Found by watching a local model hit the agent cap twice and then exhaust
    its steps: invisible against a scripted provider, which always finished.
    """
    if outcome.reason == "finished":
        await run.complete(outcome.result)
        return

    await run.fail(
        f"The supervisor stopped after {outcome.steps} steps without finishing "
        f"the task. Anything its workers produced is in this run's event log. "
        f"Raise 'max steps per agent' in settings to give it more room."
    )
