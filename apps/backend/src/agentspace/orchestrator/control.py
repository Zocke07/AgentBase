"""The control vocabulary an agent uses to end its turn or delegate.

**These are deliberately not Phase 6 tools, and they do not live in `tools/`.**
§1 constraint 5 is absolute: every filesystem, shell and network tool call
passes the approval gate, and that gate is Phase 6. Shipping `read_file` here
to give the loop something to call would create exactly the ungated path the
constraint forbids, and building the `Tool` protocol now would pre-empt the
sandbox and risk model that Phase 6 owns.

So this module offers the model only calls that *touch nothing*: they end an
agent's turn, hand work to another agent, or ask for a worker to exist. Each
one produces events and changes orchestration state, and nothing else.

**The control vocabulary is not subject to `allowed_tools`.** §5 Phase 5 says
an empty allowlist "means the agent can reason and hand off but touches
nothing" — so `handoff` survives an empty list by name, and `finish` must, or
an agent could never end its turn. What the allowlist governs is the *tool
catalogue* in :mod:`agentspace.tools.catalogue`. Which control calls a given
agent has is decided by what it *is*: a worker gets `finish` and `handoff`, a
supervisor also gets `spawn_agent`, and a worker that calls `spawn_agent`
anyway is refused (see :meth:`agentspace.orchestrator.agent.Agent._permit`).

The schemas are hand-written JSON Schema because that is what all three
providers take (see :class:`~agentspace.providers.base.ToolSpec`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from agentspace.providers.base import ToolSpec

if TYPE_CHECKING:
    from collections.abc import Iterable

    from agentspace.tools.catalogue import ToolDeclaration

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

#: **Phase 5 changed this tool's shape.** In Phase 4 the supervisor invented a
#: worker by supplying a name and a role, which meant an agent's identity was
#: whatever a model happened to type. §5 Phase 5 makes agents editable data, so
#: the supervisor now *chooses from a roster* the user controls: `agent` names
#: a row in `agent_defs`, and the role, system prompt, model and tool allowlist
#: all come from that row rather than from the model's imagination.
#:
#: The roster itself is listed in the supervisor's system prompt rather than in
#: this description, because it differs per run — see
#: :func:`agentspace.orchestrator.supervisor.supervisor_prompt`.
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

#: What a worker agent may call, before its definition's `allowed_tools` are
#: added to it.
WORKER_TOOLS: Final[list[ToolSpec]] = [FINISH, HANDOFF]

#: What the supervisor may call. It delegates rather than doing the work, and
#: it has no `allowed_tools` of its own: the supervisor is orchestration, not a
#: roster entry, so it never reaches the tool catalogue at all.
SUPERVISOR_TOOLS: Final[list[ToolSpec]] = [SPAWN_AGENT, FINISH]

#: The control calls each kind of agent legitimately has.
#:
#: Kept as names, separate from the `ToolSpec` lists above, on purpose: the
#: lists decide what a model is *shown*, these decide what it may *do*. A model
#: can name a tool it was never shown, so the two have to be independently
#: stated or "we did not offer it" quietly becomes the only thing stopping it.
WORKER_CONTROL_NAMES: Final[frozenset[str]] = frozenset({FINISH.name, HANDOFF.name})
SUPERVISOR_CONTROL_NAMES: Final[frozenset[str]] = WORKER_CONTROL_NAMES | {SPAWN_AGENT.name}


def catalogue_specs(declarations: Iterable[ToolDeclaration]) -> list[ToolSpec]:
    """Offer catalogue tools to a model as `ToolSpec`s.

    **The input schema is deliberately open.** A real schema for `write_file`
    would have to name its arguments, and those are defined by the `Tool`
    protocol Phase 6 owns — inventing them here would bake in a guess that
    phase then has to unpick, which §5 says not to do. Nothing executes these
    calls in Phase 5, so no argument shape is relied upon: an agent permitted a
    catalogue tool that calls it is told the tool is not available yet, and the
    arguments it sent are recorded in `tool.requested` exactly as given.

    Phase 6 replaces this function with one that reads each tool's real schema.
    """
    return [
        ToolSpec(
            name=declaration.name,
            description=declaration.description,
            input_schema={"type": "object", "additionalProperties": True},
        )
        for declaration in declarations
    ]
