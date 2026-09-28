"""In-memory API keys delivered over stdin at spawn (§1 constraint 4).

Never use `argv`: every local process can read it. The shell writes one JSON
line after spawn::

    {"anthropic_api_key": "<from keychain>", "openai_api_key": "<from keychain>"}

stdin then becomes the shutdown watchdog. The watchdog thread consumes the
line, so a launch without one still binds; a missing key raises
:class:`ProviderAuthError` on first use. No repr exposes a key in a traceback.
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

#: Names the shell may send; ignore unknown keys.
SECRET_KEYS: Final[frozenset[str]] = frozenset(
    {
        "anthropic_api_key",
        "openai_api_key",
        # A bot token is also a credential: use this route, never `settings`.
        "discord_bot_token",
    }
)


def parse_secrets_line(line: str) -> dict[str, str]:
    """Parse a handshake line into known secrets.

    Non-object JSON, non-strings, and ``shutdown`` yield an empty mapping.
    Never raise or log the line.
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
    """Process-lifetime, memory-only API-key storage, locked across two threads."""

    __slots__ = ("_lock", "_secrets")

    def __init__(self, secrets: Mapping[str, str] | None = None) -> None:
        self._lock = threading.Lock()
        self._secrets: dict[str, str] = dict(secrets or {})

    def load(self, secrets: Mapping[str, str]) -> None:
        """Merge handshake secrets; log names, never values."""
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
        """Return present secret names; safe to log or expose over HTTP."""
        with self._lock:
            return tuple(sorted(self._secrets))

    def __repr__(self) -> str:
        """Stay value-free: default reprs can expose secrets in tracebacks."""
        return f"SecretStore(names={self.names!r})"

    __str__ = __repr__
