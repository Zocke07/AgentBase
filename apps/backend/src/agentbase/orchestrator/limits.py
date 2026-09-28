"""Hard run limits (§5 Phase 4).

Resolve once at start and record in ``run.started``. ``max_steps_per_agent``
ends an agent with ``agent.completed`` (§4 has no ``agent.failed``);
``max_run_seconds`` ends a run with ``run.failed``; ``max_agents_per_run``
refuses only the spawn via ``tool.error`` so the supervisor can continue.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from agentbase.store.settings import WorkspaceSettings

__all__ = [
    "DEFAULT_MAX_AGENTS_PER_RUN",
    "DEFAULT_MAX_RUN_COST_MICROS",
    "DEFAULT_MAX_RUN_SECONDS",
    "DEFAULT_MAX_STEPS_PER_AGENT",
    "RunLimits",
]

#: Matches the `agent_defs.max_steps` default in §4.
DEFAULT_MAX_STEPS_PER_AGENT: Final[int] = 20

#: Supervisor plus workers; low enough to catch spawn loops within seconds.
DEFAULT_MAX_AGENTS_PER_RUN: Final[int] = 5

#: Ten minutes: prevents unattended overnight budget burn.
DEFAULT_MAX_RUN_SECONDS: Final[int] = 600

#: Two dollars in micros: per-run ceiling alongside monthly cap; 0 disables it.
DEFAULT_MAX_RUN_COST_MICROS: Final[int] = 2_000_000


@dataclass(frozen=True, slots=True)
class RunLimits:
    """Run ceilings fixed at start; mid-run setting edits affect the next run."""

    max_steps_per_agent: int = DEFAULT_MAX_STEPS_PER_AGENT
    max_agents_per_run: int = DEFAULT_MAX_AGENTS_PER_RUN
    max_run_seconds: int = DEFAULT_MAX_RUN_SECONDS
    #: Micros; 0 leaves monthly cap as the sole ceiling.
    max_run_cost_micros: int = DEFAULT_MAX_RUN_COST_MICROS

    @classmethod
    def from_settings(cls, settings: WorkspaceSettings) -> RunLimits:
        return cls(
            max_steps_per_agent=settings.max_steps_per_agent,
            max_agents_per_run=settings.max_agents_per_run,
            max_run_seconds=settings.max_run_seconds,
            max_run_cost_micros=settings.max_run_cost_micros,
        )

    def as_payload(self) -> dict[str, Any]:
        """Build the ``run.started`` payload."""
        return {
            "max_steps_per_agent": self.max_steps_per_agent,
            "max_agents_per_run": self.max_agents_per_run,
            "max_run_seconds": self.max_run_seconds,
            "max_run_cost_micros": self.max_run_cost_micros,
        }
