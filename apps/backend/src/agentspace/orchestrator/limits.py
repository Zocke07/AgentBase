"""The hard limits a run cannot exceed.

§5 Phase 4: "Hard limits: max steps per agent, max agents per run, max
wall-clock per run. All configurable, all enforced, all emit a terminal event
when hit."

**Why a separate module rather than three integers passed around.** A limit
that is read from settings at the point of use is a limit that can be read
differently in two places, and the run has no record of which values it was
actually held to. :class:`RunLimits` is resolved once at run start and written
into the `run.started` payload, so the event log says what the rules were —
which matters when the answer to "why did this stop" has to come from the log
alone (§5 Phase 4, acceptance criterion).

**What each limit terminates.** The §4 event list is a closed contract, and it
constrains this more than it first appears:

* ``max_steps_per_agent`` ends the *agent*, with `agent.completed` carrying
  ``reason: "max_steps"``. There is no `agent.failed` in §4, so an agent that
  runs out of steps completes with a reason rather than failing.
* ``max_run_seconds`` ends the *run*, with `run.failed`.
* ``max_agents_per_run`` ends nothing. The spawn is refused and the supervisor
  is told so through a `tool.error`, leaving it to carry on with the workers it
  already has. Killing a run that is otherwise succeeding because its
  supervisor asked for one worker too many trades real work for strictness, and
  a supervisor that loops on retrying hits the step limit anyway.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from agentspace.store.settings import WorkspaceSettings

__all__ = [
    "DEFAULT_MAX_AGENTS_PER_RUN",
    "DEFAULT_MAX_RUN_SECONDS",
    "DEFAULT_MAX_STEPS_PER_AGENT",
    "RunLimits",
]

#: Matches the `agent_defs.max_steps` default in §4, so Phase 5's per-agent
#: value and this global ceiling start from the same number.
DEFAULT_MAX_STEPS_PER_AGENT: Final[int] = 20

#: A supervisor plus workers. Low enough that a spawn loop is caught in
#: seconds, high enough for the two-worker run §5 Phase 4 asks for.
DEFAULT_MAX_AGENTS_PER_RUN: Final[int] = 5

#: Ten minutes. The ceiling exists so an unattended run cannot burn a month's
#: budget overnight; it is not a latency target.
DEFAULT_MAX_RUN_SECONDS: Final[int] = 600


@dataclass(frozen=True, slots=True)
class RunLimits:
    """The ceilings one run is held to, fixed at the moment it starts.

    Frozen because a run must not be held to different rules at step 1 and step
    12 — a setting edited mid-run applies to the *next* run, the same way §5
    Phase 5 requires of agent definitions.
    """

    max_steps_per_agent: int = DEFAULT_MAX_STEPS_PER_AGENT
    max_agents_per_run: int = DEFAULT_MAX_AGENTS_PER_RUN
    max_run_seconds: int = DEFAULT_MAX_RUN_SECONDS

    @classmethod
    def from_settings(cls, settings: WorkspaceSettings) -> RunLimits:
        return cls(
            max_steps_per_agent=settings.max_steps_per_agent,
            max_agents_per_run=settings.max_agents_per_run,
            max_run_seconds=settings.max_run_seconds,
        )

    def as_payload(self) -> dict[str, Any]:
        """The shape written into `run.started`.

        The log is the only thing a replay gets to read, so the limits a run was
        actually held to have to be in it.
        """
        return {
            "max_steps_per_agent": self.max_steps_per_agent,
            "max_agents_per_run": self.max_agents_per_run,
            "max_run_seconds": self.max_run_seconds,
        }
