"""Shared HTTP plumbing for the provider implementations.

Every provider talks to a JSON-over-HTTP endpoint, and the parts that are the
same for all of them (client lifetime, timeouts, and turning transport and
status failures into the :mod:`agentspace.providers.base` error taxonomy) live
here so the three implementations differ only where the *vendors* differ.

**Why raw HTTP rather than the vendor SDKs.** Normalizing token usage and tool
calls is required either way (§5 Phase 3 asks for a single protocol), so the
SDKs would save little; they would add two large dependency trees to a
PyInstaller `--onefile` binary that has to stay startable, and each brings its
own hidden-import problems at freeze time. One client, three thin adapters.

**Nothing here logs a request body or a header.** Bodies carry prompts and
headers carry the API key, and the Tauri shell pipes the sidecar's stderr
straight to its own console (§1 constraint 4).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Final

import httpx2

from agentspace.providers.base import (
    ProviderAuthError,
    ProviderError,
    ProviderRateLimitedError,
    ProviderUnavailableError,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping

__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "post_json",
    "stream_ndjson",
    "stream_sse",
]

#: Generous, because a large completion legitimately takes minutes, but not
#: unbounded, because a hung request with no ceiling wedges the run forever and
#: the user has no way to see why.
DEFAULT_TIMEOUT_SECONDS: Final[float] = 120.0


def _raise_for_status(response: httpx2.Response, provider: str) -> None:
    """Map an HTTP status onto the provider error taxonomy.

    The mapping is deliberately coarse: callers above this layer branch on
    retryable versus not, and nothing above it should be reading vendor error
    codes: that would be a code change on switching provider.
    """
    status = response.status_code
    if status < 400:
        return

    detail = _error_detail(response)

    if status in (401, 403):
        msg = f"{provider} rejected the API key ({status}): {detail}"
        raise ProviderAuthError(msg)

    if status == 429:
        retry_after = response.headers.get("retry-after")
        seconds: float | None = None
        if retry_after:
            try:
                seconds = float(retry_after)
            except ValueError:
                seconds = None
        msg = f"{provider} rate limited the request: {detail}"
        raise ProviderRateLimitedError(msg, retry_after_seconds=seconds)

    if status >= 500:
        msg = f"{provider} is unavailable ({status}): {detail}"
        raise ProviderUnavailableError(msg)

    msg = f"{provider} rejected the request ({status}): {detail}"
    raise ProviderError(msg)


def _error_detail(response: httpx2.Response) -> str:
    """Best-effort human-readable reason from an error body.

    Every provider nests its message somewhere different, and a provider that
    returns HTML or nothing at all must not turn into a `KeyError` that hides
    the real status code.
    """
    try:
        body: Any = response.json()
    except ValueError:
        return response.text[:200].strip() or "no response body"

    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str):
                return message
        if isinstance(error, str):
            return error
        message = body.get("message")
        if isinstance(message, str):
            return message

    return str(body)[:200]


async def post_json(
    client: httpx2.AsyncClient,
    url: str,
    payload: Mapping[str, Any],
    headers: Mapping[str, str],
    provider: str,
) -> dict[str, Any]:
    """POST ``payload`` and return the decoded JSON object.

    Transport failures become :class:`ProviderUnavailableError` rather than leaking
    an ``httpx2`` exception: a caller that had to catch those would be coupled
    to this module's choice of HTTP client.
    """
    try:
        response = await client.post(url, json=dict(payload), headers=dict(headers))
    except httpx2.TimeoutException as exc:
        msg = f"{provider} timed out after {DEFAULT_TIMEOUT_SECONDS:.0f}s"
        raise ProviderUnavailableError(msg) from exc
    except httpx2.HTTPError as exc:
        msg = f"could not reach {provider}: {exc}"
        raise ProviderUnavailableError(msg) from exc

    _raise_for_status(response, provider)

    try:
        body: Any = response.json()
    except ValueError as exc:
        msg = f"{provider} returned a non-JSON body"
        raise ProviderError(msg) from exc

    if not isinstance(body, dict):
        msg = f"{provider} returned {type(body).__name__}, expected a JSON object"
        raise ProviderError(msg)

    return body


async def _stream_lines(
    client: httpx2.AsyncClient,
    url: str,
    payload: Mapping[str, Any],
    headers: Mapping[str, str],
    provider: str,
) -> AsyncIterator[str]:
    """POST and yield response lines as they arrive.

    The error mapping is the same as :func:`post_json`, with one wrinkle that
    is easy to get wrong: on a streamed response the body has not been read
    when the status arrives, so ``response.json()`` inside ``_error_detail``
    would raise instead of explaining the failure. ``aread()`` first, and a 401
    reports the vendor's reason rather than an empty string.
    """
    try:
        async with client.stream(
            "POST", url, json=dict(payload), headers=dict(headers)
        ) as response:
            if response.status_code >= 400:
                await response.aread()
                _raise_for_status(response, provider)

            async for line in response.aiter_lines():
                yield line
    except httpx2.TimeoutException as exc:
        msg = f"{provider} timed out after {DEFAULT_TIMEOUT_SECONDS:.0f}s"
        raise ProviderUnavailableError(msg) from exc
    except httpx2.HTTPError as exc:
        msg = f"could not reach {provider}: {exc}"
        raise ProviderUnavailableError(msg) from exc


async def stream_sse(
    client: httpx2.AsyncClient,
    url: str,
    payload: Mapping[str, Any],
    headers: Mapping[str, str],
    provider: str,
) -> AsyncIterator[dict[str, Any]]:
    """Yield the decoded ``data:`` objects of a Server-Sent Events response.

    The ``event:`` line is deliberately ignored and the discriminator is read
    from the JSON body instead: the same decision, for the same reason, that
    this project's own SSE stream makes (see CLAUDE.md, Phase 2): a reader
    keyed on the event *name* silently drops any type it was not written to
    expect, and both vendors add new chunk types without warning.

    Non-JSON lines are skipped rather than raised on. SSE comments (`: ping`),
    blank separators and OpenAI's ``[DONE]`` sentinel are all framing, not
    content, and a stream must not die because a keep-alive arrived.
    """
    async for line in _stream_lines(client, url, payload, headers, provider):
        if not line.startswith("data:"):
            continue

        data = line[len("data:") :].strip()
        if not data or data == "[DONE]":
            continue

        try:
            parsed: Any = json.loads(data)
        except ValueError:
            continue

        if isinstance(parsed, dict):
            yield parsed


async def stream_ndjson(
    client: httpx2.AsyncClient,
    url: str,
    payload: Mapping[str, Any],
    headers: Mapping[str, str],
    provider: str,
) -> AsyncIterator[dict[str, Any]]:
    """Yield the decoded objects of a newline-delimited JSON response.

    Unlike :func:`stream_sse` a malformed line is an error here. NDJSON has no
    framing lines to skip, so anything unparseable is the vendor sending
    something this adapter does not understand, and silently dropping it would
    lose response content rather than a keep-alive.
    """
    async for line in _stream_lines(client, url, payload, headers, provider):
        stripped = line.strip()
        if not stripped:
            continue

        try:
            parsed: Any = json.loads(stripped)
        except ValueError as exc:
            msg = f"{provider} returned a non-JSON line in a streamed response"
            raise ProviderError(msg) from exc

        if not isinstance(parsed, dict):
            msg = f"{provider} streamed {type(parsed).__name__}, expected a JSON object"
            raise ProviderError(msg)

        yield parsed
