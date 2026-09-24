"""Search the current space's Markdown knowledge without leaving the sandbox."""

from __future__ import annotations

from typing import Any

from agentbase.knowledge.store import search_folder
from agentbase.tools.base import Prepared, ToolArgumentError
from agentbase.tools.catalogue import RiskLevel, lookup
from agentbase.tools.sandbox import Sandbox

__all__ = ["SearchKnowledgeTool"]


class SearchKnowledgeTool:
    """Local hybrid retrieval over Markdown notes in the current space."""

    name = "search_knowledge"

    @property
    def description(self) -> str:
        declaration = lookup(self.name)
        if declaration is None:  # pragma: no cover - registry test pins this
            raise RuntimeError(f"{self.name!r} has no catalogue entry")
        return declaration.description

    @property
    def risk(self) -> RiskLevel:
        declaration = lookup(self.name)
        if declaration is None:  # pragma: no cover - registry test pins this
            raise RuntimeError(f"{self.name!r} has no catalogue entry")
        return declaration.risk

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "What to retrieve from this space's Markdown knowledge.",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 20,
                    "description": "Maximum cited chunks to return. Defaults to 8.",
                },
            },
            "required": ["query"],
        }

    def prepare(self, arguments: dict[str, Any], sandbox: Sandbox) -> Prepared:
        query = arguments.get("query")
        if not isinstance(query, str) or not query.strip():
            raise ToolArgumentError("search_knowledge needs a non-empty 'query' string.")
        limit = arguments.get("limit", 8)
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 20:
            raise ToolArgumentError(
                "search_knowledge's 'limit' must be an integer from 1 to 20."
            )
        return Prepared(
            tool_name=self.name,
            summary=f"search local knowledge for {query.strip()!r}",
            payload={"query": query.strip(), "limit": limit},
            raw_arguments=dict(arguments),
        )

    async def execute(self, prepared: Prepared, sandbox: Sandbox) -> str:
        query: str = prepared.payload["query"]
        limit: int = prepared.payload["limit"]
        hits = await search_folder(sandbox.root, query, limit)
        if not hits:
            return f"No knowledge matched {query!r}."
        return "\n\n".join(
            f"{hit.citation} (relevance {hit.score:.0%})\n{hit.excerpt}" for hit in hits
        )
