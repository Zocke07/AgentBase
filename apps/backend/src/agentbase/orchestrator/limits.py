"""The hard limits a run cannot exceed (§5 Phase 4).

Resolved once at run start and written into `run.started`, so the log says
what rules a run was held to. ``max_steps_per_agent`` ends the *agent* with
`agent.completed` (§4 has no `agent.failed`); ``max_run_seconds`` ends the
run with `run.failed`; ``max_agents_per_run`` ends nothing: the spawn is
refused through a `tool.error` and the supervisor carries on, since killing a
run for asking for one worker too many trades real work for strictness.
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

#: A supervisor plus workers: low enough that a spawn loop is caught in seconds.
DEFAULT_MAX_AGENTS_PER_RUN: Final[int] = 5

#: Ten minutes: so an unattended run cannot burn a month's budget overnight.
DEFAULT_MAX_RUN_SECONDS: Final[int] = 600

#: Two dollars, in micros: what one run may spend before it is stopped. The
#: monthly cap bounds the month; this bounds the one run that goes wrong. 0
#: turns it off.
DEFAULT_MAX_RUN_COST_MICROS: Final[int] = 2_000_000


@dataclass(frozen=True, slots=True)
class RunLimits:
    """The ceilings one run is held to, fixed at the moment it starts.

    A setting edited mid-run applies to the next run.
    """

    max_steps_per_agent: int = DEFAULT_MAX_STEPS_PER_AGENT
    max_agents_per_run: int = DEFAULT_MAX_AGENTS_PER_RUN
    max_run_seconds: int = DEFAULT_MAX_RUN_SECONDS
    #: In micros; 0 means the monthly cap is the only ceiling.
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
        """The shape written into `run.started`."""
        return {
            "max_steps_per_agent": self.max_steps_per_agent,
            "max_agents_per_run": self.max_agents_per_run,
            "max_run_seconds": self.max_run_seconds,
            "max_run_cost_micros": self.max_run_cost_micros,
        }
