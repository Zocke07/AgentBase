"""Tool implementations, sandbox, and approval gate for an agent.

Keep them together so calls are both sandboxed and gated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from agentbase.tools.builtin import build_registry
from agentbase.tools.catalogue import ToolPolicy, effective_auto_approve

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from agentbase.tools.approval import ApprovalService
    from agentbase.tools.base import Tool
    from agentbase.tools.catalogue import RiskLevel
    from agentbase.tools.sandbox import Sandbox

__all__ = ["ToolRuntime"]


@dataclass(frozen=True, slots=True)
class ToolRuntime:
    """The tools an agent may execute, and everything needed to execute one."""

    tools: Mapping[str, Tool]
    sandbox: Sandbox
    approvals: ApprovalService
    #: Workspace pre-authorized risk levels, frozen at run start.
    workspace_auto_approve: tuple[RiskLevel, ...] = ()
    #: Frozen workspace per-tool answers; absence means ``ToolPolicy.ASK``.
    workspace_tool_policies: Mapping[str, ToolPolicy] = field(default_factory=dict)
    #: Frozen hosts a network call may reach without asking; ``*`` is any.
    workspace_auto_approve_hosts: tuple[str, ...] = ("*",)

    @classmethod
    def build(
        cls,
        sandbox: Sandbox,
        approvals: ApprovalService,
        workspace_auto_approve: Iterable[RiskLevel] = (),
        tools: Mapping[str, Tool] | None = None,
        workspace_tool_policies: Mapping[str, ToolPolicy] | None = None,
        workspace_auto_approve_hosts: Iterable[str] = ("*",),
    ) -> ToolRuntime:
        """Assemble a runtime over the built-in tools. ``tools`` is injectable for tests."""
        return cls(
            tools=build_registry() if tools is None else tools,
            sandbox=sandbox,
            approvals=approvals,
            workspace_auto_approve=tuple(workspace_auto_approve),
            workspace_tool_policies=dict(workspace_tool_policies or {}),
            workspace_auto_approve_hosts=tuple(workspace_auto_approve_hosts),
        )

    def get(self, name: str) -> Tool | None:
        return self.tools.get(name)

    def auto_approve_for(self, definition_levels: Iterable[RiskLevel]) -> frozenset[RiskLevel]:
        """Return risk levels this agent may run without a prompt.

        Empty definition policy inherits workspace levels; nonempty policy
        narrows them by intersection.
        """
        levels = tuple(definition_levels)
        if not levels:
            return frozenset(self.workspace_auto_approve)
        return effective_auto_approve(levels, self.workspace_auto_approve)

    def policy_for(self, tool: str, definition_levels: Iterable[RiskLevel]) -> ToolPolicy:
        """Return a tool policy after definition-level narrowing.

        Named levels turn an app-wide ``allow`` into ``ask`` unless they include
        the tool's risk; ``deny`` remains final.
        """
        policy = self.workspace_tool_policies.get(tool, ToolPolicy.ASK)
        if policy is not ToolPolicy.ALLOW:
            return policy
        levels = frozenset(definition_levels)
        implementation = self.tools.get(tool)
        if levels and (implementation is None or implementation.risk not in levels):
            return ToolPolicy.ASK
        return policy
