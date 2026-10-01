"""Tool declarations and risk levels.

Allowlist validation, editor controls, and tool implementations share this
catalogue, keeping declared and enforced risk aligned.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

__all__ = [
    "CATALOGUE",
    "POLICY_LEVELS",
    "RiskLevel",
    "ToolDeclaration",
    "ToolPolicy",
    "effective_auto_approve",
    "effective_tool_policies",
    "is_registered",
    "lookup",
    "policy_may_allow",
    "stricter",
    "tool_names",
]


class RiskLevel(StrEnum):
    """Potential damage from a tool call; policy uses a set, not a threshold."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ToolPolicy(StrEnum):
    """Per-tool gate decision before risk-level policy.

    Absent tools default to ``ASK``; ``ALLOW`` bypasses the prompt and ``DENY``
    refuses the call.
    """

    ASK = "ask"
    ALLOW = "allow"
    DENY = "deny"


#: Strictness order for space-level narrowing.
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
    """Tool name, purpose, and risk; implementation lives elsewhere."""

    name: str
    description: str
    risk: RiskLevel


#: Built-ins agent definitions may allow. Sandboxed reads are low risk; writes
#: and network access are not.
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
        # Confined to the workspace, but may destroy work.
        risk=RiskLevel.MEDIUM,
    ),
    ToolDeclaration(
        name="http_get",
        description="Fetch a URL over HTTP and return the response body.",
        # Reads can exfiltrate workspace data.
        risk=RiskLevel.MEDIUM,
    ),
    ToolDeclaration(
        name="read_feed",
        description=(
            "Fetch an RSS or Atom URL and return bounded, complete entries with "
            "deterministic identifiers."
        ),
        # Same network boundary as ``http_get``.
        risk=RiskLevel.MEDIUM,
    ),
    ToolDeclaration(
        name="read_prices",
        description=(
            "Fetch one year of daily prices for watchlist symbols, compute "
            "watchlist movers, and write stable price files."
        ),
        risk=RiskLevel.MEDIUM,
    ),
    ToolDeclaration(
        name="compute_portfolio",
        description=(
            "Compute portfolio value, P&L, weights, concentration, and limit "
            "crossings from the saved positions and prices."
        ),
        risk=RiskLevel.MEDIUM,
    ),
    ToolDeclaration(
        name="check_limits",
        description=(
            "Check portfolio and thesis tickers against the saved position, "
            "sector, and daily-loss limits."
        ),
        risk=RiskLevel.MEDIUM,
    ),
    ToolDeclaration(
        name="score_predictions",
        description=(
            "Resolve thesis predictions against saved trading sessions and write "
            "the append-only ledger, monthly scorecard, accuracy, and calibration files."
        ),
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


#: Risk levels a policy may answer without a person. ``run_shell`` is the only
#: high-risk tool and runs as the user with no OS isolation, so however much else
#: runs on its own, a person decides each call to it.
POLICY_LEVELS: Final[frozenset[RiskLevel]] = frozenset({RiskLevel.LOW, RiskLevel.MEDIUM})


def policy_may_allow(name: str) -> bool:
    """Whether a policy may answer calls to ``name`` with a yes."""
    declaration = _BY_NAME.get(name)
    return declaration is not None and declaration.risk in POLICY_LEVELS


def effective_tool_policies(
    requested: Mapping[str, ToolPolicy],
    policy: Mapping[str, ToolPolicy],
) -> dict[str, ToolPolicy]:
    """Narrow workspace per-tool policy with a space policy.

    Each result takes the stricter answer; unnamed tools remain absent and
    therefore read as ``ASK``.
    """
    merged = dict(policy)
    for tool, wanted in requested.items():
        merged[tool] = stricter(wanted, policy.get(tool, ToolPolicy.ASK))
    return merged


def effective_auto_approve(
    requested: Iterable[RiskLevel],
    policy: Iterable[RiskLevel],
) -> frozenset[RiskLevel]:
    """Intersect definition auto-approval with workspace policy.

    Intersection ensures definitions cannot widen policy.
    """
    return frozenset(requested) & frozenset(policy)
