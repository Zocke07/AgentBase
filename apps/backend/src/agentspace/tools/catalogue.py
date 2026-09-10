"""What tools exist, and how dangerous each one is.

**This module declares names and risk levels. It implements nothing.**

§5 Phase 5 requires that "every entry in `allowed_tools` must resolve to a
registered tool", so validating an agent definition needs a registry of tools
to resolve against — in this phase, before any tool can exist. §1 constraint 5
is why none can: every filesystem, shell and network call passes the approval
gate, and that gate is Phase 6. Shipping a working `write_file` here to give
the allowlist something real to point at would create exactly the ungated path
the constraint forbids.

So the catalogue is a *declaration* of the five built-ins §5 Phase 6 names,
carrying the one fact Phase 5 and Phase 7 both need about them — their risk —
and nothing else. Phase 6 attaches implementations, the sandbox and the
approval gate to these same names. Until it does, an agent permitted a
catalogue tool that calls it is told the tool is not available yet; the call is
never dispatched, because there is nothing to dispatch to.

Two consumers depend on this being data rather than code:

* the allowlist validator in :mod:`agentspace.store.agents`, which rejects a
  definition naming a tool that does not exist;
* Phase 7's agent editor, which §5 says must show "each tool's risk level next
  to it, so the consequence of ticking `run_shell` is visible at the moment of
  ticking it". A UI hardcoding that list would drift from this one.

`RiskLevel` lives here rather than in the `base.py` §3's layout sketches
because `base.py` is the Tool *protocol*, whose signature depends on the
sandbox Phase 6 owns. Half a protocol now would be a file Phase 6 rewrites.
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
    """How much damage a tool call can do. §5 Phase 6's three levels.

    The ordering is meaningful to a reader and deliberately not encoded as
    comparison: "at most medium" is not a policy this project expresses, because
    `http_get` and `write_file` are both medium and permitting one is not a
    reason to permit the other. Policy is a *set* of levels, never a threshold.
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True, slots=True)
class ToolDeclaration:
    """One tool's name, purpose and risk. No implementation, by design."""

    name: str
    description: str
    risk: RiskLevel


#: The five built-ins §5 Phase 6 names, and nothing else. A definition may only
#: allow a tool listed here.
#:
#: The risk levels follow §5 Phase 6 directly: "any `medium`/`high` risk call
#: emits `approval.requested` and blocks until resolved. `low` risk (read within
#: workspace) may be auto-approved by policy." So reads inside the sandbox are
#: low; anything that writes, or that leaves the machine, is not.
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
        # Medium, not high: the sandbox confines it to the workspace root, so
        # the worst case is losing work the user put there — recoverable, and
        # not the same class of thing as running arbitrary code.
        risk=RiskLevel.MEDIUM,
    ),
    ToolDeclaration(
        name="http_get",
        description="Fetch a URL over HTTP and return the response body.",
        # Medium despite being a read: it is the one tool that can carry the
        # contents of the workspace off the machine, so a prompt-injected agent
        # calling it is an exfiltration path, not a page view.
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
    """Whether ``name`` resolves to a declared tool (§5 Phase 5, validation)."""
    return name in _BY_NAME


def lookup(name: str) -> ToolDeclaration | None:
    return _BY_NAME.get(name)


def effective_auto_approve(
    requested: Iterable[RiskLevel],
    policy: Iterable[RiskLevel],
) -> frozenset[RiskLevel]:
    """Intersect a definition's `auto_approve` with the workspace policy.

    §5 Phase 5's security note: "`auto_approve` on an agent definition may only
    *narrow* what the global policy already permits — it can never grant a risk
    level the workspace policy has not enabled."

    An intersection is the whole implementation, and writing it as one is the
    point: a union, or a definition-wins fallback, would let a user-authored
    row escalate its own privileges, which is precisely the shape §5 says to
    stop and reconsider on. There is no argument order that changes the answer
    and no value of ``requested`` that can add to ``policy``.

    **Nothing calls this in Phase 5**, because nothing is approved in Phase 5 —
    there is no gate and no tool to put behind one. It exists, and is tested,
    so that Phase 6 wires the workspace policy into a rule that is already
    settled rather than inventing one at the point of building the gate.
    """
    return frozenset(requested) & frozenset(policy)
