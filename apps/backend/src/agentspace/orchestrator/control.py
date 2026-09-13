"""The control vocabulary an agent uses to end its turn or delegate.

Not tools, and not in `tools/`: these calls touch nothing (they end a turn,
hand work over, or ask for a worker to exist), so they pass no gate, and
"is this gated?" is answered by which module a call lives in. Anything that
reads a file or opens a socket goes in `tools/`, where the gate is unavoidable.

The control vocabulary is not subject to `allowed_tools`: an empty allowlist
still reasons and hands off. Which control calls an agent has is decided by
what it is (a worker lacks `spawn_agent`), and enforced in `Agent._permit`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from agentspace.providers.base import ToolSpec

if TYPE_CHECKING:
    from collections.abc import Iterable

    from agentspace.tools.base import Tool

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

#: `agent` names a row in `agent_defs`; the role, prompt, model and allowlist
#: come from that row, never from the model. The roster is in the supervisor's
#: system prompt because it differs per run.
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

#: What a worker may call, before its definition's `allowed_tools` are added.
WORKER_TOOLS: Final[list[ToolSpec]] = [FINISH, HANDOFF]

#: What the supervisor may call. It has no `allowed_tools` and never reaches the catalogue.
SUPERVISOR_TOOLS: Final[list[ToolSpec]] = [SPAWN_AGENT, FINISH]

#: The control calls each kind of agent has. Names, separate from the
#: `ToolSpec` lists: those decide what a model is shown, these what it may do.
WORKER_CONTROL_NAMES: Final[frozenset[str]] = frozenset({FINISH.name, HANDOFF.name})
SUPERVISOR_CONTROL_NAMES: Final[frozenset[str]] = WORKER_CONTROL_NAMES | {SPAWN_AGENT.name}


def catalogue_specs(tools: Iterable[Tool]) -> list[ToolSpec]:
    """Offer catalogue tools to a model as `ToolSpec`s, from each tool's own `input_schema`."""
    return [
        ToolSpec(
            name=tool.name,
            description=tool.description,
            input_schema=tool.input_schema,
        )
        for tool in tools
    ]
