"""Tools an agent may call, and the risk each one carries.

Phase 5 populates only :mod:`agentspace.tools.catalogue` — the *names* and risk
levels, with no implementations. Phase 6 adds `base.py` (the Tool protocol),
`approval.py`, `sandbox.py` and `builtin/`, and binds executable code to the
names declared here.
"""

from __future__ import annotations

__all__: list[str] = []
