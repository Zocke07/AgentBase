"""`http_get` — the one tool that leaves the machine.

Medium risk rather than low despite being a read, and the catalogue already
says why: it is the tool that can carry the contents of the workspace off the
machine, so a prompt-injected agent calling it is an exfiltration path rather
than a page view. The URL goes through
:meth:`agentspace.tools.sandbox.Sandbox.check_url` in `prepare`, which refuses
`file:`, `data:`, and every address that is not on the public internet —
including this application's own API on loopback.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

import httpx2

from agentspace.tools.base import Prepared, ToolArgumentError, ToolExecutionError
from agentspace.tools.catalogue import RiskLevel, lookup

if TYPE_CHECKING:
    from agentspace.tools.sandbox import Sandbox

__all__ = ["MAX_BODY_CHARS", "HttpGetTool"]

#: How much of a response body reaches the model and the event log. Same
#: reasoning as `read_file`: the transcript is repeated on every later turn.
MAX_BODY_CHARS: Final[int] = 20_000

#: Shorter than the provider timeout: a page that will not answer in half a
#: minute is not worth a run's wall-clock budget.
REQUEST_TIMEOUT_SECONDS: Final[float] = 30.0


class HttpGetTool:
    """Fetch a public URL and return its body as text."""

    name = "http_get"

    def __init__(self, client: httpx2.AsyncClient | None = None) -> None:
        #: Injected by tests through a `MockTransport`, exactly as the provider
        #: adapters take one. Nothing in the shipped app passes it.
        self._client = client

    @property
    def description(self) -> str:
        declaration = lookup(self.name)
        if declaration is None:  # pragma: no cover — pinned by a test
            msg = f"{self.name!r} has an implementation but no catalogue entry"
            raise RuntimeError(msg)
        return declaration.description

    @property
    def risk(self) -> RiskLevel:
        declaration = lookup(self.name)
        if declaration is None:  # pragma: no cover — pinned by a test
            msg = f"{self.name!r} has an implementation but no catalogue entry"
            raise RuntimeError(msg)
        return declaration.risk

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": (
                        "Full http:// or https:// URL to fetch. Must be a "
                        "public address — local and private addresses are "
                        "refused."
                    ),
                }
            },
            "required": ["url"],
        }

    def prepare(self, arguments: dict[str, Any], sandbox: Sandbox) -> Prepared:
        url = arguments.get("url")
        if url is None:
            msg = f"{self.name} needs a 'url' argument and none was given."
            raise ToolArgumentError(msg)
        if not isinstance(url, str):
            msg = f"{self.name}'s 'url' must be a string, not {type(url).__name__}."
            raise ToolArgumentError(msg)

        checked = sandbox.check_url(url)
        return Prepared(
            tool_name=self.name,
            summary=f"fetch {checked} over the internet",
            payload={"url": checked},
            raw_arguments=dict(arguments),
        )

    async def execute(self, prepared: Prepared, sandbox: Sandbox) -> str:
        url: str = prepared.payload["url"]

        client = self._client
        owned = client is None
        if client is None:
            client = httpx2.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS)

        try:
            response = await client.get(url, follow_redirects=False)
        except httpx2.HTTPError as exc:
            msg = f"{url} could not be fetched: {exc}"
            raise ToolExecutionError(msg) from exc
        finally:
            if owned:
                await client.aclose()

        if response.status_code >= 400:
            msg = f"{url} returned HTTP {response.status_code}."
            raise ToolExecutionError(msg)

        # Redirects are reported rather than followed. A redirect is how a
        # checked public URL becomes an unchecked private one — the sandbox
        # validated the address the agent named, and following a `Location`
        # header would fetch an address nothing validated. Handing the target
        # back lets the agent ask for it explicitly, which puts it through
        # `check_url` and the gate again.
        if 300 <= response.status_code < 400:
            location = response.headers.get("location", "(no Location header)")
            return (
                f"{url} redirected to {location} with HTTP "
                f"{response.status_code}. Redirects are not followed "
                f"automatically; call http_get again with that URL if you want it."
            )

        body = response.text
        if len(body) > MAX_BODY_CHARS:
            return (
                f"{body[:MAX_BODY_CHARS]}\n\n"
                f"[truncated: the response was {len(body)} characters and only "
                f"the first {MAX_BODY_CHARS} are shown]"
            )
        return body
