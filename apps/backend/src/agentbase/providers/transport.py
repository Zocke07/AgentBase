"""Shared HTTP plumbing for provider implementations.

Use raw HTTP: normalization is required either way, while vendor SDK trees in
a ``--onefile`` binary create hidden-import freeze issues. Never log bodies
(prompts) or headers (keys).
"""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
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

#: Allow large completions minutes, but bound hung requests that wedge runs.
DEFAULT_TIMEOUT_SECONDS: Final[float] = 120.0

_QUOTA_CODES: Final[frozenset[str]] = frozenset(
    {
        "insufficient_quota",
        "credit_balance_exhausted",
        "usage_limit_reached",
        "organization_usage_limit_exceeded",
        "billing_hard_limit_reached",
    }
)


def _retry_after(response: httpx2.Response) -> float | None:
    value = response.headers.get("retry-after")
    if not value:
        return None
    try:
        seconds = float(value)
    except ValueError:
        try:
            date = parsedate_to_datetime(value)
            if date.tzinfo is None:
                date = date.replace(tzinfo=UTC)
            seconds = (date - datetime.now(UTC)).total_seconds()
        except (ValueError, TypeError, OverflowError):
            return None
    return max(0.0, seconds) if math.isfinite(seconds) else None


def _quota_exhausted(response: httpx2.Response) -> bool:
    try:
        body = response.json()
    except ValueError:
        return False
    error = body.get("error") if isinstance(body, dict) else None
    if not isinstance(error, dict):
        return False
    return any(
        isinstance(code, str)
        and (code in _QUOTA_CODES or code.endswith("_spend_limit_exceeded"))
        for code in (error.get("code"), error.get("type"))
    )


def _raise_for_status(response: httpx2.Response, provider: str) -> None:
    """Map HTTP status to retryable/nonretryable provider errors without vendor types."""
    status = response.status_code
    if status < 400:
        return

    detail = _error_detail(response)

    if status in (401, 403):
        msg = f"{provider} rejected the API key ({status}): {detail}"
        raise ProviderAuthError(msg)

    if status == 429:
        quota = _quota_exhausted(response)
        msg = f"{provider} rate limited the request: {detail}"
        if quota:
            msg = f"{provider} has reached its usage or billing limit: {detail}"
        raise ProviderRateLimitedError(
            msg, retry_after_seconds=_retry_after(response), retryable=not quota
        )

    if status >= 500:
        msg = f"{provider} is unavailable ({status}): {detail}"
        raise ProviderUnavailableError(msg)

    msg = f"{provider} rejected the request ({status}): {detail}"
    raise ProviderError(msg)


def _error_detail(response: httpx2.Response) -> str:
    """Extract best-effort human-readable error reason; providers nest it differently."""
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
    """POST ``payload`` and return decoded JSON.

    :class:`ProviderUnavailableError` wraps transport failures.
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
    """POST and yield response lines.

    Read streamed error bodies before status handling so 401s retain reasons.
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
    """Yield decoded ``data:`` objects from Server-Sent Events.

    Ignore ``event:`` and read body discriminator so unknown chunk types are
    not silently dropped. Skip non-JSON framing (comments, separators, ``[DONE]``).
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
    """Yield decoded newline-delimited JSON objects.

    Malformed lines are errors: unlike framing, dropping one loses content.
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
