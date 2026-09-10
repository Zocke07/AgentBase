"""Tools an agent may call, the risk each one carries, and the gate they pass.

Phase 5 populated only :mod:`agentspace.tools.catalogue` — the *names* and risk
levels, with no implementations — because §1 constraint 5 forbids a filesystem,
shell or network call that does not pass an approval gate, and the gate was
this phase's to build.

Phase 6 built it. The package now holds the whole path a tool call travels:

* :mod:`~agentspace.tools.catalogue` — what tools exist and how dangerous each
  one is. Still the registry `allowed_tools` validates against.
* :mod:`~agentspace.tools.base` — the `Tool` protocol, and the `prepare` /
  `execute` split that puts validation before the approval prompt.
* :mod:`~agentspace.tools.sandbox` — the workspace root, and what a call may
  reach. Consulted first, and with no reference to risk or policy.
* :mod:`~agentspace.tools.approval` — the human-in-the-loop gate.
* :mod:`~agentspace.tools.builtin` — the five implementations.
* :mod:`~agentspace.tools.runtime` — the three of those an agent needs at once,
  bundled so an agent cannot be assembled holding only some of them.

The order is the guarantee. A call is refused by the sandbox *before* anyone is
asked about it, so no answer to an approval prompt can authorize something out
of bounds — see :meth:`agentspace.orchestrator.agent.Agent._catalogue_call`,
where the sequence is enforced in one place.
"""

from __future__ import annotations

__all__: list[str] = []
