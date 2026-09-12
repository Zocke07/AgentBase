"""The Tool protocol: what a tool is, and the two stages every call goes through.

§5 Phase 6 opens with "`Tool` protocol with a declared `risk` level". The risk
level was declared in Phase 5 (:mod:`agentspace.tools.catalogue` has carried
the names and risks since the allowlist needed something to validate against),
so what this module adds is the executable half, and the shape of a call.

**A call happens in two stages, and the split is the security design.**

1. :meth:`Tool.prepare`: validate the arguments and resolve them against the
   :class:`~agentspace.tools.sandbox.Sandbox`. Touches nothing. Raises
   :class:`~agentspace.tools.sandbox.SandboxViolationError` for anything out of
   bounds.
2. :meth:`Tool.execute`: carry out the already-validated call.

Between them sits the approval gate. That ordering is §5 Phase 6's literal
requirement: "path traversal outside it is rejected **before the approval
prompt is even shown**", and it is not merely tidy: an approval dialog is a
question put to a human, and a question is only safe to ask if every answer is
survivable. Asking "may this agent write to `../../../etc/passwd`?" makes the
user's misclick into the vulnerability. So a call that cannot be allowed is
never offered as a choice.

:class:`Prepared` is what stage 1 produces and stage 2 consumes. It carries the
`summary` that the approval prompt shows, because the sentence a user reads has
to describe the call that will *actually run*: the resolved path, not the
string the model typed. A prompt rendered from raw arguments and an execution
driven by resolved ones are two different calls, and the gap between them is
where a confused-deputy bug lives.

**Why a protocol and not a base class with `execute` on it.** Nothing here
dispatches on type, and each tool's `execute` reads its own resolved payload -
so an ABC would buy inheritance nobody uses. :class:`Tool` is a
`runtime_checkable` Protocol so the registry can hold a heterogeneous tuple and
`mypy --strict` still checks each implementation against it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from agentspace.tools.catalogue import RiskLevel
    from agentspace.tools.sandbox import Sandbox

__all__ = [
    "Prepared",
    "Tool",
    "ToolArgumentError",
    "ToolExecutionError",
]


class ToolArgumentError(Exception):
    """The arguments are wrong in a way the agent could fix by trying again.

    Distinct from :class:`~agentspace.tools.sandbox.SandboxViolationError`,
    which is a refusal: a missing `path` is a malformed call and becomes
    `tool.error`, while a `path` pointing out of the workspace is a blocked one
    and becomes `tool.denied`. Collapsing the two would make the event log
    unable to distinguish a confused agent from a boundary being tested, which
    is the single most interesting distinction it can draw.
    """


class ToolExecutionError(Exception):
    """The call was allowed and correct, and still did not work.

    A missing file, a command that exited non-zero, a host that would not
    answer. Becomes `tool.error`: the agent is told and carries on, because a
    tool failing is an ordinary event in a run, not a reason to end one.
    """


@dataclass(frozen=True, slots=True)
class Prepared:
    """A validated, sandbox-checked call, ready for the gate and then for execution.

    ``summary`` is the human-legible sentence §5 Phase 6 requires (*Agent
    "researcher" wants to delete report.docx*), minus the agent name, which the
    gate supplies because a tool does not know who called it.

    ``payload`` holds the resolved arguments each tool's :meth:`Tool.execute`
    reads back. It is deliberately the tool's own shape rather than a common
    one: `write_file` resolved a path and kept its content, `http_get` resolved
    a URL, and forcing those into a shared structure would invent a vocabulary
    with one user per key.
    """

    tool_name: str
    summary: str
    payload: dict[str, Any] = field(default_factory=dict)
    #: The arguments as the model sent them, recorded in `tool.requested` and
    #: in the `approvals` row. Kept beside the resolved payload rather than
    #: replaced by it, so a replay can show what was asked as well as what was
    #: done: the two differing is exactly what a traversal attempt looks like.
    raw_arguments: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class Tool(Protocol):
    """One thing an agent can do that reaches outside the orchestrator."""

    @property
    def name(self) -> str:
        """Matches a :data:`agentspace.tools.catalogue.CATALOGUE` entry.

        The catalogue is the registry `allowed_tools` validates against, so a
        tool whose name is not in it can never appear on any allowlist and is
        therefore unreachable. A test pins the two lists together.
        """

    @property
    def description(self) -> str:
        """What the model is told this tool does."""

    @property
    def risk(self) -> RiskLevel:
        """How much damage this call can do: §5 Phase 6's `risk` level.

        Decides whether the approval gate stops to ask. Read from the
        catalogue rather than declared twice, so the level the agent editor
        shows next to a checkbox is the level the gate enforces.
        """

    @property
    def input_schema(self) -> dict[str, Any]:
        """JSON Schema for the arguments, as all three providers take it.

        This replaces Phase 5's deliberately-open
        :func:`agentspace.orchestrator.control.catalogue_specs` schema, which
        existed only because the argument shapes were this phase's to define.
        """

    def prepare(self, arguments: dict[str, Any], sandbox: Sandbox) -> Prepared:
        """Validate and resolve a call without performing any part of it.

        :raises ToolArgumentError: the call is malformed. Becomes `tool.error`.
        :raises agentspace.tools.sandbox.SandboxViolationError: the call is out
            of bounds. Becomes `tool.denied`, per §5 Phase 6's acceptance
            criterion.
        :raises agentspace.tools.sandbox.UrlNotAllowedError: likewise, for the
            one tool that takes a URL.
        """

    async def execute(self, prepared: Prepared, sandbox: Sandbox) -> str:
        """Carry out a call that has been prepared and approved.

        Returns what the agent observes: the tool result, as text, since that
        is what goes back into a model transcript.

        :raises ToolExecutionError: the call was legitimate and failed anyway.
        """
