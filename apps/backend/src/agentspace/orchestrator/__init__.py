"""The orchestration loop, hand-written (§1 constraint 1).

:func:`execute_run` is the entry point: it resolves the run's limits and
provider, drives the supervisor, and guarantees a terminal event whatever
happens. Assembling those pieces here rather than in `run.py` keeps `run.py`
ignorant of agents — a `Run` owns lifecycle and the event sequence, and does
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
from typing import TYPE_CHECKING

from agentspace.budget.ledger import BudgetedProvider, BudgetExceededError
from agentspace.events.types import EventType
from agentspace.orchestrator.agent import Agent, AgentSpec, StepOutcome
from agentspace.orchestrator.limits import RunLimits
from agentspace.orchestrator.run import Mailbox, Run, RunDeadlineExceededError
from agentspace.orchestrator.supervisor import SUPERVISOR_NAME, Supervisor
from agentspace.providers.base import ProviderError
from agentspace.providers.factory import UnknownProviderError, build_provider

if TYPE_CHECKING:
    from collections.abc import Callable

    import httpx2

    from agentspace.budget.ledger import BudgetLedger
    from agentspace.events.store import EventStore
    from agentspace.providers.base import Provider
    from agentspace.secrets import SecretStore
    from agentspace.store.settings import SettingsStore

__all__ = [
    "SUPERVISOR_NAME",
    "Agent",
    "AgentSpec",
    "Mailbox",
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
    ledger: BudgetLedger,
    secrets: SecretStore,
    run_id: str,
    goal: str,
    *,
    client: httpx2.AsyncClient | None = None,
    provider: Provider | None = None,
    clock: Callable[[], float] | None = None,
) -> None:
    """Drive one run from `run.started` to a terminal event.

    :param provider: overrides the configured provider. Tests pass a scripted
        one; nothing in the shipped app does. It is still wrapped by
        :class:`~agentspace.budget.ledger.BudgetedProvider`, so a test cannot
        accidentally prove the cap holds on a path that bypasses it.
    :param clock: monotonic time source, injected so the wall-clock limit can
        be tested without a test that actually waits.
    """
    workspace = await settings.get()
    limits = RunLimits.from_settings(workspace)

    run = Run(
        store=store,
        id=run_id,
        goal=goal,
        limits=limits,
        clock=clock if clock is not None else time.monotonic,
    )

    await run.start()

    try:
        inner = provider if provider is not None else build_provider(workspace, secrets, client)
    except (UnknownProviderError, ProviderError) as exc:
        # A missing key or an unknown provider name is a configuration problem,
        # not a crash — it has to reach the user as a readable run failure.
        await run.fail(str(exc))
        return

    guarded = BudgetedProvider(inner, ledger, run_id)
    mailbox = Mailbox(run)

    run.register_agent(SUPERVISOR_NAME)
    await run.emit(
        EventType.AGENT_SPAWNED,
        {
            "role": "Plans the work and delegates it",
            "provider": guarded.name,
            "model": guarded.model,
        },
        agent_id=SUPERVISOR_NAME,
    )

    supervisor = Supervisor(run=run, mailbox=mailbox, provider=guarded, goal=goal)

    try:
        outcome = await supervisor.execute(goal)
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


async def _finish(run: Run, outcome: StepOutcome) -> None:
    """Write the run's terminal event from how the supervisor actually stopped.

    **A supervisor that ran out of steps did not complete the run.** §4 has no
    `agent.failed`, so an agent out of steps *completes* with a reason — but
    that is a fact about the agent, not about the run. Treating the two as the
    same thing marks the run `completed` and hands the user a summary reading
    "supervisor stopped after 4 steps with no result": a terminal event that
    says the run worked when it did not, which is precisely the drift between
    the log and reality that §2 exists to prevent.

    A worker running out of steps is different and stays a completion: the
    supervisor still sees its partial result and can finish the goal around it.
    Only the supervisor giving up means the run gave up.

    Found by watching a local model hit the agent cap twice and then exhaust
    its steps — invisible against a scripted provider, which always finished.
    """
    if outcome.reason == "finished":
        await run.complete(outcome.result)
        return

    await run.fail(
        f"The supervisor stopped after {outcome.steps} steps without finishing "
        f"the task. Anything its workers produced is in this run's event log. "
        f"Raise 'max steps per agent' in settings to give it more room."
    )
