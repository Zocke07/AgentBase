"""Agent-callable tools, their risk, sandbox, and approval gate.

The call path is catalogue → preparation → sandbox → approval → execution.
Sandbox refusal precedes any prompt, so approval cannot authorize out-of-bounds
access.
"""

from __future__ import annotations

__all__: list[str] = []
