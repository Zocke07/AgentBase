"""Hand-written orchestration loop (§1 constraint 1).

:func:`execute_run` resolves limits, roster, and providers; drives the
supervisor; and always writes a terminal event. Without one, log replay is
unreadable and waiting streams never end.
"""

from __future__ import annotations

import logging
import time
from dataclasses import replace
from typing import TYPE_CHECKING

from agentbase.budget.ledger import BudgetedProvider, BudgetExceededError
from agentbase.events.types import EventType
from agentbase.orchestrator.agent import Agent, AgentSpec, StepOutcome
from agentbase.orchestrator.limits import RunLimits
from agentbase.orchestrator.registry import AgentRegistry, ProviderPool
from agentbase.orchestrator.run import (
    Mailbox,
    Run,
    RunCancelledError,
    RunCostExceededError,
    RunDeadlineExceededError,
)
from agentbase.orchestrator.supervisor import SUPERVISOR_NAME, Supervisor
from agentbase.providers.base import ProviderError
from agentbase.providers.factory import UnknownProviderError
from agentbase.store.spaces import DEFAULT_SPACE_ID

if TYPE_CHECKING:
    from collections.abc import Callable, MutableMapping

    import httpx2

    from agentbase.budget.ledger import BudgetLedger
    from agentbase.events.store import EventStore
    from agentbase.knowledge.store import KnowledgeStore, SearchHit
    from agentbase.providers.base import Provider
    from agentbase.providers.chatgpt import ChatGPTInferenceRuntime
    from agentbase.secrets import SecretStore
    from agentbase.store.agents import AgentDefStore
    from agentbase.store.settings import SettingsStore, WorkspaceSettings
    from agentbase.store.spaces import Space
    from agentbase.tools.runtime import ToolRuntime

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

logger = logging.getLogger("agentbase.orchestrator")


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
    knowledge: KnowledgeStore | None = None,
    excluded_citations: frozenset[str] = frozenset(),
    on_registered: Callable[[Run], None] | None = None,
    max_run_seconds: int | None = None,
) -> None:
    """Drive a run from ``run.started`` to a terminal event.

    :param agents: definitions read once into a frozen registry.
    :param provider: override for every agent (tests use scripted providers),
        still protected by the budget guard.
    :param runtime: tools, sandbox, and gate. ``None`` disables catalogue
        tools for orchestration tests.
    :param clock: injectable monotonic source for wall-limit tests.
    :param live: mapping that registers the live run for cancellation.
    :param space: run space; apply its rules before reads. ``None`` uses
        app-wide rules and the default roster.
    :param max_run_seconds: schedule-specific limit over the space limit;
        other limits and policy remain unchanged.
    """
    workspace = await settings.get()
    if space is not None:
        workspace = space.apply_to(workspace)
    if max_run_seconds is not None:
        workspace = workspace.model_copy(update={"max_run_seconds": max_run_seconds})
    limits = RunLimits.from_settings(workspace)

    hits: tuple[SearchHit, ...] = ()
    if knowledge is not None and space is not None:
        try:
            hits = tuple(
                await knowledge.search(
                    space.id, goal, 6, excluded_citations=set(excluded_citations)
                )
            )
        except OSError:
            logger.exception("knowledge retrieval failed for run %s", run_id)
    knowledge_context = knowledge.format_context(hits) if knowledge is not None else ""

    run = Run(
        store=store,
        id=run_id,
        goal=goal,
        limits=limits,
        clock=clock if clock is not None else time.monotonic,
        space=space,
        knowledge=hits,
        knowledge_exclusions=tuple(sorted(excluded_citations)),
        spent_so_far=lambda: ledger.run_spent_micros(run_id),
    )

    if live is not None:
        live[run_id] = run
    if on_registered is not None:
        on_registered(run)
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
            knowledge,
            knowledge_context,
            excluded_citations,
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
    knowledge: KnowledgeStore | None,
    knowledge_context: str,
    excluded_citations: frozenset[str],
) -> None:
    """Execute a run after registering it as live."""
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
        # Report default-provider configuration failure; supervisor handles a
        # definition's own provider failure.
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
        knowledge=knowledge,
        space_id=run.space.id if run.space is not None else DEFAULT_SPACE_ID,
        knowledge_context=knowledge_context,
        excluded_citations=excluded_citations,
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
    except RunCostExceededError as exc:
        await run.fail(exc.reason)
    except BudgetExceededError as exc:
        # Ledger already emitted ``budget.exceeded``; now write terminal event.
        await run.fail(exc.reason)
    except ProviderError as exc:
        await run.fail(str(exc))
    except Exception as exc:
        logger.exception("run %s failed", run_id)
        await run.fail(f"The run stopped unexpectedly: {exc}")
    else:
        await _finish(run, outcome, knowledge)


def _with_workspace_policy(
    runtime: ToolRuntime | None, workspace: WorkspaceSettings
) -> ToolRuntime | None:
    """Snapshot workspace approval policy onto run tool runtime.

    Like limits and roster, prevent mid-run widening from loosening the gate.
    """
    if runtime is None:
        return None
    return replace(
        runtime,
        workspace_auto_approve=tuple(workspace.auto_approve),
        workspace_tool_policies=dict(workspace.tool_policies),
    )


async def _finish(
    run: Run, outcome: StepOutcome, knowledge: KnowledgeStore | None = None
) -> None:
    """Write terminal event based on supervisor outcome.

    A step-limited supervisor *completes* as an agent (§4 has no
    ``agent.failed``) but fails the run without the goal answer. A worker limit
    differs: supervisor may finish around it.
    """
    if outcome.reason == "finished":
        memory_path = None
        if knowledge is not None:
            space_id = run.space.id if run.space is not None else DEFAULT_SPACE_ID
            try:
                memory_path = await knowledge.save_run_memory(
                    space_id,
                    run_id=run.id,
                    goal=run.goal,
                    summary=outcome.result,
                    citations=[hit.citation for hit in run.knowledge],
                )
            except (OSError, ValueError):
                logger.exception("could not save memory for run %s", run.id)
        await run.complete(outcome.result, memory_path)
        return

    if outcome.reason == "stuck":
        # Result already names its loop; more steps would not help.
        await run.fail(
            f"{outcome.result} Anything its workers produced is in this run's event log."
        )
        return

    await run.fail(
        f"The supervisor stopped after {outcome.steps} steps without finishing "
        f"the task. Anything its workers produced is in this run's event log. "
        f"Raise 'max steps per agent' in settings to give it more room."
    )
