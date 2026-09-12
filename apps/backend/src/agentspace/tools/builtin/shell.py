"""`run_shell`: the highest-risk tool, and the one with the most honest limits.

§5 Phase 6 asks for two properties: "`run_shell` has no network and a hard
timeout." One of those is fully enforceable in-process and the other is not, so
this module states plainly which is which rather than implying both.

**The hard timeout is real.** The command is killed at
:data:`~agentspace.tools.sandbox.SHELL_TIMEOUT_SECONDS`, and killed *as a
process tree*: `taskkill /T` on Windows, a process-group signal on POSIX.
Killing only the direct child is the same mistake Phase 1 made with the
PyInstaller bootloader: the process the parent holds a handle to is not the
process doing the work, so `proc.kill()` returns cleanly and leaves the real
command running. A timeout that orphans what it was meant to stop is not a
timeout.

**"No network" is not enforced here, and cannot be.** There is no in-process,
cross-platform way to deny a child process a socket. What this module actually
does is remove the *environment* that makes network use convenient (proxy
variables and every inherited secret-bearing variable), which raises the cost
and does not close the hole. A command that calls `curl` still reaches the
internet.

That is not a shortfall being glossed over: it is the exact gap BUILD_SPEC §5
Phase 6's own addendum identifies when it says the app-level sandbox "is a real
but limited boundary" and that a misbehaving shell command "still runs as your
actual user account", and it is why the addendum puts real isolation in a
container on the maintainer's own instance rather than in the shipped build.
The mitigation that *is* in the shipped build is the approval gate: `run_shell`
is `high` risk, so every call stops and asks unless the user has explicitly
pre-authorized high-risk calls.

**The environment is scrubbed, and that part matters more than it looks.** The
sidecar holds API keys in memory (§1 constraint 4). A child process inheriting
the parent's environment wholesale is a standing invitation for the next thing
that puts a credential in one to leak it to any command an agent can run, so the
child gets a constructed environment rather than a filtered copy of ours.
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

#: Environment variables the child is allowed to inherit, by name.
#:
#: An allowlist, for the same reason `allowed_tools` is one: the interesting
#: variable is always the one nobody thought to deny. `PATH` and the Windows
#: shell's own requirements are here because without them `cmd.exe` cannot
#: start at all; nothing else is.
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
    """Build the child's environment rather than filtering ours.

    Constructed from an allowlist so that a variable added to the sidecar's
    environment in some later phase does not silently become readable by every
    shell command an agent runs.
    """
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

        # The whole command, verbatim, in the summary. §5 Phase 6 wants a
        # human-legible prompt, and for this tool the command *is* the
        # legible fact: abbreviating it would hide the part the user is being
        # asked to judge.
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
                # POSIX: give the child its own process group so the whole tree
                # can be signalled on timeout. Windows gets the same effect from
                # `taskkill /T` below.
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

        `process.kill()` alone stops the shell and leaves its children running -
        which is how a "timed out" command keeps holding a file and burning CPU
        after the run that started it has ended.
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

            # Already gone, or a group we may not signal. Either way the
            # `process.kill()` below is the remaining thing to try.
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

        A non-zero exit is *reported*, not raised: a failing command is
        frequently the informative result (a test run that fails, a grep that
        matches nothing), and turning it into `tool.error` would tell the agent
        the tool broke when the tool worked perfectly.
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
