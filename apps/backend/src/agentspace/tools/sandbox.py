"""Where a tool call may reach, decided before anything runs or anyone is asked.

§5 Phase 6: "a configured workspace root. Path traversal outside it is rejected
**before the approval prompt is even shown**." That ordering is the whole
design. An approval dialog reading *Agent "researcher" wants to write to
`../../../Windows/System32/drivers/etc/hosts` — Allow / Deny* puts the user one
misclick from the thing the sandbox exists to prevent, and asks them to make a
judgement they have no way to make well. A path outside the root is not a risky
call awaiting a decision; it is not a call at all.

So this module answers one question — *is this reachable?* — and answers it with
no reference to risk levels, policy, or who is asking. Those are the approval
gate's business, and it only ever sees calls that already passed here.

**Resolution, not inspection.** Every check below compares fully resolved paths.
A string search for `".."` rejects the legitimate `reports/../notes.txt` and
misses a symlink that contains neither dots nor slashes, which is the escape
that actually works. :meth:`Path.resolve` collapses traversal *and* follows
symlinks, so one comparison covers both, plus the drive-letter and UNC cases
that a POSIX-shaped implementation treats as ordinary relative segments.

**On URLs.** `http_get` is the one tool that reaches off the filesystem, and the
containment idea has a direct analogue: the machine's own services are inside
the boundary and must stay unreachable. Without :meth:`Sandbox.check_url`, an
agent can fetch `http://127.0.0.1:8787/settings` and read this application's own
API from inside a run — §1 constraint 3 keeps other *machines* out and does
nothing about that. :meth:`Sandbox.resolve_url` also hands back the address it
checked, so `http_get` connects to that one rather than resolving the name a
second time — see the method for why that matters.
"""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Final
from urllib.parse import urlsplit

__all__ = [
    "SHELL_TIMEOUT_SECONDS",
    "CheckedUrl",
    "Sandbox",
    "SandboxViolationError",
    "UrlNotAllowedError",
]

#: How long `run_shell` may run before it is killed (§5 Phase 6: "a hard
#: timeout"). Long enough for a build or a test run, short enough that a
#: command waiting on input the agent cannot supply does not hold the run's
#: whole wall-clock budget.
SHELL_TIMEOUT_SECONDS: Final[float] = 60.0

#: Schemes `http_get` will fetch. An allowlist rather than a denylist of the
#: obviously-bad ones, because the interesting schemes are the ones nobody
#: thinks to deny: `file:` is a filesystem read that bypasses the path sandbox
#: entirely, and `data:` makes the tool a laundering step for content the model
#: wrote itself.
_ALLOWED_SCHEMES: Final[frozenset[str]] = frozenset({"http", "https"})


class SandboxViolationError(Exception):
    """A path that resolves outside the workspace root.

    Carries a message written for the user, because it reaches them: §5 Phase 6
    requires this refusal to be visible in the event log as `tool.denied`, and
    that payload is what the Phase 7 dialog renders.
    """


class UrlNotAllowedError(Exception):
    """A URL `http_get` will not fetch. Same contract as its sibling above."""


@dataclass(frozen=True, slots=True)
class CheckedUrl:
    """A URL `http_get` may fetch, and the address that was checked.

    ``address`` is what the connection must be made to. The check resolved
    the name and looked at every answer; connecting by name again would ask
    the resolver a second time, and a second answer is the whole of the
    rebinding attack.
    """

    url: str
    #: The hostname as written — what the `Host` header and the TLS handshake
    #: carry, so the server sees the name the agent asked for.
    host: str
    #: The address the check saw, and the one to connect to.
    address: ipaddress.IPv4Address | ipaddress.IPv6Address


