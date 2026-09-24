"""`http_get`: the one tool that leaves the machine.

The URL goes through :meth:`~agentbase.tools.sandbox.Sandbox.resolve_url` in
`prepare`, which refuses `file:`, `data:` and every non-public address. The
connection is then made to the address that was checked, with the name in
the `Host` header and the SNI, so the resolver is asked once and DNS
rebinding has nothing to rebind.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

import httpx2

from agentbase.tools.base import Prepared, ToolArgumentError, ToolExecutionError
from agentbase.tools.catalogue import RiskLevel, lookup

if TYPE_CHECKING:
    from agentbase.tools.sandbox import Sandbox

__all__ = ["MAX_BODY_CHARS", "HttpGetTool"]

#: How much of a response body reaches the model and the event log.
MAX_BODY_CHARS: Final[int] = 20_000

#: A page that will not answer in half a minute is not worth a run's budget.
REQUEST_TIMEOUT_SECONDS: Final[float] = 30.0


class HttpGetTool:
    """Fetch a public URL and return its body as text."""

    name = "http_get"

    def __init__(self, client: httpx2.AsyncClient | None = None) -> None:
        #: Injected by tests through a `MockTransport`.
        self._client = client

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
                "url": {
                    "type": "string",
                    "description": (
                        "Full http:// or https:// URL to fetch. Must be a "
                        "public address: local and private addresses are "
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

        checked = sandbox.resolve_url(url)
        return Prepared(
            tool_name=self.name,
            summary=f"fetch {checked.url} over the internet",
            payload={"url": checked.url, "host": checked.host, "address": str(checked.address)},
            raw_arguments=dict(arguments),
        )

    async def execute(self, prepared: Prepared, sandbox: Sandbox) -> str:
        url: str = prepared.payload["url"]
        host: str = prepared.payload["host"]
        address: str = prepared.payload["address"]

        client = self._client
        owned = client is None
        if client is None:
            client = httpx2.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS)

        # Connect to the checked address; present the name. `httpx2` would set
        # `Host` from the URL (the address), so the header is given explicitly.
        parsed = httpx2.URL(url)
        pinned = parsed.copy_with(host=address)
        headers = {"host": host if parsed.port is None else f"{host}:{parsed.port}"}
        extensions: dict[str, Any] = {"sni_hostname": host} if parsed.scheme == "https" else {}

        try:
            response = await client.get(
                pinned, headers=headers, extensions=extensions, follow_redirects=False
            )
        except httpx2.HTTPError as exc:
            msg = f"{url} could not be fetched: {exc}"
            raise ToolExecutionError(msg) from exc
        finally:
            if owned:
                await client.aclose()

        if response.status_code >= 400:
            msg = f"{url} returned HTTP {response.status_code}."
            raise ToolExecutionError(msg)

        # Reported rather than followed: a `Location` header is how a checked
        # public URL becomes an unchecked private one. Asking again puts the
        # target through the check and the gate.
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
