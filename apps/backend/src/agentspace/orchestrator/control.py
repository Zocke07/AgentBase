"""The control vocabulary an agent uses to end its turn or delegate.

**These are deliberately not Phase 6 tools, and they do not live in `tools/`.**
§1 constraint 5 is absolute: every filesystem, shell and network tool call
passes the approval gate, and that gate is Phase 6. Shipping `read_file` here
to give the loop something to call would create exactly the ungated path the
constraint forbids, and building the `Tool` protocol now would pre-empt the
sandbox and risk model that Phase 6 owns.

So Phase 4 offers the model only calls that *touch nothing*: they end an
agent's turn, hand work to another agent, or ask for a worker to exist. Each
one produces events and changes orchestration state, and nothing else. When
Phase 6 adds real tools they slot into the same `tool.requested` →
`tool.called` → `tool.result` sequence with the approval events inserted
between the first two.

The schemas are hand-written JSON Schema because that is what all three
providers take (see :class:`~agentspace.providers.base.ToolSpec`).
"""

from __future__ import annotations

from typing import Final

from agentspace.providers.base import ToolSpec

__all__ = [
    "FINISH",
    "HANDOFF",
    "SPAWN_AGENT",
    "SUPERVISOR_TOOLS",
    "WORKER_TOOLS",
]

FINISH: Final[ToolSpec] = ToolSpec(
    name="finish",
    description=(
        "End your turn. Call this when the task you were given is done, or when "
        "you have established that you cannot do it. This is the only way to "
        "complete your work — a message on its own does not end your turn."
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

SPAWN_AGENT: Final[ToolSpec] = ToolSpec(
    name="spawn_agent",
    description=(
        "Create a worker agent and give it a subtask. It runs until it finishes "
        "and its result is returned to you. Spawn one worker per distinct piece "
        "of work; do not spawn a worker for something you can answer yourself."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": (
                    "A short lowercase identifier for the worker, e.g. "
                    "'researcher'. Must be unique within this run."
                ),
            },
            "role": {
                "type": "string",
                "description": "One line describing what this worker is for.",
            },
            "task": {
                "type": "string",
                "description": "The subtask this worker should carry out.",
            },
        },
        "required": ["name", "role", "task"],
    },
)

#: What a worker agent may call.
WORKER_TOOLS: Final[list[ToolSpec]] = [FINISH, HANDOFF]

#: What the supervisor may call. It delegates rather than doing the work.
SUPERVISOR_TOOLS: Final[list[ToolSpec]] = [SPAWN_AGENT, FINISH]
