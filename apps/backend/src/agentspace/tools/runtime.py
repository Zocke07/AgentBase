"""What an agent needs in order to actually call a tool.

Three things have to be in the same place at the moment a call is dispatched:
the tool implementations, the :class:`~agentspace.tools.sandbox.Sandbox` they
resolve against, and the :class:`~agentspace.tools.approval.ApprovalService`
that decides whether the call proceeds. :class:`ToolRuntime` is that bundle.

**Why a bundle rather than four constructor arguments on `Agent`.** They are
not independent: a sandbox without a gate is an ungated path to the filesystem
(§1 constraint 5), and a gate without a sandbox asks the user to adjudicate
paths the sandbox should have refused outright. Passing them as one value means
there is no way to assemble an agent that has some of them — the combination
that would look like it worked and be the vulnerability.

**§3 does not name this module**, in the same way it does not name
`orchestrator/limits.py` or `orchestrator/control.py`. It is additive: it holds
no policy of its own, only the wiring, and every rule it applies belongs to one
of the three things it carries.
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
    #: The workspace's pre-authorized risk levels, frozen at run start along
    #: with the rest of the run's rules. A policy read live would hold a run to
    #: different rules at step 1 and step 12 — the same reasoning that makes
    #: `RunLimits` and the agent roster snapshots.
    workspace_auto_approve: tuple[RiskLevel, ...] = ()

    @classmethod
    def build(
        cls,
        sandbox: Sandbox,
        approvals: ApprovalService,
        workspace_auto_approve: Iterable[RiskLevel] = (),
        tools: Mapping[str, Tool] | None = None,
    ) -> ToolRuntime:
        """Assemble a runtime over the built-in tools.

        ``tools`` is injectable so a test can supply a double; nothing in the
        shipped app passes it.
        """
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

        **An empty `auto_approve` on a definition means "inherit", not "none".**
        This is the one judgement call in the gate, and it is worth stating why
        it is not the obvious pure intersection.

        §4 defaults the column to `'[]'` and every seeded built-in carries that
        value. A strict intersection therefore makes the workspace policy inert:
        a user sets `auto_approve` to `["low"]` to let an overnight run proceed,
        every definition intersects it away to nothing, and the setting reports
        success while changing nothing — the exact shape this project has
        shipped once already (CLAUDE.md, Phase 4: "a setting that could not be
        set, and said it could") and which §5 Phase 6 rules out by asking for a
        policy that lets "overnight runs progress".

        **The security property is unchanged**, which is the part that matters.
        §5 Phase 5's note forbids a definition *escalating*: "it can never grant
        a risk level the workspace policy has not enabled". Under both readings
        the result is a subset of :attr:`workspace_auto_approve`, so no
        definition can add anything — the only difference is whether a
        definition that said nothing is read as declining or as not answering.
        A row that has never been edited has not declined.

        A definition that *does* name levels still narrows, through
        :func:`~agentspace.tools.catalogue.effective_auto_approve` — the pure
        intersection, kept as the single audited implementation of the rule that
        actually carries the security weight.
        """
        levels = tuple(definition_levels)
        if not levels:
            return frozenset(self.workspace_auto_approve)
        return effective_auto_approve(levels, self.workspace_auto_approve)
