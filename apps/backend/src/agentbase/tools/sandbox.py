"""Sandbox boundaries checked before tools run or approval is requested.

Resolve paths before policy prompts, preventing traversal and symlink escapes.
Network tools may reach only public addresses; :meth:`Sandbox.resolve_url`
returns the checked address to prevent DNS rebinding.
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

#: ``run_shell`` timeout; caps commands waiting on input.
SHELL_TIMEOUT_SECONDS: Final[float] = 60.0

#: Fetchable schemes. ``file:`` bypasses the path sandbox; ``data:`` launders input.
_ALLOWED_SCHEMES: Final[frozenset[str]] = frozenset({"http", "https"})


class SandboxViolationError(Exception):
    """Path outside the workspace root; reported as ``tool.denied``."""


class UrlNotAllowedError(Exception):
    """URL refused by network tools; same contract as a path refusal."""


@dataclass(frozen=True, slots=True)
class CheckedUrl:
    """Fetchable URL and its checked address; connect to ``address`` to avoid rebinding."""

    url: str
    #: Original hostname for ``Host`` and TLS.
    host: str
    #: Checked address to connect to.
    address: ipaddress.IPv4Address | ipaddress.IPv6Address


@dataclass(frozen=True, slots=True)
class Sandbox:
    """Resolved workspace root and reachability checks."""

    root: Path

    def __post_init__(self) -> None:
        # Frozen dataclass requires ``object.__setattr__``.
        object.__setattr__(self, "root", Path(self.root).expanduser().resolve())

    # --- paths -------------------------------------------------------------

    def resolve_path(self, candidate: str) -> Path:
        """Resolve a candidate to a path inside the root.

        The result may not exist yet, for example before ``write_file`` creates it.

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

        # Refuse NTFS alternate data streams consistently across platforms.
        # Drive letters are absolute and use the containment check below.
        if ":" in text and not Path(text).is_absolute():
            msg = (
                f"{candidate!r} is not a valid workspace path: ':' is not "
                f"allowed in a file name, because on Windows it writes a hidden "
                f"alternate data stream rather than the file you named. Use a "
                f"plain name such as 'notes.txt'."
            )
            raise SandboxViolationError(msg)

        # Judge absolute candidates by containment, not their spelling.
        joined = self.root / text

        try:
            resolved = joined.resolve()
        except (OSError, RuntimeError) as exc:
            # Treat resolution loops and OS errors as a refusal.
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

    def resolve_write_path(self, candidate: str) -> Path:
        """Resolve a path an agent wants to write, refusing app-owned places.

        The top-level ``memory`` folder is where the inbox and run memories
        live, and hidden folders hold Obsidian's settings and the app's
        backups. A write there would skip the memory inbox, so it is refused
        before any policy can answer it. The check runs on the resolved path,
        so a link cannot rename its way in.

        :raises SandboxViolationError: for everything :meth:`resolve_path`
            refuses, and for an app-owned destination.
        """
        resolved = self.resolve_path(candidate)
        parts = resolved.relative_to(self.root).parts
        hidden = any(part.startswith(".") for part in parts)
        # Case-folded because Windows and macOS treat Memory/ as memory/.
        if hidden or (parts and parts[0].casefold() == "memory"):
            msg = (
                f"{candidate!r} is managed by AgentBase and agents cannot write "
                f"there. The memory folder and hidden folders such as .obsidian "
                f"hold the app's own records; to suggest a memory, use "
                f"propose_memory, which puts it in the inbox for review."
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
        """Return a fetchable URL without exposing its checked address."""
        return self.resolve_url(candidate).url

    def resolve_url(self, candidate: str) -> CheckedUrl:
        """Validate a public URL and return the address that was checked.

        Reject hosts with any non-public address; connecting to the returned
        address prevents a public-to-private DNS rebinding.

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
        """Resolve every address for ``hostname``; one private address rejects it."""
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
