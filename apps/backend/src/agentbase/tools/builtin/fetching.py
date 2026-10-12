"""Bounded HTTPS reads at a checked address, shared by the market tools.

A request is checked before approval: :func:`checked_request` resolves the
URL's host once through the sandbox, which refuses private addresses, and
:func:`fetch_bytes` connects to that address while naming the host for TLS.
Redirects are never followed, and a body is read only up to a byte limit.
Later requests on the same checked host, such as one ticker after another,
reuse its address with a different fixed path.
"""

from __future__ import annotations

import json
import math
from typing import TYPE_CHECKING, Any, Final

import httpx2

from agentbase import __version__
from agentbase.tools.base import ToolExecutionError

if TYPE_CHECKING:
    from pathlib import Path

    from agentbase.tools.sandbox import Sandbox

__all__ = [
    "MAX_LOCAL_BYTES",
    "MAX_RESPONSE_BYTES",
    "USER_AGENT",
    "checked_request",
    "clean_text",
    "fetch_bytes",
    "finite_number",
    "json_object",
    "read_local",
    "write_json",
]

MAX_RESPONSE_BYTES: Final[int] = 2_000_000
MAX_LOCAL_BYTES: Final[int] = 1_000_000
USER_AGENT: Final[str] = f"AgentBase/{__version__} investment-research"
REQUEST_TIMEOUT_SECONDS: Final[float] = 20.0


def checked_request(sandbox: Sandbox, url: str) -> dict[str, str]:
    """The URL with its host and the public address it was checked at."""
    checked = sandbox.resolve_url(url)
    return {"url": checked.url, "host": checked.host, "address": str(checked.address)}


async def fetch_bytes(
    client: httpx2.AsyncClient,
    request: dict[str, str],
    *,
    url: str | None = None,
    maximum: int = MAX_RESPONSE_BYTES,
    user_agent: str = USER_AGENT,
) -> bytes:
    """GET ``url`` (default: the checked one) on the checked host and address."""
    target = httpx2.URL(url or request["url"])
    if target.host != request["host"] or target.scheme != "https":
        raise ToolExecutionError("Request is outside its approved HTTPS host.")
    try:
        async with client.stream(
            "GET",
            target.copy_with(host=request["address"]),
            headers={
                "host": request["host"],
                "user-agent": user_agent,
                "accept": "application/json, application/rss+xml, application/xml;q=0.9",
            },
            extensions={"sni_hostname": request["host"]},
            follow_redirects=False,
            timeout=REQUEST_TIMEOUT_SECONDS,
        ) as response:
            if response.status_code >= 300:
                raise ToolExecutionError(
                    f"{target} returned HTTP {response.status_code}; redirects are not followed."
                )
            advertised = response.headers.get("content-length", "")
            if advertised.isdigit() and int(advertised) > maximum:
                raise ToolExecutionError(
                    f"{target} exceeded the {maximum}-byte response limit."
                )
            chunks: list[bytes] = []
            size = 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > maximum:
                    raise ToolExecutionError(
                        f"{target} exceeded the {maximum}-byte response limit."
                    )
                chunks.append(chunk)
    except httpx2.HTTPError as exc:
        raise ToolExecutionError(f"{target} could not be fetched: {exc}") from exc
    return b"".join(chunks)


def json_object(body: bytes, source: str) -> dict[str, Any]:
    try:
        value = json.loads(body)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ToolExecutionError(f"{source} returned invalid JSON.") from exc
    if not isinstance(value, dict):
        raise ToolExecutionError(f"{source} must return a JSON object.")
    return value


def clean_text(value: Any, maximum: int = 200) -> str | None:
    """Collapsed, bounded text, or ``None`` for anything else or blank."""
    if not isinstance(value, str) or not value.strip():
        return None
    return " ".join(value.split())[:maximum]


def finite_number(value: Any) -> int | float | None:
    """A JSON number that is finite; ``None`` for booleans, text and the rest."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        return value if math.isfinite(value) else None
    except OverflowError:
        return None


def read_local(path: Path, maximum: int = MAX_LOCAL_BYTES) -> bytes:
    """A space file's bytes, empty when it does not exist."""
    if not path.exists():
        return b""
    if not path.is_file() or path.stat().st_size > maximum:
        raise ToolExecutionError(f"{path.name} is not a file below the local read limit.")
    return path.read_bytes()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
