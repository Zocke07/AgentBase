"""The control vocabulary an agent uses to end its turn or delegate.

**These are not tools, and they do not live in `tools/`.** §1 constraint 5 is
absolute: every filesystem, shell and network tool call passes the approval
gate. What is here passes no gate at all, and the reason it may not is the
reason it is here — these calls *touch nothing*. They end an agent's turn, hand
work to another agent, or ask for a worker to exist. Each produces events and
changes orchestration state, and nothing else.

That distinction is what keeps the constraint checkable rather than a matter of
trust. "Is this gated?" is not a judgement about a call site; it is the question
of whether the call is in this module or in
:mod:`agentspace.tools.builtin`, and the two sets are disjoint by construction —
:meth:`agentspace.orchestrator.agent.Agent._permit` reaches the gate for one and
never for the other. Adding anything here that reads a file or opens a socket
would create exactly the ungated path the constraint forbids, so it goes in
`tools/` instead, where the gate is unavoidable.

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


def catalogue_specs(tools: Iterable[Tool]) -> list[ToolSpec]:
    """Offer catalogue tools to a model as `ToolSpec`s.

    **Phase 6 made these schemas real.** Phase 5 offered
    ``{"type": "object", "additionalProperties": True}`` for every tool,
    because the argument shapes belonged to the `Tool` protocol this phase
    owns and guessing them would have been building ahead. Now each tool
    declares its own :attr:`~agentspace.tools.base.Tool.input_schema` and this
    reads it, so a model is told that `write_file` needs a `path` and a
    `content` instead of discovering it by being refused.

    Takes implementations rather than
    :class:`~agentspace.tools.catalogue.ToolDeclaration`s for the same reason:
    a declaration knows a tool's name and risk and has no schema to give.
    """
    return [
        ToolSpec(
            name=tool.name,
            description=tool.description,
            input_schema=tool.input_schema,
        )
        for tool in tools
    ]
