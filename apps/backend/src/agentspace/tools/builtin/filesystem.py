"""`read_file`, `list_dir`, `write_file`: the three tools that touch the disk.

None of them interprets a path: every one goes through
:meth:`~agentspace.tools.sandbox.Sandbox.resolve_path` in `prepare`, the one
place containment is decided. Results are truncated, and the truncation is
stated in the result text: a tool result is repeated in every later
`llm.request`, and a model that believes it read a whole file reasons about
the part it did not see.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Final

from agentspace.tools.base import Prepared, ToolArgumentError, ToolExecutionError
from agentspace.tools.catalogue import RiskLevel, lookup

if TYPE_CHECKING:
    from pathlib import Path

    from agentspace.tools.sandbox import Sandbox

__all__ = ["ListDirTool", "ReadFileTool", "WriteFileTool"]

#: How much of a file `read_file` returns. See the module docstring.
MAX_READ_CHARS: Final[int] = 20_000

#: How many entries `list_dir` returns.
MAX_DIR_ENTRIES: Final[int] = 500

#: How much `write_file` will write in one call, so one bad call cannot fill the disk.
MAX_WRITE_CHARS: Final[int] = 200_000


def _risk(name: str) -> RiskLevel:
    """The catalogue's risk for ``name``, never a second declaration of it."""
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


def _required_str(arguments: dict[str, Any], key: str, tool: str) -> str:
    """Read a required string argument, or say what was wrong so the model can retry."""
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
                }
            },
            "required": ["path"],
        }

    def prepare(self, arguments: dict[str, Any], sandbox: Sandbox) -> Prepared:
        raw = _required_str(arguments, "path", self.name)
        resolved = sandbox.resolve_path(raw)
        shown = sandbox.relative(resolved)

        return Prepared(
            tool_name=self.name,
            summary=f"read the file {shown}",
            payload={"path": resolved, "shown": shown},
            raw_arguments=dict(arguments),
        )

    async def execute(self, prepared: Prepared, sandbox: Sandbox) -> str:
        path: Path = prepared.payload["path"]
        shown: str = prepared.payload["shown"]

        def read() -> str:
            if not path.exists():
                msg = f"There is no file at {shown} in the workspace."
                raise ToolExecutionError(msg)
            if path.is_dir():
                msg = f"{shown} is a directory, not a file. Use list_dir for it."
                raise ToolExecutionError(msg)
            try:
                # A stray byte should not turn a readable file into an error.
                return path.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                msg = f"{shown} could not be read: {exc.strerror or exc}"
                raise ToolExecutionError(msg) from exc

        content = await asyncio.to_thread(read)

        if len(content) > MAX_READ_CHARS:
            return (
                f"{content[:MAX_READ_CHARS]}\n\n"
                f"[truncated: {shown} is {len(content)} characters and only the "
                f"first {MAX_READ_CHARS} are shown]"
            )
        return content


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
        # Optional: listing the root is the obvious first call.
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
                msg = f"There is no directory at {shown} in the workspace."
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

            lines = []
            for entry in entries[:MAX_DIR_ENTRIES]:
                if entry.is_dir():
                    lines.append(f"{entry.name}/")
                else:
                    try:
                        size = entry.stat().st_size
                    except OSError:
                        lines.append(entry.name)
                    else:
                        lines.append(f"{entry.name} ({size} bytes)")

            if len(entries) > MAX_DIR_ENTRIES:
                lines.append(f"[truncated: {len(entries)} entries, showing {MAX_DIR_ENTRIES}]")
            return "\n".join(lines)

        return await asyncio.to_thread(listing)


class WriteFileTool:
    """Create or overwrite a file inside the workspace.

    Containment is the sandbox's, not this class's.
    """

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

        resolved = sandbox.resolve_path(raw)
        shown = sandbox.relative(resolved)

        # "create" and "overwrite" are different decisions for the user.
        # Checked at prepare time, possibly minutes before the write; a file
        # created meanwhile makes the description wrong, never the boundary.
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
                # `newline="\n"`: `write_text` would write CRLF on Windows.
                with path.open("w", encoding="utf-8", newline="\n") as handle:
                    handle.write(content)
            except OSError as exc:
                msg = f"{shown} could not be written: {exc.strerror or exc}"
                raise ToolExecutionError(msg) from exc
            return f"Wrote {len(content)} characters to {shown}."

        return await asyncio.to_thread(write)
