"""The built-in tools, and the registry that holds them.

Each implements :class:`~agentbase.tools.base.Tool`, reads its risk from the
catalogue rather than restating it, and resolves every path and URL through
the sandbox in `prepare`, before the gate is consulted.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from agentbase.tools.builtin.filesystem import ListDirTool, ReadFileTool, WriteFileTool
from agentbase.tools.builtin.knowledge import SearchKnowledgeTool
from agentbase.tools.builtin.memory import ProposeMemoryTool
from agentbase.tools.builtin.network import HttpGetTool, ReadFeedTool
from agentbase.tools.builtin.shell import RunShellTool

if TYPE_CHECKING:
    from agentbase.tools.base import Tool

__all__ = [
    "BUILTIN_TOOLS",
    "HttpGetTool",
    "ListDirTool",
    "ProposeMemoryTool",
    "ReadFeedTool",
    "ReadFileTool",
    "RunShellTool",
    "SearchKnowledgeTool",
    "WriteFileTool",
    "build_registry",
]

#: Every implemented tool, in catalogue order; a test pins it against the catalogue.
BUILTIN_TOOLS: Final[tuple[type[Tool], ...]] = (
    ReadFileTool,
    ListDirTool,
    SearchKnowledgeTool,
    ProposeMemoryTool,
    WriteFileTool,
    HttpGetTool,
    ReadFeedTool,
    RunShellTool,
)


def build_registry() -> dict[str, Tool]:
    """Instantiate every built-in, keyed by name. Tools are stateless; one instance each."""
    tools: dict[str, Tool] = {}
    for factory in BUILTIN_TOOLS:
        tool = factory()
        tools[tool.name] = tool
    return tools
