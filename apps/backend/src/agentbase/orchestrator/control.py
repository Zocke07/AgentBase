"""Agent control vocabulary for ending turns and delegation.

These calls are not ``tools/`` tools: they end turns, hand off work, or spawn
workers without touching resources, so they bypass the gate. File/socket calls
belong in ``tools/``, where gating is unavoidable.

Control vocabulary ignores ``allowed_tools`` so empty allowlists still reason
and hand off. Agent kind decides held calls (workers lack ``spawn_agent``),
enforced by :meth:`Agent._permit`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from agentbase.providers.base import ToolSpec

if TYPE_CHECKING:
    from collections.abc import Iterable

    from agentbase.tools.base import Tool

__all__ = [
    "FINISH",
    "HANDOFF",
    "SPAWN_AGENT",
    "SUPERVISOR_CONTROL_NAMES",
    "SUPERVISOR_TOOLS",
    "WORKER_CONTROL_NAMES",
    "WORKER_TOOLS",
    "catalogue_specs",
]

FINISH: Final[ToolSpec] = ToolSpec(
    name="finish",
    description=(
        "End your turn. Call this when the task you were given is done, or when "
        "you have established that you cannot do it. This is the only way to "
        "complete your work: a message on its own does not end your turn."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "result": {
                "type": "string",
                "description": (
                    "What you found or produced, in full. This is the only thing "
                    "passed on to whoever delegated the task to you."
                ),
            }
        },
        "required": ["result"],
    },
)

HANDOFF: Final[ToolSpec] = ToolSpec(
    name="handoff",
    description=(
        "Hand the remaining work to another agent that already exists in this "
        "run. Use this when the next step is outside what you were asked to do."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "to": {
                "type": "string",
                "description": "The name of the agent to hand off to.",
            },
            "task": {
                "type": "string",
                "description": "What that agent should do, stated as a task.",
            },
        },
        "required": ["to", "task"],
    },
)

#: ``agent`` names an ``agent_defs`` row; role, prompt, model, and allowlist
#: come from it, never model input. Roster lives in per-run supervisor prompt.
SPAWN_AGENT: Final[ToolSpec] = ToolSpec(
    name="spawn_agent",
    description=(
        "Put one of your available agents to work on a subtask. The agent runs "
        "until it finishes and its result is returned to you. Choose the agent "
        "whose role best fits the subtask; spawn one per distinct piece of work, "
        "and do not spawn one for something you can answer yourself. You may use "
        "the same agent more than once for genuinely separate subtasks."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "agent": {
                "type": "string",
                "description": (
                    "The name of the agent to use. Must be one of the agents "
                    "listed as available to you."
                ),
            },
            "task": {
                "type": "string",
                "description": "The subtask this agent should carry out.",
            },
        },
        "required": ["agent", "task"],
    },
)

#: Worker controls before definition ``allowed_tools`` are added.
WORKER_TOOLS: Final[list[ToolSpec]] = [FINISH, HANDOFF]

#: Supervisor controls; it has no ``allowed_tools`` or catalogue access.
SUPERVISOR_TOOLS: Final[list[ToolSpec]] = [SPAWN_AGENT, FINISH]

#: Control names held by each agent kind. Unlike ``ToolSpec`` lists that show
#: models options, these enforce what may run.
WORKER_CONTROL_NAMES: Final[frozenset[str]] = frozenset({FINISH.name, HANDOFF.name})
SUPERVISOR_CONTROL_NAMES: Final[frozenset[str]] = WORKER_CONTROL_NAMES | {SPAWN_AGENT.name}


def catalogue_specs(tools: Iterable[Tool]) -> list[ToolSpec]:
    """Expose catalogue tools as ``ToolSpec`` values using their input schemas."""
    return [
        ToolSpec(
            name=tool.name,
            description=tool.description,
            input_schema=tool.input_schema,
        )
        for tool in tools
    ]
