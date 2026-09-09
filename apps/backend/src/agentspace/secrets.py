"""API keys in memory, delivered over stdin at spawn.

§1 constraint 4: keys live in the OS keychain and reach the sidecar over stdin
— never `.env`, never SQLite, never a config file, never a log line, never
`argv`. The last one is the reason for the whole mechanism: on Windows,
`Get-CimInstance Win32_Process` shows every process's full command line to any
user on the machine, and the POSIX equivalent is `ps`. A key passed as an
argument is world-readable for the life of the process.

**The wire protocol.** The Tauri shell writes exactly one line of JSON to the
sidecar's stdin immediately after spawn::

    {"anthropic_api_key": "<from keychain>", "openai_api_key": "<from keychain>"}

After that line, stdin reverts to the role Phase 1 gave it: the shutdown
watchdog, which stops the server on the literal line ``shutdown`` or on EOF.
The two uses do not conflict because the handshake consumes exactly one line
and the sentinel is not valid JSON.

**Why this is read on the watchdog thread rather than at startup.** A blocking
read for the secrets line in `run()` would hang any launch that does not write
one — `python -m agentspace` by hand, or a shell that crashed between spawn and
write — turning a missing key into a sidecar that never binds its port and
never explains why. The line is consumed by the same thread that then watches
for shutdown, so the server starts regardless and a key that never arrives
surfaces as a legible :class:`ProviderAuthError` on first use instead.

**Nothing here has a useful ``__repr__``.** A dataclass repr of this object in
a traceback would put the key in the Tauri console, which is the same leak by a
different route.
"""

from __future__ import annotations

import json
import logging
import threading
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["SECRET_KEYS", "SecretStore", "parse_secrets_line"]

logger = logging.getLogger("agentspace.secrets")

#: The names the shell may send. An unknown key is ignored rather than stored,
#: so a shell bug cannot fill memory with arbitrary attacker-supplied content.
SECRET_KEYS: Final[frozenset[str]] = frozenset(
    {
        "anthropic_api_key",
        "openai_api_key",
    }
)


def parse_secrets_line(line: str) -> dict[str, str]:
    """Parse one handshake line into a mapping of known secrets.

    Returns an empty mapping for anything that is not a JSON object of strings
    — including the ``shutdown`` sentinel, so that a shell which sends no
    secrets at all still shuts down correctly.

    Never raises, and never logs the line: a parse failure is reported by
    *count*, because the content is exactly what must not be written down.
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
    """Process-lifetime storage for API keys. Thread-safe, memory only.

    Written by the stdin watchdog thread and read by request handlers on the
    event loop, hence the lock.
    """

    __slots__ = ("_lock", "_secrets")

    def __init__(self, secrets: Mapping[str, str] | None = None) -> None:
        self._lock = threading.Lock()
        self._secrets: dict[str, str] = dict(secrets or {})

    def load(self, secrets: Mapping[str, str]) -> None:
        """Merge in secrets from a handshake line.

        Logs the *names* received, never the values — knowing that a key
        arrived is necessary to debug a missing-credential report, and its
        content never is.
        """
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
        """Which secrets are present. Safe to log and to expose over HTTP —
        the settings endpoint uses it so the UI can show "key configured"
        without ever reading the key back out."""
        with self._lock:
            return tuple(sorted(self._secrets))

    def __repr__(self) -> str:
        """Deliberately value-free.

        The default dataclass-style repr is how a secret ends up in a
        traceback, and the Tauri shell pipes this process's stderr straight to
        its own console.
        """
        return f"SecretStore(names={self.names!r})"

    __str__ = __repr__
