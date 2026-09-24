"""The Tool protocol: what a tool is, and the two stages every call goes through.

:meth:`Tool.prepare` validates and resolves against the sandbox while touching
nothing; :meth:`Tool.execute` carries out the already-validated call; the
approval gate sits between them. A call that cannot be allowed is therefore
never offered as a choice, because a question a user can answer wrongly is not
a boundary. :class:`Prepared` carries the summary the prompt shows, built
from the resolved call rather than the arguments the model typed, so the
sentence the user reads and the call that runs cannot disagree.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from agentbase.tools.catalogue import RiskLevel
    from agentbase.tools.sandbox import Sandbox

__all__ = [
    "Prepared",
    "Tool",
    "ToolArgumentError",
    "ToolExecutionError",
]


class ToolArgumentError(Exception):
    """A malformed call the agent could fix by retrying: `tool.error`, not a refusal."""


class ToolExecutionError(Exception):
    """The call was allowed and correct, and still did not work: `tool.error`, and the agent
    carries on.
    """


@dataclass(frozen=True, slots=True)
class Prepared:
    """A validated, sandbox-checked call, ready for the gate and then for execution.

    ``summary`` is the human-legible sentence minus the agent name, which the
    gate supplies. ``payload`` is each tool's own resolved shape.
    """

    tool_name: str
    summary: str
    payload: dict[str, Any] = field(default_factory=dict)
    #: The arguments as the model sent them, kept beside the resolved payload
    #: so a replay can show what was asked as well as what was done.
    raw_arguments: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class Tool(Protocol):
    """One thing an agent can do that reaches outside the orchestrator."""

    @property
    def name(self) -> str:
        """Matches a :data:`~agentbase.tools.catalogue.CATALOGUE` entry; a test pins the two
        lists.
        """

    @property
    def description(self) -> str:
        """What the model is told this tool does."""

    @property
    def risk(self) -> RiskLevel:
        """How much damage this call can do. Read from the catalogue, never declared twice."""

    @property
    def input_schema(self) -> dict[str, Any]:
        """JSON Schema for the arguments, as all three providers take it."""

    def prepare(self, arguments: dict[str, Any], sandbox: Sandbox) -> Prepared:
        """Validate and resolve a call without performing any part of it.

        :raises ToolArgumentError: the call is malformed. Becomes `tool.error`.
        :raises agentbase.tools.sandbox.SandboxViolationError: out of bounds.
            Becomes `tool.denied`.
        :raises agentbase.tools.sandbox.UrlNotAllowedError: likewise, for a URL.
        """

    async def execute(self, prepared: Prepared, sandbox: Sandbox) -> str:
        """Carry out a call that has been prepared and approved. Returns the result as text.

        :raises ToolExecutionError: the call was legitimate and failed anyway.
        """
