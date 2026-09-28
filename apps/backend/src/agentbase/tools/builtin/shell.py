"""``run_shell``: high-risk command execution with bounded output and timeout.

Timeout kills the process tree. The child receives an allowlisted environment,
not the sidecar's credential-bearing environment.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
import subprocess
import sys
from typing import TYPE_CHECKING, Any, Final

from agentbase.tools.base import Prepared, ToolArgumentError, ToolExecutionError
from agentbase.tools.catalogue import RiskLevel, lookup
from agentbase.tools.sandbox import SHELL_TIMEOUT_SECONDS

if TYPE_CHECKING:
    from agentbase.tools.sandbox import Sandbox

__all__ = ["MAX_OUTPUT_CHARS", "RunShellTool"]

#: How much combined output reaches the model and the log.
MAX_OUTPUT_CHARS: Final[int] = 20_000

#: Environment variables required to start a shell or ``cmd.exe``.
_INHERITED_ENV: Final[tuple[str, ...]] = (
    "PATH",
    "SYSTEMROOT",
    "COMSPEC",
    "PATHEXT",
    "WINDIR",
    "TEMP",
    "TMP",
    "LANG",
    "LC_ALL",
)


def _child_environment(workspace: str) -> dict[str, str]:
    """Build child environment from an allowlist rather than filtering ours."""
    environment = {name: os.environ[name] for name in _INHERITED_ENV if name in os.environ}
    # Expose the workspace for command convenience.
    environment["AGENTBASE_WORKSPACE"] = workspace
    return environment


class RunShellTool:
    """Run a shell command in the workspace, with a hard timeout."""

    name = "run_shell"

    @property
    def description(self) -> str:
        declaration = lookup(self.name)
        if declaration is None:  # pragma: no cover: pinned by a test
            msg = f"{self.name!r} has an implementation but no catalogue entry"
            raise RuntimeError(msg)
        return declaration.description

    @property
    def risk(self) -> RiskLevel:
        declaration = lookup(self.name)
        if declaration is None:  # pragma: no cover: pinned by a test
            msg = f"{self.name!r} has an implementation but no catalogue entry"
            raise RuntimeError(msg)
        return declaration.risk

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": (
                        "The shell command to run. It runs in the workspace "
                        "directory with a "
                        f"{SHELL_TIMEOUT_SECONDS:.0f} second timeout."
                    ),
                }
            },
            "required": ["command"],
        }

    def prepare(self, arguments: dict[str, Any], sandbox: Sandbox) -> Prepared:
        command = arguments.get("command")
        if command is None:
            msg = f"{self.name} needs a 'command' argument and none was given."
            raise ToolArgumentError(msg)
        if not isinstance(command, str):
            msg = f"{self.name}'s 'command' must be a string, not {type(command).__name__}."
            raise ToolArgumentError(msg)
        if not command.strip():
            msg = f"{self.name} was given an empty command."
            raise ToolArgumentError(msg)

        # Prompt shows the complete command verbatim.
        return Prepared(
            tool_name=self.name,
            summary=f"run the shell command: {command.strip()}",
            payload={"command": command.strip()},
            raw_arguments=dict(arguments),
        )

    async def execute(self, prepared: Prepared, sandbox: Sandbox) -> str:
        command: str = prepared.payload["command"]

        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                cwd=sandbox.root,
                env=_child_environment(str(sandbox.root)),
                # POSIX process group lets timeout signal the whole tree.
                start_new_session=sys.platform != "win32",
            )
        except OSError as exc:
            msg = f"The command could not be started: {exc.strerror or exc}"
            raise ToolExecutionError(msg) from exc

        try:
            stdout, _ = await asyncio.wait_for(
                process.communicate(), timeout=SHELL_TIMEOUT_SECONDS
            )
        except TimeoutError:
            await self._kill_tree(process)
            msg = (
                f"The command was killed after {SHELL_TIMEOUT_SECONDS:.0f} seconds. "
                f"Commands that wait for input never finish here: stdin is closed."
            )
            raise ToolExecutionError(msg) from None

        output = stdout.decode("utf-8", errors="replace").strip()
        return self._format(process.returncode, output)

    @staticmethod
    async def _kill_tree(process: asyncio.subprocess.Process) -> None:
        """Kill a command and its child processes."""
        if process.returncode is not None:
            return

        if sys.platform == "win32":
            taskkill = shutil.which("taskkill")
            if taskkill is not None:
                killer = await asyncio.create_subprocess_exec(
                    taskkill,
                    "/F",
                    "/T",
                    "/PID",
                    str(process.pid),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                await killer.wait()
        else:
            import signal

            # Fall back to ``process.kill`` if the group cannot be signalled.
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)

        with contextlib.suppress(ProcessLookupError):
            process.kill()

        # Reap the process to avoid an abandoned transport warning.
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(process.wait(), timeout=5.0)

    @staticmethod
    def _format(returncode: int | None, output: str) -> str:
        """Return exit code and output; nonzero exit is not ``tool.error``."""
        body = output if output else "(no output)"
        if len(body) > MAX_OUTPUT_CHARS:
            body = (
                f"{body[:MAX_OUTPUT_CHARS]}\n\n"
                f"[truncated: {len(output)} characters of output, showing "
                f"{MAX_OUTPUT_CHARS}]"
            )

        if returncode == 0:
            return body
        return f"The command exited with status {returncode}.\n\n{body}"
