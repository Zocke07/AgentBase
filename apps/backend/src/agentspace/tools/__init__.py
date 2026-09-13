"""Tools an agent may call, the risk each one carries, and the gate they pass.

The whole path a tool call travels: :mod:`~agentspace.tools.catalogue` (what
exists, and its risk), :mod:`~agentspace.tools.base` (the `Tool` protocol and
the `prepare`/`execute` split), :mod:`~agentspace.tools.sandbox` (what a call
may reach, consulted first), :mod:`~agentspace.tools.approval` (the gate),
:mod:`~agentspace.tools.builtin` (the implementations) and
:mod:`~agentspace.tools.runtime` (the bundle an agent needs). The sandbox
refuses before anyone is asked, so no answer to a prompt can authorize
something out of bounds; `Agent._catalogue_call` enforces the sequence.
"""

from __future__ import annotations

__all__: list[str] = []
