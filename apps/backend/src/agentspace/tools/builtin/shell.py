"""`run_shell`: the highest-risk tool, and the one with the most honest limits.

The hard timeout is real, and it kills the process *tree* (`taskkill /T` on
Windows, a process-group signal on POSIX); killing only the direct child
leaves the real command running. "No network" is not enforced and cannot be
in-process cross-platform: a command that calls `curl` reaches the internet.
§5 Phase 6's addendum puts real isolation in a container outside the shipped
build; here the mitigation is that `run_shell` is `high` risk and always
asks. The child gets a constructed environment from an allowlist, never a
copy of the sidecar's, which holds API keys.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
import subprocess
import sys
from typing import TYPE_CHECKING, Any, Final

from agentspace.tools.base import Prepared, ToolArgumentError, ToolExecutionError
from agentspace.tools.catalogue import RiskLevel, lookup
from agentspace.tools.sandbox import SHELL_TIMEOUT_SECONDS

if TYPE_CHECKING:
    from agentspace.tools.sandbox import Sandbox

__all__ = ["MAX_OUTPUT_CHARS", "RunShellTool"]

#: How much combined output reaches the model and the log.
MAX_OUTPUT_CHARS: Final[int] = 20_000

#: Environment variables the child may inherit: what `cmd.exe` and a shell
#: need to start, and nothing else.
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
    """Build the child's environment from the allowlist rather than filtering ours."""
    environment = {name: os.environ[name] for name in _INHERITED_ENV if name in os.environ}
    # Convenience, and a hint about where the command is running.
    environment["AGENTSPACE_WORKSPACE"] = workspace
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

        # The whole command, verbatim: it is the thing the user is asked to judge.
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
                # POSIX: its own process group, so the whole tree can be signalled.
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
        """Kill the command and everything it started.

        `process.kill()` alone leaves the children running.
        """
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

            # Already gone, or a group we may not signal; `process.kill()` below remains.
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)

        with contextlib.suppress(ProcessLookupError):
            process.kill()

        # Reap it, so the event loop does not warn about an abandoned transport.
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(process.wait(), timeout=5.0)

    @staticmethod
    def _format(returncode: int | None, output: str) -> str:
        """Report the exit code alongside the output.

        A non-zero exit is a result, not a `tool.error`.
        """
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
