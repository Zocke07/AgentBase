"""Shared HTTP plumbing for the provider implementations.

Raw HTTP rather than the vendor SDKs: normalizing usage and tool calls is
required either way, and two SDK dependency trees in a `--onefile` binary buy
hidden-import problems at freeze time. Nothing here logs a body or a header:
bodies carry prompts and headers carry the key.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Final

import httpx2

from agentbase.providers.base import (
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

#: Generous, since a large completion takes minutes; bounded, since a hung
#: request with no ceiling wedges the run with nothing to see.
DEFAULT_TIMEOUT_SECONDS: Final[float] = 120.0


def _raise_for_status(response: httpx2.Response, provider: str) -> None:
    """Map an HTTP status onto the provider error taxonomy: retryable or not, nothing vendor-
    specific.
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

    Every provider nests it somewhere different.
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

    Transport failures become :class:`ProviderUnavailableError`.
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

    On a streamed error the body is unread when the status arrives, so it is
    ``aread()`` first or the 401 reports an empty reason.
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

    The ``event:`` line is ignored and the discriminator read from the body,
    so a chunk type this adapter was not written for is not silently dropped.
    Non-JSON lines (comments, separators, ``[DONE]``) are framing and skipped.
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

    A malformed line is an error here: NDJSON has no framing to skip, so
    dropping one would lose content rather than a keep-alive.
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