@dataclass(frozen=True, slots=True)
class Sandbox:
    """The workspace root, and the questions that can be asked about it.

    Frozen, and the root is resolved once in :meth:`__post_init__`. Both matter:
    a root that can be reassigned is a boundary a later refactor can move, and
    an *unresolved* root silently rejects everything on macOS, where `/var` is a
    symlink to `/private/var` — every candidate resolves to a path that is not
    relative to the root as written.
    """

    root: Path

    def __post_init__(self) -> None:
        # `object.__setattr__` because the dataclass is frozen; normalising an
        # input in `__post_init__` is the one legitimate use of it.
        object.__setattr__(self, "root", Path(self.root).expanduser().resolve())

    # --- paths -------------------------------------------------------------

    def resolve_path(self, candidate: str) -> Path:
        """Resolve ``candidate`` against the root, or refuse it.

        The returned path is absolute and guaranteed to be inside the root. It
        may not exist — `write_file` names its target before creating it, so
        requiring existence here would make the sandbox unusable by the one
        tool whose containment matters most.

        :raises SandboxViolationError: when the path resolves outside the root,
            is empty, or names an alternate data stream.
        """
        text = candidate.strip()
        if not text:
            msg = (
                "No path was given. Tools that take a path need one relative to "
                "the workspace, such as 'notes.txt'."
            )
            raise SandboxViolationError(msg)

        # A colon in a *relative* path is refused on every platform, and the
        # reason is Windows-specific: `notes.txt:hidden` writes an NTFS
        # alternate data stream. It stays inside the root, so containment does
        # not catch it, and almost no tool displays it — a tool reporting that
        # it wrote `notes.txt` would be lying to the user. It has to be checked
        # before joining, because `Path` drops the stream suffix on some
        # operations and it would vanish before the comparison.
        #
        # **Applied on POSIX too, where a colon is a legal filename character.**
        # That over-rejects `notes:2026.txt` on macOS, and the alternative is
        # worse: the workspace would accept a path on one platform and refuse it
        # on the other, so an agent definition that worked on the maintainer's
        # macOS build would fail on the Windows one it actually ships to (§1
        # constraint 7). One rule, stated in terms of what is portable.
        #
        # A drive letter is the legitimate colon and is absolute, so it falls
        # through to the containment check rather than being caught here.
        if ":" in text and not Path(text).is_absolute():
            msg = (
                f"{candidate!r} is not a valid workspace path: ':' is not "
                f"allowed in a file name, because on Windows it writes a hidden "
                f"alternate data stream rather than the file you named. Use a "
                f"plain name such as 'notes.txt'."
            )
            raise SandboxViolationError(msg)

        # An absolute candidate replaces the root under `/`, which is what we
        # want: it is then judged by where it actually points, not rejected for
        # being absolute. A path inside the root written absolutely is fine.
        joined = self.root / text

        try:
            resolved = joined.resolve()
        except (OSError, RuntimeError) as exc:
            # A resolution loop, or a path the OS refuses outright. Both are
            # refusals rather than crashes.
            msg = f"{candidate!r} is not a usable workspace path: {exc}"
            raise SandboxViolationError(msg) from exc

        if not resolved.is_relative_to(self.root):
            msg = (
                f"{candidate!r} is outside the workspace and cannot be reached. "
                f"Tools may only touch files under {self.root.name}{Path().anchor}, "
                f"using paths relative to it."
            )
            raise SandboxViolationError(msg)

        return resolved

    def relative(self, path: Path) -> str:
        """Render a resolved path the way a user should see it.

        The absolute path leaks the account name and the install location into
        approval prompts and event payloads. What a user needs is which file
        inside their workspace is about to be touched.
        """
        try:
            relative = path.resolve().relative_to(self.root)
        except (OSError, ValueError):
            return str(path)
        return str(relative) if str(relative) != "." else "."

    # --- urls --------------------------------------------------------------

    def check_url(self, candidate: str) -> str:
        """Return ``candidate`` if `http_get` may fetch it, else refuse.

        :meth:`resolve_url` without the address. Kept for callers that only
        need the yes or no.
        """
        return self.resolve_url(candidate).url

    def resolve_url(self, candidate: str) -> CheckedUrl:
        """Check ``candidate`` and say which address was checked.

        A literal address in a private, loopback, link-local or otherwise
        reserved range is refused, and so is a hostname any of whose addresses
        is one. The address handed back is the first the resolver gave — the
        operating system's preference — and every one of them passed.

        **Why the address travels with the answer.** A name can resolve to a
        public address when checked and a private one when the request is
        made — DNS rebinding — and a check that answered yes and then let the
        client resolve the name again had only raised the cost of reaching the
        LAN, not closed the way in. `http_get` therefore connects to
        ``address`` and carries ``host`` in the `Host` header and the TLS
        handshake, so the resolver is asked once, here, and the answer it gave
        is the connection that is made.

        :raises UrlNotAllowedError: for a bad scheme, a missing host, or a host
            that is or resolves to a non-public address.
        """
        try:
            parts = urlsplit(candidate.strip())
        except ValueError as exc:
            msg = f"{candidate!r} is not a URL that can be fetched: {exc}"
            raise UrlNotAllowedError(msg) from exc

        if parts.scheme not in _ALLOWED_SCHEMES:
            allowed = ", ".join(sorted(_ALLOWED_SCHEMES))
            msg = (
                f"{candidate!r} cannot be fetched: only {allowed} URLs are "
                f"allowed, and this one is {parts.scheme or 'not a URL'}."
            )
            raise UrlNotAllowedError(msg)

        try:
            hostname = parts.hostname
        except ValueError as exc:
            msg = f"{candidate!r} has a host that cannot be read: {exc}"
            raise UrlNotAllowedError(msg) from exc

        if not hostname:
            msg = f"{candidate!r} cannot be fetched: it names no host."
            raise UrlNotAllowedError(msg)

        addresses = self._addresses_for(hostname, candidate)
        for address in addresses:
            if not address.is_global:
                msg = (
                    f"{candidate!r} cannot be fetched: {hostname} is a "
                    f"loopback, private or otherwise local address "
                    f"({address}). Tools may only reach the public internet — "
                    f"this machine's own services, and the local network, are "
                    f"not reachable from inside a run."
                )
                raise UrlNotAllowedError(msg)

        if not addresses:
            msg = f"{candidate!r} cannot be fetched: {hostname} resolved to no address."
            raise UrlNotAllowedError(msg)

        return CheckedUrl(url=candidate.strip(), host=hostname, address=addresses[0])

    def _addresses_for(
        self, hostname: str, candidate: str
    ) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
        """Every address ``hostname`` currently stands for.

        A literal is used as given. A name is resolved, and *all* of its
        addresses are checked rather than the first: a host answering with one
        public and one private address would otherwise pass on a coin flip.
        """
        try:
            return [ipaddress.ip_address(hostname)]
        except ValueError:
            pass

        try:
            infos = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
        except OSError as exc:
            msg = (
                f"{candidate!r} cannot be fetched: {hostname} could not be "
                f"resolved ({exc.strerror or exc})."
            )
            raise UrlNotAllowedError(msg) from exc

        addresses: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
        for info in infos:
            sockaddr = info[4]
            if sockaddr:
                addresses.append(ipaddress.ip_address(str(sockaddr[0])))
        return addresses
