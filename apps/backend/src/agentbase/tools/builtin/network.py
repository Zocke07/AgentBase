"""The bounded network readers that leave the machine.

The URL goes through :meth:`~agentbase.tools.sandbox.Sandbox.resolve_url` in
`prepare`, which refuses `file:`, `data:` and every non-public address. The
connection is then made to the address that was checked, with the name in the
`Host` header and the SNI, so the resolver is asked once and DNS rebinding has
nothing to rebind. `http_get` returns bounded text; `read_feed` turns a larger
bounded RSS or Atom document into complete entries locally.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from typing import TYPE_CHECKING, Any, Final
from urllib.parse import urljoin, urlparse
from xml.etree.ElementTree import Element, ParseError

import httpx2
from defusedxml import ElementTree as SafeElementTree
from defusedxml.common import DefusedXmlException

from agentbase.tools.base import Prepared, ToolArgumentError, ToolExecutionError
from agentbase.tools.catalogue import RiskLevel, lookup

if TYPE_CHECKING:
    from agentbase.tools.sandbox import Sandbox

__all__ = [
    "DEFAULT_FEED_ENTRIES",
    "MAX_BODY_CHARS",
    "MAX_FEED_BYTES",
    "MAX_FEED_ENTRIES",
    "HttpGetTool",
    "ReadFeedTool",
]

#: How much of a response body reaches the model and the event log.
MAX_BODY_CHARS: Final[int] = 20_000

#: A page that will not answer in half a minute is not worth a run's budget.
REQUEST_TIMEOUT_SECONDS: Final[float] = 30.0

#: A feed is downloaded completely before parsing, but never without a hard
#: network-input ceiling. This is intentionally much larger than the text a
#: model sees: local parsing discards channel decoration and all but a bounded
#: number of complete entries.
MAX_FEED_BYTES: Final[int] = 2_000_000

#: Ten headlines per source is enough for a scanner run without multiplying a
#: watchlist into an enormous context. A caller can ask for more, but never more
#: than twenty complete entries from one feed.
DEFAULT_FEED_ENTRIES: Final[int] = 10
MAX_FEED_ENTRIES: Final[int] = 20

MAX_FEED_TITLE_CHARS: Final[int] = 500
MAX_FEED_SUMMARY_CHARS: Final[int] = 500
MAX_FEED_URL_CHARS: Final[int] = 2_048


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


class ReadFeedTool:
    """Fetch RSS or Atom and return complete, bounded, deterministic entries."""

    name = "read_feed"

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
                        "Full public http:// or https:// RSS or Atom URL. Local "
                        "and private addresses are refused."
                    ),
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": MAX_FEED_ENTRIES,
                    "description": (
                        f"Complete entries to return (default {DEFAULT_FEED_ENTRIES}, "
                        f"maximum {MAX_FEED_ENTRIES})."
                    ),
                },
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

        limit = arguments.get("limit", DEFAULT_FEED_ENTRIES)
        if isinstance(limit, bool) or not isinstance(limit, int):
            msg = f"{self.name}'s 'limit' must be an integer."
            raise ToolArgumentError(msg)
        if not 1 <= limit <= MAX_FEED_ENTRIES:
            msg = f"{self.name}'s 'limit' must be between 1 and {MAX_FEED_ENTRIES}."
            raise ToolArgumentError(msg)

        checked = sandbox.resolve_url(url)
        return Prepared(
            tool_name=self.name,
            summary=f"read up to {limit} complete entries from {checked.url}",
            payload={
                "url": checked.url,
                "host": checked.host,
                "address": str(checked.address),
                "limit": limit,
            },
            raw_arguments=dict(arguments),
        )

    async def execute(self, prepared: Prepared, sandbox: Sandbox) -> str:
        url: str = prepared.payload["url"]
        host: str = prepared.payload["host"]
        address: str = prepared.payload["address"]
        limit: int = prepared.payload["limit"]

        client = self._client
        owned = client is None
        if client is None:
            client = httpx2.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS)

        parsed = httpx2.URL(url)
        pinned = parsed.copy_with(host=address)
        headers = {
            "host": host if parsed.port is None else f"{host}:{parsed.port}",
            "accept": (
                "application/atom+xml, application/rss+xml, application/xml, text/xml;q=0.9"
            ),
        }
        extensions: dict[str, Any] = {"sni_hostname": host} if parsed.scheme == "https" else {}

        try:
            async with client.stream(
                "GET",
                pinned,
                headers=headers,
                extensions=extensions,
                follow_redirects=False,
            ) as response:
                if 300 <= response.status_code < 400:
                    location = response.headers.get("location", "(no Location header)")
                    msg = (
                        f"{url} redirected to {location} with HTTP {response.status_code}. "
                        "Redirects are not followed automatically; call read_feed again "
                        "with that URL if you want it."
                    )
                    raise ToolExecutionError(msg)
                if response.status_code >= 400:
                    msg = f"{url} returned HTTP {response.status_code}."
                    raise ToolExecutionError(msg)

                advertised = response.headers.get("content-length")
                if (
                    advertised is not None
                    and advertised.isdigit()
                    and int(advertised) > MAX_FEED_BYTES
                ):
                    msg = (
                        f"{url} declared a {advertised}-byte feed, above the "
                        f"{MAX_FEED_BYTES}-byte feed safety limit."
                    )
                    raise ToolExecutionError(msg)

                chunks: list[bytes] = []
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > MAX_FEED_BYTES:
                        msg = f"{url} is above the {MAX_FEED_BYTES}-byte feed safety limit."
                        raise ToolExecutionError(msg)
                    chunks.append(chunk)
        except ToolExecutionError:
            raise
        except httpx2.HTTPError as exc:
            msg = f"{url} could not be fetched: {exc}"
            raise ToolExecutionError(msg) from exc
        finally:
            if owned:
                await client.aclose()

        return json.dumps(
            _feed_document(b"".join(chunks), url=url, limit=limit),
            ensure_ascii=False,
            separators=(",", ":"),
        )


def _feed_document(body: bytes, *, url: str, limit: int) -> dict[str, Any]:
    try:
        root = SafeElementTree.fromstring(body)
    except (DefusedXmlException, ParseError) as exc:
        msg = f"{url} did not contain safe, well-formed RSS or Atom XML: {exc}"
        raise ToolExecutionError(msg) from exc

    root_kind = _local_name(root.tag)
    if root_kind not in {"feed", "rdf", "rss"}:
        msg = f"{url} is XML, but its root element is {root_kind!r}, not RSS or Atom."
        raise ToolExecutionError(msg)

    channel = next((child for child in root if _local_name(child.tag) == "channel"), root)
    title = _child_text(channel, ("title",))
    raw_items = [
        element for element in root.iter() if _local_name(element.tag) in {"entry", "item"}
    ]
    parsed_items = [
        entry
        for element in raw_items
        if (entry := _feed_entry(element, feed_url=url)) is not None
    ]
    deduplicated = _deduplicate_entries(parsed_items)
    selected = deduplicated[:limit]
    return {
        "feed_url": url,
        "feed_title": title or None,
        "fetched_at": datetime.now(UTC).isoformat(),
        "available_entries": len(raw_items),
        "valid_entries": len(parsed_items),
        "deduplicated_entries": len(deduplicated),
        "returned_entries": len(selected),
        "truncated": len(deduplicated) > len(selected),
        "entries": selected,
    }


def _feed_entry(element: Element, *, feed_url: str) -> dict[str, str | None] | None:
    title = _clip(_plain_text(_child_text(element, ("title",))), MAX_FEED_TITLE_CHARS)
    link = _absolute_http_url(_entry_link(element), base=feed_url)
    if title == "" or link == "":
        return None

    published = _published(_child_text(element, ("pubdate", "published", "updated", "date")))
    source_element = _child(element, ("source",))
    source_url = "" if source_element is None else source_element.attrib.get("url", "")
    source_name = "" if source_element is None else _element_text(source_element)
    description = _child_text(element, ("description", "summary", "content", "encoded"))
    summary = _clip(_plain_text(description), MAX_FEED_SUMMARY_CHARS)
    identifier = _sha1(f"{link}{title}")
    return {
        "id": identifier,
        "dedupe_key": _sha1(_normal_title(title)),
        "published": published,
        "source": _source_domain(source_url, link, source_name),
        "url": link,
        "title": title,
        "summary": summary,
    }


def _entry_link(element: Element) -> str:
    for child in element:
        if _local_name(child.tag) != "link":
            continue
        href = child.attrib.get("href", "").strip()
        relation = child.attrib.get("rel", "alternate")
        if href and relation in {"", "alternate"}:
            return href
        text = _element_text(child)
        if text:
            return text
    guid = _child_text(element, ("guid", "id"))
    return guid if guid.startswith(("http://", "https://")) else ""


def _absolute_http_url(value: str, *, base: str) -> str:
    if value == "":
        return ""
    joined = urljoin(base, value.strip())
    parsed = urlparse(joined)
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or parsed.hostname is None
        or len(joined) > MAX_FEED_URL_CHARS
    ):
        return ""
    return joined


def _deduplicate_entries(
    entries: list[dict[str, str | None]],
) -> list[dict[str, str | None]]:
    kept: list[dict[str, str | None]] = []
    for candidate in entries:
        duplicate_at: int | None = None
        for index, current in enumerate(kept):
            same_id = current["id"] == candidate["id"]
            same_title = current["dedupe_key"] == candidate["dedupe_key"]
            if same_id or (same_title and _within_one_day(current, candidate)):
                duplicate_at = index
                break
        if duplicate_at is None:
            kept.append(candidate)
            continue
        current = kept[duplicate_at]
        if _date_key(candidate["published"]) < _date_key(current["published"]):
            kept[duplicate_at] = candidate
    return kept


def _within_one_day(left: dict[str, str | None], right: dict[str, str | None]) -> bool:
    left_date = _iso_datetime(left["published"])
    right_date = _iso_datetime(right["published"])
    if left_date is None or right_date is None:
        return False
    return abs(left_date - right_date) <= timedelta(days=1)


def _date_key(value: str | None) -> datetime:
    return _iso_datetime(value) or datetime.max.replace(tzinfo=UTC)


def _iso_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _published(value: str) -> str | None:
    if value == "":
        return None
    parsed: datetime | None = None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _source_domain(source_url: str, link: str, source_name: str) -> str:
    for candidate in (source_url, link):
        host = urlparse(candidate).hostname
        if host:
            return host.removeprefix("www.").lower()
    return _clip(_plain_text(source_name), 200)


def _normal_title(value: str) -> str:
    without_source = re.sub(r"\s+-\s+[^-]{1,80}$", "", value.casefold())
    return " ".join(re.findall(r"[\w]+", without_source, flags=re.UNICODE))


def _sha1(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8"), usedforsecurity=False).hexdigest()


def _child(element: Element, names: tuple[str, ...]) -> Element | None:
    wanted = set(names)
    return next(
        (child for child in element if _local_name(child.tag) in wanted),
        None,
    )


def _child_text(element: Element, names: tuple[str, ...]) -> str:
    child = _child(element, names)
    return "" if child is None else _element_text(child)


def _element_text(element: Element) -> str:
    parts: list[str] = []

    def visit(node: Element) -> None:
        if _local_name(node.tag) in {"script", "style"}:
            if node.tail:
                parts.append(node.tail)
            return
        if node.text:
            parts.append(node.text)
        for child in node:
            visit(child)
        if node.tail:
            parts.append(node.tail)

    visit(element)
    return " ".join("".join(parts).split())


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


class _PlainTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style"}:
            self.ignored_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style"} and self.ignored_depth > 0:
            self.ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        if self.ignored_depth == 0:
            self.parts.append(data)


def _plain_text(value: str) -> str:
    parser = _PlainTextParser()
    parser.feed(value)
    parser.close()
    return " ".join(" ".join(parser.parts).split())


def _clip(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[:limit].rstrip()
