"""What an agent needs in order to call a tool: the implementations, the sandbox and the gate.

One bundle rather than separate arguments, because a sandbox without a gate
is an ungated path to the disk and a gate without a sandbox asks the user to
judge paths that should have been refused. There is no way to assemble an
agent holding only some of them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from agentspace.tools.builtin import build_registry
from agentspace.tools.catalogue import effective_auto_approve

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from agentspace.tools.approval import ApprovalService
    from agentspace.tools.base import Tool
    from agentspace.tools.catalogue import RiskLevel
    from agentspace.tools.sandbox import Sandbox

__all__ = ["ToolRuntime"]


@dataclass(frozen=True, slots=True)
class ToolRuntime:
    """The tools an agent may execute, and everything needed to execute one."""

    tools: Mapping[str, Tool]
    sandbox: Sandbox
    approvals: ApprovalService
    #: The workspace's pre-authorized risk levels, frozen at run start like the
    #: rest of the run's rules.
    workspace_auto_approve: tuple[RiskLevel, ...] = ()

    @classmethod
    def build(
        cls,
        sandbox: Sandbox,
        approvals: ApprovalService,
        workspace_auto_approve: Iterable[RiskLevel] = (),
        tools: Mapping[str, Tool] | None = None,
    ) -> ToolRuntime:
        """Assemble a runtime over the built-in tools. ``tools`` is injectable for tests."""
        return cls(
            tools=build_registry() if tools is None else tools,
            sandbox=sandbox,
            approvals=approvals,
            workspace_auto_approve=tuple(workspace_auto_approve),
        )

    def get(self, name: str) -> Tool | None:
        return self.tools.get(name)

    def auto_approve_for(self, definition_levels: Iterable[RiskLevel]) -> frozenset[RiskLevel]:
        """What this agent may skip the dialog for.

        An empty `auto_approve` on a definition means "inherit", not "none":
        §4 defaults the column to `'[]'`, so a strict intersection would make
        the workspace policy inert. Under both readings the result is a subset
        of :attr:`workspace_auto_approve`, so no definition can widen it; a
        definition that names levels narrows through
        :func:`~agentspace.tools.catalogue.effective_auto_approve`. See
        CLAUDE.md before restoring the strict reading.
        """
        levels = tuple(definition_levels)
        if not levels:
            return frozenset(self.workspace_auto_approve)
        return effective_auto_approve(levels, self.workspace_auto_approve)
