"""Let an agent propose durable memory without silently trusting it."""

from __future__ import annotations

import asyncio
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from agentspace.tools.base import Prepared, ToolArgumentError
from agentspace.tools.catalogue import RiskLevel, lookup
from agentspace.tools.sandbox import Sandbox

__all__ = ["ProposeMemoryTool"]


class ProposeMemoryTool:
    """Write a proposed Markdown memory that requires later user approval."""

    name = "propose_memory"

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
                "title": {
                    "type": "string",
                    "description": "A short factual title for the proposed memory.",
                },
                "content": {
                    "type": "string",
                    "description": "The durable conclusion and evidence worth remembering.",
                },
                "confidence": {
                    "type": "string",
                    "enum": ["low", "medium", "high"],
                    "description": "How strongly the available evidence supports it.",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional tags without leading # characters.",
                },
            },
            "required": ["title", "content", "confidence"],
        }

    def prepare(self, arguments: dict[str, Any], sandbox: Sandbox) -> Prepared:
        title = arguments.get("title")
        content = arguments.get("content")
        confidence = arguments.get("confidence")
        tags = arguments.get("tags", [])
        if not isinstance(title, str) or not title.strip() or len(title) > 120:
            raise ToolArgumentError("propose_memory needs a title from 1 to 120 characters.")
        if not isinstance(content, str) or not content.strip() or len(content) > 20_000:
            raise ToolArgumentError("propose_memory needs content from 1 to 20,000 characters.")
        if confidence not in {"low", "medium", "high"}:
            raise ToolArgumentError("propose_memory confidence must be low, medium, or high.")
        if not isinstance(tags, list) or any(
            not isinstance(tag, str)
            or re.fullmatch(r"[\w/-]{1,60}", tag.strip().lstrip("#")) is None
            for tag in tags
        ):
            raise ToolArgumentError(
                "propose_memory tags may contain letters, numbers, slash, underscore, or dash."
            )
        clean_tags = list(dict.fromkeys(tag.strip().lstrip("#") for tag in tags))[:20]
        return Prepared(
            tool_name=self.name,
            summary=f"propose a memory titled {title.strip()!r}",
            payload={
                "title": " ".join(title.split()),
                "content": content.strip(),
                "confidence": confidence,
                "tags": clean_tags,
            },
            raw_arguments=dict(arguments),
        )

    async def execute(self, prepared: Prepared, sandbox: Sandbox) -> str:
        memory_id = str(uuid.uuid4())
        relative = f"memory/inbox/{memory_id}.md"
        destination = sandbox.resolve_path(relative)
        tags: list[str] = prepared.payload["tags"]
        tag_lines = "".join(f"  - {tag}\n" for tag in ["agent-memory", *tags])
        content = (
            "---\n"
            "type: agent-memory\n"
            f"memory_id: {memory_id}\n"
            f"created: {datetime.now(UTC).date().isoformat()}\n"
            "status: proposed\n"
            "pinned: false\n"
            f"confidence: {prepared.payload['confidence']}\n"
            "tags:\n"
            f"{tag_lines}"
            "---\n"
            f"# {prepared.payload['title']}\n\n"
            "## Goal\n\nAgent-proposed durable knowledge\n\n"
            "## Outcome\n\n"
            f"{prepared.payload['content']}\n"
        )

        def write() -> None:
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_suffix(".md.agentspace-tmp")
            temporary.write_text(content, encoding="utf-8")
            temporary.replace(destination)

        await asyncio.to_thread(write)
        return f"Proposed memory [[{relative.removesuffix('.md')}]] for user review."
