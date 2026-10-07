"""Hand-written orchestration loop (§1 constraint 1).

:func:`execute_run` resolves limits, roster, and providers; drives the
supervisor; and always writes a terminal event. Without one, log replay is
unreadable and waiting streams never end.
"""

from __future__ import annotations

import logging
import time
from dataclasses import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from agentbase.budget.ledger import BudgetedProvider, BudgetExceededError
from agentbase.events.types import EventType
from agentbase.knowledge.manager import MemoryManager
from agentbase.orchestrator.agent import Agent, AgentSpec, StepOutcome
from agentbase.orchestrator.clock import started_note
from agentbase.orchestrator.limits import RunLimits
from agentbase.orchestrator.registry import AgentRegistry, ProviderPool
from agentbase.orchestrator.run import (
    UNATTENDED_ORIGINS,
    Mailbox,
    Run,
    RunCancelledError,
    RunCostExceededError,
    RunDeadlineExceededError,
)
from agentbase.orchestrator.supervisor import SUPERVISOR_NAME, Supervisor
from agentbase.providers.base import ProviderError
from agentbase.providers.factory import UnknownProviderError
from agentbase.store.schedules import LocalZone
from agentbase.store.spaces import DEFAULT_SPACE_ID
from agentbase.tools.catalogue import ToolPolicy

if TYPE_CHECKING:
    from collections.abc import Callable, MutableMapping
    from datetime import tzinfo

    import httpx2

    from agentbase.budget.ledger import BudgetLedger
    from agentbase.events.store import EventStore
    from agentbase.events.types import RunOrigin
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
    origin: RunOrigin = "ui",
    supervised: bool = False,
    zone: tzinfo | None = None,
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
    :param origin: where the run came from; an unattended origin makes its
        questions expire after ``unattended_question_seconds``.
    :param supervised: step through: every call asks a person, who is there
        to answer, and only the app's own refusals still answer by policy.
    :param zone: local time zone for the start time agents are told; the
        machine's own by default.
    """
    workspace = await settings.get()
    if space is not None:
        workspace = space.apply_to(workspace)
    if max_run_seconds is not None:
        workspace = workspace.model_copy(update={"max_run_seconds": max_run_seconds})
    if supervised:
        # Narrowing only: every yes becomes a question, every no stays.
        workspace = workspace.model_copy(
            update={
                "auto_approve": [],
                "tool_policies": {
                    tool: policy
                    for tool, policy in workspace.tool_policies.items()
                    if policy is ToolPolicy.DENY
                },
            }
        )
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

    # The recorded start, so the time agents see matches the run's own record.
    row = await store.get_run(run_id)
    started = row.created_at if row is not None else datetime.now(UTC)
    time_note = started_note(started, zone if zone is not None else LocalZone())

    question_seconds = (
        workspace.unattended_question_seconds
        if origin in UNATTENDED_ORIGINS and not supervised
        else None
    )
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
        origin=origin,
        question_seconds=question_seconds,
        approval=_approval_record(workspace, origin, question_seconds, supervised=supervised),
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
            time_note,
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
    time_note: str,
) -> None:
    """Execute a run after registering it as live."""
    run_id = run.id
    goal = run.goal
    limits = run.limits

    await run.start()

    registry = await AgentRegistry.load(
        agents,
        limits,
        space_id=run.space.id if run.space is not None else DEFAULT_SPACE_ID,
        time_note=time_note,
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
        time_note=time_note,
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
        await _finish(
            run,
            outcome,
            knowledge,
            guarded,
            memory_management=workspace.memory_management,
        )


def _approval_record(
    workspace: WorkspaceSettings,
    origin: RunOrigin,
    question_seconds: int | None,
    *,
    supervised: bool,
) -> dict[str, Any]:
    """The app-wide and space policy this run acts under, for ``run.started``.

    It is the same snapshot the gate is given, so replay can say why a call
    ran without asking. A definition may narrow it further per agent.
    """
    return {
        "levels": [str(level) for level in workspace.auto_approve],
        "tool_policies": {
            tool: str(policy) for tool, policy in sorted(workspace.tool_policies.items())
        },
        "hosts": list(workspace.auto_approve_hosts),
        "question_seconds": question_seconds,
        "supervised": supervised,
        "origin": origin,
    }


def _with_workspace_policy(
    runtime: ToolRuntime | None, workspace: WorkspaceSettings
) -> ToolRuntime | None:
    """Snapshot workspace approval policy onto run tool runtime.

    Like limits and roster, prevent mid-run widening from loosening the gate.
    """
    if runtime is None:
        return None
    policies = dict(workspace.tool_policies)
    if workspace.memory_management == "off":
        policies["propose_memory"] = ToolPolicy.DENY
    return replace(
        runtime,
        workspace_auto_approve=tuple(workspace.auto_approve),
        workspace_tool_policies=policies,
        workspace_auto_approve_hosts=tuple(workspace.auto_approve_hosts),
    )


async def _finish(
    run: Run,
    outcome: StepOutcome,
    knowledge: KnowledgeStore | None = None,
    provider: Provider | None = None,
    *,
    memory_management: str = "review",
) -> None:
    """Write terminal event based on supervisor outcome.

    A step-limited supervisor *completes* as an agent (§4 has no
    ``agent.failed``) but fails the run without the goal answer. A worker limit
    differs: supervisor may finish around it.
    """
    if outcome.reason == "finished":
        memory_path = None
        if knowledge is not None and memory_management != "off":
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
            if memory_management == "automatic" and provider is not None:
                try:
                    await MemoryManager(knowledge).manage(space_id, provider, run)
                except Exception as exc:
                    # Saved context is secondary to the task the person asked
                    # for. Leave generated notes proposed and make the failure
                    # visible without changing the successful run outcome.
                    logger.exception("could not manage saved context for run %s", run.id)
                    await run.emit(
                        EventType.LLM_ERROR,
                        {
                            "purpose": "saved_context",
                            "error": (
                                "Saved context could not be managed automatically. "
                                f"It remains in Needs attention: {exc}"
                            ),
                        },
                    )
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
