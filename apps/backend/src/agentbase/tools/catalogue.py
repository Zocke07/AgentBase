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
    from collections.abc import Iterable, Mapping

__all__ = [
    "CATALOGUE",
    "RiskLevel",
    "ToolDeclaration",
    "ToolPolicy",
    "effective_auto_approve",
    "effective_tool_policies",
    "is_registered",
    "lookup",
    "stricter",
    "tool_names",
]


class RiskLevel(StrEnum):
    """How much damage a tool call can do. Policy is a *set* of levels, never a threshold."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ToolPolicy(StrEnum):
    """What the gate does with a call to one tool, by name, before its risk level is read.

    ``ASK`` is the default and means the risk-level rule decides; ``ALLOW``
    runs the call without asking; ``DENY`` refuses it without asking. A tool
    absent from a policy is ``ASK``.
    """

    ASK = "ask"
    ALLOW = "allow"
    DENY = "deny"


#: Strictness, for narrowing: a space may move a tool along this order, never back.
_STRICTNESS: Final[dict[ToolPolicy, int]] = {
    ToolPolicy.ALLOW: 0,
    ToolPolicy.ASK: 1,
    ToolPolicy.DENY: 2,
}


def stricter(left: ToolPolicy, right: ToolPolicy) -> ToolPolicy:
    """The stricter of two policies for one tool."""
    return left if _STRICTNESS[left] >= _STRICTNESS[right] else right


@dataclass(frozen=True, slots=True)
class ToolDeclaration:
    """One tool's name, purpose and risk. No implementation, by design."""

    name: str
    description: str
    risk: RiskLevel


#: The built-ins a definition may allow. A definition may only allow a tool
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
        name="search_knowledge",
        description=(
            "Search this space's Markdown knowledge and return relevant chunks with citations."
        ),
        risk=RiskLevel.LOW,
    ),
    ToolDeclaration(
        name="propose_memory",
        description=(
            "Propose a durable Markdown memory for the user's review; it is not "
            "retrieved until approved."
        ),
        risk=RiskLevel.MEDIUM,
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
        name="read_feed",
        description=(
            "Fetch an RSS or Atom URL and return bounded, complete entries with "
            "deterministic identifiers."
        ),
        # The same network boundary as http_get, with local parsing afterwards.
        risk=RiskLevel.MEDIUM,
    ),
    ToolDeclaration(
        name="run_shell",
        description=(
            "Run a shell command as your user, starting in the space folder, "
            "with a timeout. The command can access the network."
        ),
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


def effective_tool_policies(
    requested: Mapping[str, ToolPolicy],
    policy: Mapping[str, ToolPolicy],
) -> dict[str, ToolPolicy]:
    """Narrow the workspace's per-tool policies by a space's.

    Each tool ends up with the stricter of the two answers, so a space can
    turn an allowed tool into a question or a refusal and a question into a
    refusal, and can never widen what the app-wide policy permits. A tool
    neither names stays absent, which reads as ``ASK``.
    """
    merged = dict(policy)
    for tool, wanted in requested.items():
        merged[tool] = stricter(wanted, policy.get(tool, ToolPolicy.ASK))
    return merged


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
