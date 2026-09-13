"""What tools exist, and how dangerous each one is. Names and risk levels only.

The allowlist validator and the agent editor's checkboxes both read this, so
the level shown beside a checkbox is the level the gate enforces. A tool
reads its own risk from here rather than declaring it twice.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Iterable

__all__ = [
    "CATALOGUE",
    "RiskLevel",
    "ToolDeclaration",
    "effective_auto_approve",
    "is_registered",
    "lookup",
    "tool_names",
]


class RiskLevel(StrEnum):
    """How much damage a tool call can do. Policy is a *set* of levels, never a threshold."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True, slots=True)
class ToolDeclaration:
    """One tool's name, purpose and risk. No implementation, by design."""

    name: str
    description: str
    risk: RiskLevel


#: The five built-ins §5 Phase 6 names. A definition may only allow a tool
#: listed here. Reads inside the sandbox are low; anything that writes, or
#: that leaves the machine, is not.
CATALOGUE: Final[tuple[ToolDeclaration, ...]] = (
    ToolDeclaration(
        name="read_file",
        description="Read a file inside the workspace.",
        risk=RiskLevel.LOW,
    ),
    ToolDeclaration(
        name="list_dir",
        description="List the contents of a directory inside the workspace.",
        risk=RiskLevel.LOW,
    ),
    ToolDeclaration(
        name="write_file",
        description="Create or overwrite a file inside the workspace.",
        # Medium: confined to the workspace, so the worst case is lost work there.
        risk=RiskLevel.MEDIUM,
    ),
    ToolDeclaration(
        name="http_get",
        description="Fetch a URL over HTTP and return the response body.",
        # Medium despite being a read: it can carry the workspace off the machine.
        risk=RiskLevel.MEDIUM,
    ),
    ToolDeclaration(
        name="run_shell",
        description="Run a shell command in the workspace with no network access.",
        risk=RiskLevel.HIGH,
    ),
)

_BY_NAME: Final[dict[str, ToolDeclaration]] = {tool.name: tool for tool in CATALOGUE}


def tool_names() -> tuple[str, ...]:
    """Every registered tool name, in catalogue order."""
    return tuple(_BY_NAME)


def is_registered(name: str) -> bool:
    """Whether ``name`` resolves to a declared tool."""
    return name in _BY_NAME


def lookup(name: str) -> ToolDeclaration | None:
    return _BY_NAME.get(name)


def effective_auto_approve(
    requested: Iterable[RiskLevel],
    policy: Iterable[RiskLevel],
) -> frozenset[RiskLevel]:
    """Intersect a definition's `auto_approve` with the workspace policy.

    An intersection is the whole implementation: no value of ``requested``
    can add to ``policy``, which is §5 Phase 5's rule that a definition may
    only narrow what the policy permits.
    """
    return frozenset(requested) & frozenset(policy)
