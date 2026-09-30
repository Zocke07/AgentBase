"""Built-in tools and their registry.

Each implements :class:`~agentbase.tools.base.Tool`, reads risk from the
catalogue, and resolves paths or URLs before approval.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from agentbase.tools.builtin.filesystem import ListDirTool, ReadFileTool, WriteFileTool
from agentbase.tools.builtin.knowledge import SearchKnowledgeTool
from agentbase.tools.builtin.memory import ProposeMemoryTool
from agentbase.tools.builtin.network import HttpGetTool, ReadFeedTool
from agentbase.tools.builtin.portfolio import ComputePortfolioTool
from agentbase.tools.builtin.prices import ReadPricesTool
from agentbase.tools.builtin.shell import RunShellTool

if TYPE_CHECKING:
    from agentbase.tools.base import Tool

__all__ = [
    "BUILTIN_TOOLS",
    "ComputePortfolioTool",
    "HttpGetTool",
    "ListDirTool",
    "ProposeMemoryTool",
    "ReadFeedTool",
    "ReadFileTool",
    "ReadPricesTool",
    "RunShellTool",
    "SearchKnowledgeTool",
    "WriteFileTool",
    "build_registry",
]

#: Implemented tools in catalogue order; tests pin the two lists together.
BUILTIN_TOOLS: Final[tuple[type[Tool], ...]] = (
    ReadFileTool,
    ListDirTool,
    SearchKnowledgeTool,
    ProposeMemoryTool,
    WriteFileTool,
    HttpGetTool,
    ReadFeedTool,
    ReadPricesTool,
    ComputePortfolioTool,
    RunShellTool,
)


def build_registry() -> dict[str, Tool]:
    """Create one stateless instance of every built-in, keyed by name."""
    tools: dict[str, Tool] = {}
    for factory in BUILTIN_TOOLS:
        tool = factory()
        tools[tool.name] = tool
    return tools
