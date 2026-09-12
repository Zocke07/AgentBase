"""The five built-in tools §5 Phase 6 names, and the registry that holds them.

Every one of them implements :class:`agentspace.tools.base.Tool`, declares its
risk by reading :mod:`agentspace.tools.catalogue` rather than restating it, and
resolves every path and URL through the
:class:`~agentspace.tools.sandbox.Sandbox` in `prepare`: before the approval
gate is consulted and before anything is touched.

**Risk is read from the catalogue, never declared here.** The catalogue is what
the allowlist validates against and what the Phase 7 agent editor renders next
to each checkbox. A tool that restated its own risk could disagree with the
label the user ticked, which would make the editor's whole point ("the
consequence of ticking `run_shell` is visible at the moment of ticking it")
quietly false.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from agentspace.tools.builtin.filesystem import ListDirTool, ReadFileTool, WriteFileTool
from agentspace.tools.builtin.network import HttpGetTool
from agentspace.tools.builtin.shell import RunShellTool

if TYPE_CHECKING:
    from agentspace.tools.base import Tool

__all__ = [
    "BUILTIN_TOOLS",
    "HttpGetTool",
    "ListDirTool",
    "ReadFileTool",
    "RunShellTool",
    "WriteFileTool",
    "build_registry",
]

#: Every implemented tool, in catalogue order.
#:
#: `test_every_catalogue_tool_has_an_implementation` pins this against
#: :data:`agentspace.tools.catalogue.CATALOGUE`. The two drifting is the bug
#: that makes `GET /tools` report a tool as available when calling it fails, and
#: it is invisible without that test because each half is internally consistent.
BUILTIN_TOOLS: Final[tuple[type[Tool], ...]] = (
    ReadFileTool,
    ListDirTool,
    WriteFileTool,
    HttpGetTool,
    RunShellTool,
)


def build_registry() -> dict[str, Tool]:
    """Instantiate every built-in, keyed by name.

    Tools are stateless (the sandbox arrives per call), so one instance each
    is enough and a run does not need its own copies.
    """
    tools: dict[str, Tool] = {}
    for factory in BUILTIN_TOOLS:
        tool = factory()
        tools[tool.name] = tool
    return tools
