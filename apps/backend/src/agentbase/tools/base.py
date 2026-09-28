"""Tool protocol and its prepare-approve-execute lifecycle.

``prepare`` validates and resolves without side effects; the approval gate
then decides whether ``execute`` can run. :class:`Prepared` carries a summary
of the resolved call so the prompt matches execution.
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
    """Retryable malformed call; emitted as ``tool.error``, not a refusal."""


class ToolExecutionError(Exception):
    """Allowed, valid call that failed; emitted as ``tool.error``."""


@dataclass(frozen=True, slots=True)
class Prepared:
    """Validated, sandbox-checked call ready for approval and execution."""

    tool_name: str
    summary: str
    payload: dict[str, Any] = field(default_factory=dict)
    #: Model-supplied arguments, retained beside resolved payload for replay.
    raw_arguments: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class Tool(Protocol):
    """One thing an agent can do that reaches outside the orchestrator."""

    @property
    def name(self) -> str:
        """Name matching a :data:`~agentbase.tools.catalogue.CATALOGUE` entry."""

    @property
    def description(self) -> str:
        """What the model is told this tool does."""

    @property
    def risk(self) -> RiskLevel:
        """Call risk, read from the catalogue rather than redeclared."""

    @property
    def input_schema(self) -> dict[str, Any]:
        """JSON Schema for the arguments, as all three providers take it."""

    def prepare(self, arguments: dict[str, Any], sandbox: Sandbox) -> Prepared:
        """Validate and resolve a call without side effects.

        :raises ToolArgumentError: the call is malformed. Becomes `tool.error`.
        :raises agentbase.tools.sandbox.SandboxViolationError: out of bounds.
            Becomes `tool.denied`.
        :raises agentbase.tools.sandbox.UrlNotAllowedError: likewise, for a URL.
        """

    async def execute(self, prepared: Prepared, sandbox: Sandbox) -> str:
        """Execute a prepared, approved call and return text.

        :raises ToolExecutionError: the call was legitimate and failed anyway.
        """
