"""`read_file`, `list_dir`, `write_file`: the three tools that touch the disk.

All three take a path, and none of them interprets it: every one goes through
:meth:`agentspace.tools.sandbox.Sandbox.resolve_path` in `prepare`, which is
the single place containment is decided. A tool that did its own path handling
would be a second boundary to keep correct, and the second one is always the
one that is wrong.

**Results are truncated, and the truncation is visible.** A tool result goes
into the event log *and* into the model's transcript, which `llm.request`
then repeats on every subsequent turn, so an unbounded read grows the log
quadratically (a hazard CLAUDE.md already records against long runs). Silently
returning a prefix would be worse than the size: a model that believes it read
a whole file will reason about the part it did not see. So the cap is stated in
the result text where the model reads it.
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

#: How much `write_file` will write in one call. A model that means to write a
#: megabyte has usually lost the plot, and the cap keeps one bad call from
#: filling the user's disk.
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
    """Read a required string argument, or say what was wrong with the call.

    Not tolerant the way :func:`agentspace.orchestrator.agent._text_argument`
    is: a control call with a missing argument can still do something sensible,
    while `write_file` with no path cannot. The message names the tool and the
    argument because it goes back to the model, which then has enough to retry.
    """
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
                # `errors="replace"` rather than failing: a model asking for a
                # text file that turns out to hold a stray byte is better served
                # by the readable remainder than by an encoding error.
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
        # The only optional path argument: listing the workspace root is the
        # obvious first call an agent makes, and requiring '.' for it wastes a
        # step on a model that omitted it.
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

    The tool §5 Phase 6's acceptance criterion is written about: "an agent
    instructed to write outside the workspace root is blocked at the sandbox
    layer, and this is visible in the event log as `tool.denied`". Nothing in
    this class implements that: :meth:`prepare` calls `resolve_path` and the
    sandbox raises. That is the point of it living there.
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

        # The summary distinguishes the two cases because they are different
        # decisions for the user: creating a file is additive, and overwriting
        # one destroys work that may not be recoverable. §5 Phase 6's own
        # example prompt is about a destructive call for exactly this reason.
        #
        # Read at prepare time, which is before the approval and therefore
        # possibly minutes before the write. If something else creates the file
        # while the user is deciding, the prompt said "create" and an overwrite
        # happens. Re-checking at execute time would not help (the decision has
        # already been made by then), and the honest fix is a compare-and-swap
        # the `Tool` protocol has no vocabulary for. Recorded rather than
        # papered over: it is a wrong *description*, never a wrong boundary, and
        # the write is still confined to the workspace either way.
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
                # `newline="\n"` because `write_text` translates to CRLF on
                # Windows. This project has already had six source files
                # silently converted that way (CLAUDE.md, Phase 4); a tool that
                # does it to a user's file is the same bug with a wider blast
                # radius, and an agent writing YAML or a diff would corrupt it.
                with path.open("w", encoding="utf-8", newline="\n") as handle:
                    handle.write(content)
            except OSError as exc:
                msg = f"{shown} could not be written: {exc.strerror or exc}"
                raise ToolExecutionError(msg) from exc
            return f"Wrote {len(content)} characters to {shown}."

        return await asyncio.to_thread(write)
