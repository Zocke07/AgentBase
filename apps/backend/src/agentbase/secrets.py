"""API keys in memory, delivered over stdin at spawn (§1 constraint 4).

Never `argv`: a command line is readable by every process on the machine.
The shell writes one JSON line right after spawn::

    {"anthropic_api_key": "<from keychain>", "openai_api_key": "<from keychain>"}

and stdin then reverts to the shutdown watchdog. The line is consumed on the
watchdog thread, not at startup, so a launch that sends none still binds its
port, and a missing key surfaces as a :class:`ProviderAuthError` on first
use. Nothing here has a repr that could put a key in a traceback.
"""

from __future__ import annotations

import json
import logging
import threading
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["SECRET_KEYS", "SecretStore", "parse_secrets_line"]

logger = logging.getLogger("agentbase.secrets")

#: The names the shell may send; an unknown key is ignored rather than stored.
SECRET_KEYS: Final[frozenset[str]] = frozenset(
    {
        "anthropic_api_key",
        "openai_api_key",
        # A bot token is a credential in the same sense an API key is, so it
        # takes the same route and never touches the `settings` table.
        "discord_bot_token",
    }
)


def parse_secrets_line(line: str) -> dict[str, str]:
    """Parse one handshake line into a mapping of known secrets.

    Anything that is not a JSON object of strings (the ``shutdown`` sentinel
    included) yields an empty mapping. Never raises, never logs the line.
    """
    try:
        parsed = json.loads(line)
    except (json.JSONDecodeError, ValueError):
        return {}

    if not isinstance(parsed, dict):
        return {}

    secrets: dict[str, str] = {}
    for key, value in parsed.items():
        if key in SECRET_KEYS and isinstance(value, str) and value:
            secrets[key] = value

    return secrets


class SecretStore:
    """Process-lifetime storage for API keys: memory only, locked for two threads."""

    __slots__ = ("_lock", "_secrets")

    def __init__(self, secrets: Mapping[str, str] | None = None) -> None:
        self._lock = threading.Lock()
        self._secrets: dict[str, str] = dict(secrets or {})

    def load(self, secrets: Mapping[str, str]) -> None:
        """Merge in secrets from a handshake line, logging the names and never the values."""
        with self._lock:
            self._secrets.update(secrets)

        if secrets:
            logger.info("received %d secret(s): %s", len(secrets), ", ".join(sorted(secrets)))

    def get(self, name: str) -> str | None:
        with self._lock:
            return self._secrets.get(name)

    def has(self, name: str) -> bool:
        return self.get(name) is not None

    @property
    def names(self) -> tuple[str, ...]:
        """Which secrets are present. Safe to log and to expose over HTTP."""
        with self._lock:
            return tuple(sorted(self._secrets))

    def __repr__(self) -> str:
        """Deliberately value-free: a default repr is how a secret ends up in a traceback."""
        return f"SecretStore(names={self.names!r})"

    __str__ = __repr__
