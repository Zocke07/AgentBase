"""Where a tool call may reach, decided before anything runs or anyone is asked.

A path outside the workspace root is refused before an approval prompt is
composed (§5 Phase 6): a dialog asking whether an agent may write to
`../../etc/hosts` puts the user one misclick from the thing the sandbox exists
to prevent. This module answers one question, *is this reachable?*, with no
reference to risk, policy or who is asking.

Every check compares fully resolved paths. A string search for `".."` rejects
the legitimate `reports/../notes.txt` and misses a symlink, which is the escape
that works; :meth:`Path.resolve` covers traversal, symlinks, drive letters and
UNC paths in one comparison.

For `http_get`, the machine's own services are inside the boundary: without
:meth:`Sandbox.check_url` an agent can read this application's API from inside
a run. :meth:`Sandbox.resolve_url` also hands back the address it checked so
the tool connects to that one rather than resolving the name again.
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

#: How long `run_shell` may run before it is killed: long enough for a build,
#: short enough that a command waiting on input does not eat the run's budget.
SHELL_TIMEOUT_SECONDS: Final[float] = 60.0

#: Schemes `http_get` will fetch. An allowlist: `file:` is a filesystem read
#: that bypasses the path sandbox, and `data:` launders the model's own text.
_ALLOWED_SCHEMES: Final[frozenset[str]] = frozenset({"http", "https"})


class SandboxViolationError(Exception):
    """A path that resolves outside the workspace root.

    The message reaches the user via `tool.denied`.
    """


class UrlNotAllowedError(Exception):
    """A URL `http_get` will not fetch. Same contract as :class:`SandboxViolationError`."""


@dataclass(frozen=True, slots=True)
class CheckedUrl:
    """A URL `http_get` may fetch, and the address that was checked.

    The connection must be made to ``address``: resolving the name again
    would give a second answer, which is the whole of a rebinding attack.
    """

    url: str
    #: The hostname as written, for the `Host` header and the TLS handshake.
    host: str
    #: The address the check saw, and the one to connect to.
    address: ipaddress.IPv4Address | ipaddress.IPv6Address


@dataclass(frozen=True, slots=True)
class Sandbox:
    """The workspace root, and the questions that can be asked about it.

    The root is resolved once, in :meth:`__post_init__`: an unresolved root
    rejects everything on macOS, where `/var` is a symlink to `/private/var`.
    """

    root: Path

    def __post_init__(self) -> None:
        # `object.__setattr__` because the dataclass is frozen.
        object.__setattr__(self, "root", Path(self.root).expanduser().resolve())

    # --- paths -------------------------------------------------------------

    def resolve_path(self, candidate: str) -> Path:
        """Resolve ``candidate`` against the root, or refuse it.

        The result is absolute and inside the root. It need not exist:
        `write_file` names its target before creating it.

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

        # A colon in a relative path is refused on every platform: on Windows
        # `notes.txt:hidden` writes an NTFS alternate data stream, inside the
        # root and invisible to most tools. Checked before joining, because
        # `Path` drops the suffix on some operations. Applied on POSIX too, so
        # a definition that works on one platform does not fail on the other.
        # A drive letter is absolute and falls through to the containment check.
        if ":" in text and not Path(text).is_absolute():
            msg = (
                f"{candidate!r} is not a valid workspace path: ':' is not "
                f"allowed in a file name, because on Windows it writes a hidden "
                f"alternate data stream rather than the file you named. Use a "
                f"plain name such as 'notes.txt'."
            )
            raise SandboxViolationError(msg)

        # An absolute candidate replaces the root under `/`: it is judged by
        # where it points, not rejected for being absolute.
        joined = self.root / text

        try:
            resolved = joined.resolve()
        except (OSError, RuntimeError) as exc:
            # A resolution loop, or a path the OS refuses: a refusal, not a crash.
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
        """Render a resolved path relative to the root, for prompts and payloads."""
        try:
            relative = path.resolve().relative_to(self.root)
        except (OSError, ValueError):
            return str(path)
        return str(relative) if str(relative) != "." else "."

    # --- urls --------------------------------------------------------------

    def check_url(self, candidate: str) -> str:
        """Return ``candidate`` if `http_get` may fetch it, else refuse.

        :meth:`resolve_url` without the address.
        """
        return self.resolve_url(candidate).url

    def resolve_url(self, candidate: str) -> CheckedUrl:
        """Check ``candidate`` and say which address was checked.

        A private, loopback, link-local or reserved address is refused, and
        so is a hostname any of whose addresses is one. The address handed
        back is the resolver's first, and every one of them passed. It
        travels with the answer because a name can resolve public when checked
        and private when connected (DNS rebinding); `http_get` connects to it
        and carries ``host`` in the `Host` header and the TLS handshake.

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
                    f"({address}). Tools may only reach the public internet: "
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
        """Every address ``hostname`` stands for: all of them, so a host with one
        public and one private address does not pass on a coin flip."""
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
