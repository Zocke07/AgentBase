"""Filesystem tools: ``read_file``, ``list_dir``, and ``write_file``.

All paths pass through :meth:`~agentbase.tools.sandbox.Sandbox.resolve_path`
before approval, and writes through ``resolve_write_path``, which also keeps
agents out of the app's own records. Read and listing results are bounded and report truncation.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Final

from agentbase.knowledge.store import is_memory_markdown
from agentbase.tools.base import Prepared, ToolArgumentError, ToolExecutionError
from agentbase.tools.catalogue import RiskLevel, lookup
from agentbase.tools.sandbox import SandboxViolationError

if TYPE_CHECKING:
    from pathlib import Path

    from agentbase.tools.sandbox import Sandbox

__all__ = ["ListDirTool", "ReadFileTool", "WriteFileTool"]

#: Maximum text returned by ``read_file``.
MAX_READ_CHARS: Final[int] = 20_000

#: Maximum entries returned by ``list_dir``.
MAX_DIR_ENTRIES: Final[int] = 500

#: Maximum text ``write_file`` writes in one call.
MAX_WRITE_CHARS: Final[int] = 200_000

#: Entries named beside a path that does not exist.
MAX_HINT_ENTRIES: Final[int] = 30

#: Bytes read to tell a binary file from text.
_SNIFF_BYTES: Final[int] = 8192


def _risk(name: str) -> RiskLevel:
    """Return catalogue risk for ``name`` without redeclaring it."""
    declaration = lookup(name)
    if declaration is None:  # pragma: no cover: pinned by a test
        msg = f"{name!r} has an implementation but no catalogue entry"
        raise RuntimeError(msg)
    return declaration.risk


def _description(name: str) -> str:
    declaration = lookup(name)
    if declaration is None:  # pragma: no cover: pinned by a test
        msg = f"{name!r} has an implementation but no catalogue entry"
        raise RuntimeError(msg)
    return declaration.description


def _space_path(sandbox: Sandbox, path: Path) -> str:
    """A path as read_file and list_dir take it: from the space root, with ``/``."""
    return sandbox.relative(path).replace("\\", "/")


def _nearby(sandbox: Sandbox, missing: Path) -> str:
    """What exists nearest a missing path, so the agent's next call can be right.

    On 2026-10-13 a decision listed a "facts" folder that never existed; told
    only that, it had to guess again. Hidden entries are left out, as
    retrieval leaves them out.
    """
    folder = missing.parent
    while not folder.is_dir() and sandbox.root in folder.parents:
        folder = folder.parent
    if folder != sandbox.root and sandbox.root not in folder.parents:
        return ""
    try:
        entries = sorted(
            (entry for entry in folder.iterdir() if not entry.name.startswith(".")),
            key=lambda entry: entry.name.lower(),
        )
    except OSError:
        return ""
    shown = _space_path(sandbox, folder)
    where = "The space's top level" if shown == "." else shown
    if not entries:
        return f" {where} is empty."
    prefix = "" if shown == "." else f"{shown}/"
    named = [
        f"{prefix}{entry.name}/" if entry.is_dir() else f"{prefix}{entry.name}"
        for entry in entries[:MAX_HINT_ENTRIES]
    ]
    more = len(entries) - MAX_HINT_ENTRIES
    tail = f", and {more} more" if more > 0 else ""
    return f" {where} holds: {', '.join(named)}{tail}."


def _required_str(arguments: dict[str, Any], key: str, tool: str) -> str:
    """Read a required string argument or raise a retryable error."""
    value = arguments.get(key)
    if value is None:
        msg = f"{tool} needs a {key!r} argument and none was given."
        raise ToolArgumentError(msg)
    if not isinstance(value, str):
        msg = f"{tool}'s {key!r} must be a string, not {type(value).__name__}."
        raise ToolArgumentError(msg)
    return value


class ReadFileTool:
    """Read a UTF-8 text file from inside the workspace."""

    name = "read_file"

    @property
    def description(self) -> str:
        return _description(self.name)

    @property
    def risk(self) -> RiskLevel:
        return _risk(self.name)

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "Path to the file, relative to the workspace root, "
                        "such as 'notes.txt' or 'reports/q1.md'."
                    ),
                },
                "offset": {
                    "type": "integer",
                    "minimum": 0,
                    "description": (
                        "Character position to start from, as a cut-off read's note "
                        "gives it. Leave it out to read from the start."
                    ),
                },
            },
            "required": ["path"],
        }

    def prepare(self, arguments: dict[str, Any], sandbox: Sandbox) -> Prepared:
        raw = _required_str(arguments, "path", self.name)
        offset = arguments.get("offset", 0)
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            msg = f"{self.name}'s 'offset' must be a whole number of characters, 0 or more."
            raise ToolArgumentError(msg)
        resolved = sandbox.resolve_path(raw)
        shown = sandbox.relative(resolved)

        return Prepared(
            tool_name=self.name,
            summary=f"read the file {shown}" + (f" from character {offset}" if offset else ""),
            payload={"path": resolved, "shown": shown, "offset": offset},
            raw_arguments=dict(arguments),
        )

    async def execute(self, prepared: Prepared, sandbox: Sandbox) -> str:
        path: Path = prepared.payload["path"]
        shown: str = prepared.payload["shown"]

        def read() -> str:
            if not path.exists():
                msg = f"There is no file at {shown} in the workspace.{_nearby(sandbox, path)}"
                raise ToolExecutionError(msg)
            if path.is_dir():
                msg = f"{shown} is a directory, not a file. Use list_dir for it."
                raise ToolExecutionError(msg)
            try:
                with path.open("rb") as handle:
                    head = handle.read(_SNIFF_BYTES)
                if b"\0" in head:
                    # Said, not shown: a decision that read a workbook was sent
                    # about 29,000 tokens of zip bytes (2026-10-13).
                    size = path.stat().st_size
                    return (
                        f"{shown} is a binary file ({size:,} bytes), such as a workbook "
                        f"or an image, so its contents are not shown. read_file shows "
                        f"text files only; read the text file it was made from instead."
                    )
                # Preserve readable text despite stray bytes.
                return path.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                msg = f"{shown} could not be read: {exc.strerror or exc}"
                raise ToolExecutionError(msg) from exc

        content = await asyncio.to_thread(read)
        return _page(content, shown, prepared.payload.get("offset", 0))


def _page(content: str, shown: str, start: int) -> str:
    """At most ``MAX_READ_CHARS`` from ``start``, ending on a whole line.

    A cut-off read says where the next one starts: the day's headlines once ran
    past the limit, and the risk manager and the decision never saw the last
    quarter of them (2026-10-20).
    """
    total = len(content)
    if start == 0 and total <= MAX_READ_CHARS:
        return content
    if start > 0 and start >= total:
        msg = f"offset {start} is past the end of {shown}, which is {total} characters."
        raise ToolExecutionError(msg)
    end = start + MAX_READ_CHARS
    if end >= total:
        return f"{content[start:]}\n\n[the end of {shown}: characters {start} to {total} of {total}]"
    # End on a line break, so a record of JSON lines is never split in two.
    line_end = content.rfind("\n", start, end)
    if line_end >= start:
        end = line_end + 1
    return (
        f"{content[start:end]}\n\n"
        f"[truncated: {shown} is {total} characters; this shows characters {start} to "
        f"{end}. Call read_file with offset {end} to read on.]"
    )


class ListDirTool:
    """List a directory inside the workspace."""

    name = "list_dir"

    @property
    def description(self) -> str:
        return _description(self.name)

    @property
    def risk(self) -> RiskLevel:
        return _risk(self.name)

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "Directory to list, relative to the workspace root. "
                        "Omit or use '.' for the workspace root itself."
                    ),
                }
            },
            "required": [],
        }

    def prepare(self, arguments: dict[str, Any], sandbox: Sandbox) -> Prepared:
        # Listing the root is the default first call.
        raw = arguments.get("path") or "."
        if not isinstance(raw, str):
            msg = f"{self.name}'s 'path' must be a string, not {type(raw).__name__}."
            raise ToolArgumentError(msg)

        resolved = sandbox.resolve_path(raw)
        shown = sandbox.relative(resolved)
        where = "the workspace root" if shown == "." else shown

        return Prepared(
            tool_name=self.name,
            summary=f"list the contents of {where}",
            payload={"path": resolved, "shown": where},
            raw_arguments=dict(arguments),
        )

    async def execute(self, prepared: Prepared, sandbox: Sandbox) -> str:
        path: Path = prepared.payload["path"]
        shown: str = prepared.payload["shown"]

        def listing() -> str:
            if not path.exists():
                msg = f"There is no directory at {shown} in the workspace.{_nearby(sandbox, path)}"
                raise ToolExecutionError(msg)
            if not path.is_dir():
                msg = f"{shown} is a file, not a directory. Use read_file for it."
                raise ToolExecutionError(msg)
            try:
                entries = sorted(path.iterdir(), key=lambda item: item.name.lower())
            except OSError as exc:
                msg = f"{shown} could not be listed: {exc.strerror or exc}"
                raise ToolExecutionError(msg) from exc

            if not entries:
                return f"{shown} is empty."

            # Each entry by its path from the space root, which is what
            # read_file takes: a bare name read from a listed folder missed.
            # Built from the checked folder, so a link is never resolved here.
            folder = _space_path(sandbox, path)
            prefix = "" if folder == "." else f"{folder}/"
            lines = []
            for entry in entries[:MAX_DIR_ENTRIES]:
                named = f"{prefix}{entry.name}"
                if entry.is_dir():
                    lines.append(f"{named}/")
                else:
                    try:
                        size = entry.stat().st_size
                    except OSError:
                        lines.append(named)
                    else:
                        lines.append(f"{named} ({size} bytes)")

            if len(entries) > MAX_DIR_ENTRIES:
                lines.append(f"[truncated: {len(entries)} entries, showing {MAX_DIR_ENTRIES}]")
            return "\n".join(lines)

        return await asyncio.to_thread(listing)


class WriteFileTool:
    """Create or overwrite a sandboxed workspace file."""

    name = "write_file"

    @property
    def description(self) -> str:
        return _description(self.name)

    @property
    def risk(self) -> RiskLevel:
        return _risk(self.name)

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "Path to write, relative to the workspace root. Parent "
                        "directories are created as needed."
                    ),
                },
                "content": {
                    "type": "string",
                    "description": "The full contents to write. Replaces the file.",
                },
            },
            "required": ["path", "content"],
        }

    def prepare(self, arguments: dict[str, Any], sandbox: Sandbox) -> Prepared:
        raw = _required_str(arguments, "path", self.name)
        content = _required_str(arguments, "content", self.name)

        if len(content) > MAX_WRITE_CHARS:
            msg = (
                f"{self.name} was given {len(content)} characters, which is over "
                f"the {MAX_WRITE_CHARS} limit for a single write."
            )
            raise ToolArgumentError(msg)

        resolved = sandbox.resolve_write_path(raw)
        shown = sandbox.relative(resolved)

        # A memory-typed note is retrieved by its own `status`, so writing one
        # would approve a memory without the inbox. Retrieval reads only
        # Markdown, which is the only kind worth refusing.
        # Read the name as retrieval will find it, whatever its spelling.
        is_note = resolved.name.rstrip(". ").casefold().endswith(".md")
        if is_note and is_memory_markdown(content):
            msg = (
                f"{shown} is written as a memory note, and agents cannot write "
                f"memories directly. Use propose_memory, which puts it in the "
                f"inbox for review."
            )
            raise SandboxViolationError(msg)

        # Prompt distinguishes creation from overwrite; this is descriptive,
        # not a concurrency boundary.
        verb = "overwrite" if resolved.exists() else "create"
        return Prepared(
            tool_name=self.name,
            summary=f"{verb} the file {shown} ({len(content)} characters)",
            payload={"path": resolved, "shown": shown, "content": content},
            raw_arguments=dict(arguments),
        )

    async def execute(self, prepared: Prepared, sandbox: Sandbox) -> str:
        path: Path = prepared.payload["path"]
        shown: str = prepared.payload["shown"]
        content: str = prepared.payload["content"]

        def write() -> str:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                # Force LF; ``write_text`` would use CRLF on Windows.
                with path.open("w", encoding="utf-8", newline="\n") as handle:
                    handle.write(content)
            except OSError as exc:
                msg = f"{shown} could not be written: {exc.strerror or exc}"
                raise ToolExecutionError(msg) from exc
            return f"Wrote {len(content)} characters to {shown}."

        return await asyncio.to_thread(write)
