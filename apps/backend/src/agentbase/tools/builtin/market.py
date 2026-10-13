"""Bounded Yahoo market discovery, company metadata and headline evidence.

All hosts and output paths are checked before approval. Dynamic requests only
substitute validated ticker symbols into fixed paths on the checked hosts;
redirects and URLs embedded in fetched text are never followed.
"""

from __future__ import annotations

import asyncio
import csv
import json
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import httpx2

from agentbase.tools.base import Prepared, ToolArgumentError, ToolExecutionError
from agentbase.tools.builtin.fetching import (
    MAX_RESPONSE_BYTES,
    checked_request,
    clean_text,
    fetch_bytes,
    finite_number,
    json_object,
    read_local,
    write_json,
)
from agentbase.tools.builtin.network import deduplicate_entries, feed_document
from agentbase.tools.catalogue import RiskLevel, lookup

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from agentbase.tools.sandbox import Sandbox

__all__ = [
    "FEED_HOST",
    "MAX_MARKET_BYTES",
    "YAHOO_HOST",
    "ReadMarketTool",
    "feed_url",
    "parse_symbols",
]

YAHOO_HOST: Final[str] = "query1.finance.yahoo.com"
FEED_HOST: Final[str] = "feeds.finance.yahoo.com"
MAX_SYMBOLS: Final[int] = 50
MAX_MARKET_BYTES: Final[int] = MAX_RESPONSE_BYTES
MAX_NEWS: Final[int] = 40
#: A day's news file also keeps what earlier collections that day saved, up to this.
MAX_DAY_NEWS: Final[int] = 200
_MAX_NEWS_FILE_BYTES: Final[int] = 5_000_000
SCREENERS: Final[tuple[str, ...]] = ("day_gainers", "day_losers", "most_actives")
_SYMBOL: Final[re.Pattern[str]] = re.compile(r"^[A-Z0-9][A-Z0-9._-]{0,19}$")
_NEWS_SYMBOL: Final[re.Pattern[str]] = re.compile(
    r"\b(?:NASDAQ(?:GS|GM|CM)?|NYSE|AMEX)\s*:\s*([A-Z][A-Z0-9.-]{0,9})\b"
    r"|\$([A-Z][A-Z0-9.-]{0,9})\b|\(([A-Z][A-Z0-9.-]{1,9})\)"
)


def _declaration(name: str) -> tuple[str, RiskLevel]:
    declaration = lookup(name)
    if declaration is None:  # pragma: no cover: catalogue test pins this
        raise RuntimeError(f"{name!r} has an implementation but no catalogue entry")
    return declaration.description, declaration.risk


def parse_symbols(value: Any, *, required: bool, maximum: int = MAX_SYMBOLS) -> list[str]:
    if value is None and not required:
        return []
    if not isinstance(value, list) or (required and not value):
        raise ToolArgumentError("symbols must be a non-empty array of ticker strings.")
    if len(value) > maximum:
        raise ToolArgumentError(f"At most {maximum} symbols are accepted.")
    result: list[str] = []
    for candidate in value:
        if not isinstance(candidate, str):
            raise ToolArgumentError("Every symbol must be a string.")
        symbol = candidate.strip().upper()
        if _SYMBOL.fullmatch(symbol) is None:
            raise ToolArgumentError(f"{candidate!r} is not a supported equity ticker.")
        if symbol != "CASH" and symbol not in result:
            result.append(symbol)
    return result


def _write_news(path: Path, rows: list[dict[str, Any]]) -> int:
    """Write the day's headlines, newest first, after keeping those an earlier
    collection that day saved; returns how many were kept.

    Theses cite a headline by its id. On 2026-10-13 a second collection on the
    same New York date replaced the file, and a cited headline was gone.
    """
    seen = {row["id"] for row in rows}
    earlier: list[dict[str, Any]] = []
    if path.is_file() and path.stat().st_size <= _MAX_NEWS_FILE_BYTES:
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if (
                isinstance(row, dict)
                and isinstance(row.get("id"), str)
                and row["id"] not in seen
            ):
                seen.add(row["id"])
                earlier.append(row)
    kept = earlier[: max(0, MAX_DAY_NEWS - len(rows))]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in [*rows, *kept]),
        encoding="utf-8",
    )
    return len(kept)


class ReadMarketTool:
    """Discover equities in predefined US screeners and published Yahoo headlines."""

    name = "read_market"

    def __init__(
        self,
        client: httpx2.AsyncClient | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._client = client
        self._clock = clock or (lambda: datetime.now(UTC))

    @property
    def description(self) -> str:
        return _declaration(self.name)[0]

    @property
    def risk(self) -> RiskLevel:
        return _declaration(self.name)[1]

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "symbols": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": MAX_SYMBOLS,
                    "description": "Optional extra equities; held and watched stocks are included.",
                },
                "limit_per_list": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 10,
                    "description": "Candidates per Yahoo list; defaults to market.limit_per_list or five.",
                },
            },
            "additionalProperties": False,
        }

    def prepare(self, arguments: dict[str, Any], sandbox: Sandbox) -> Prepared:
        symbols = parse_symbols(arguments.get("symbols"), required=False)
        sources_path = sandbox.resolve_path("config/sources.json")
        try:
            sources_body = read_local(sources_path)
            sources = json_object(sources_body, "config/sources.json") if sources_body else {}
            market = sources.get("market", {})
            if not isinstance(market, dict):
                raise ToolArgumentError("config/sources.json market must be an object.")
            limit = arguments.get("limit_per_list", market.get("limit_per_list", 5))
        except (OSError, ToolExecutionError) as exc:
            raise ToolArgumentError(
                f"Could not read market source configuration: {exc}"
            ) from exc
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 10:
            raise ToolArgumentError("limit_per_list must be an integer between 1 and 10.")
        now = self._clock().astimezone(UTC)
        date = now.astimezone(ZoneInfo("America/New_York")).date().isoformat()
        screeners = {
            name: checked_request(
                sandbox,
                f"https://{YAHOO_HOST}/v1/finance/screener/predefined/saved?"
                + urlencode({"formatted": "false", "scrIds": name, "count": limit}),
            )
            for name in SCREENERS
        }
        feed = checked_request(sandbox, feed_url(["^GSPC", "^IXIC", "^DJI"]))
        metadata = checked_request(sandbox, _search_url("MSFT"))
        return Prepared(
            tool_name=self.name,
            summary=(
                f"read Yahoo's US gainers, losers and volume leaders (up to {limit} each), "
                "company sectors and headlines, including held and watched stocks"
            ),
            payload={
                "host": YAHOO_HOST,
                "hosts": [YAHOO_HOST, FEED_HOST],
                "symbols": symbols,
                "limit": limit,
                "as_of": date,
                "fetched_at": now.isoformat(),
                "screeners": screeners,
                "feed": feed,
                "metadata": metadata,
                "watchlist_path": sandbox.resolve_path("config/watchlist.json"),
                "positions_path": sandbox.resolve_path("portfolio/positions.csv"),
                "sources_path": sources_path,
                "universe_path": sandbox.resolve_write_path("raw/market/universe.json"),
                "screeners_path": sandbox.resolve_write_path(
                    f"raw/market/screeners-{date}.json"
                ),
                "news_path": sandbox.resolve_write_path(f"raw/news-{date}.jsonl"),
            },
            raw_arguments=dict(arguments),
        )

    async def execute(self, prepared: Prepared, sandbox: Sandbox) -> str:
        payload = prepared.payload
        warnings: list[str] = []
        universe = await asyncio.to_thread(_configured_universe, payload, warnings)
        client = self._client or httpx2.AsyncClient(timeout=20)
        try:
            screeners, news = await _collect_market(client, payload, universe, warnings)
            hints = _headline_symbols(news)
            for symbol in hints:
                if symbol not in universe and len(universe) < MAX_SYMBOLS:
                    universe[symbol] = _company(symbol, "headline_candidate")
            await _metadata(client, payload["metadata"], universe, warnings)
            # Headline hints are included only after Yahoo confirms an exact equity symbol.
            universe = {
                symbol: row
                for symbol, row in universe.items()
                if row["origins"] != ["headline_candidate"] or row.get("verified_equity")
            }
            for row in universe.values():
                if row["origins"] == ["headline_candidate"]:
                    row["origins"] = ["headline"]
            if universe:
                try:
                    url = feed_url(list(universe))
                    body = await fetch_bytes(client, payload["feed"], url=url)
                    news.extend(feed_document(body, url=url, limit=20)["entries"])
                except ToolExecutionError as exc:
                    warnings.append(f"Company headlines unavailable: {exc}")
        finally:
            if self._client is None:
                await client.aclose()

        rows = sorted(universe.values(), key=lambda row: row["ticker"])
        records: list[dict[str, Any]] = []
        for entry in deduplicate_entries(news)[:MAX_NEWS]:
            text = f"{entry['title']} {entry.get('summary') or ''}"
            matched = [row["ticker"] for row in rows if _mentions(text, row)]
            fields = {key: value for key, value in entry.items() if key != "dedupe_key"}
            records.append(
                {
                    **fields,
                    "as_of": payload["fetched_at"],
                    "collected_from": FEED_HOST,
                    "tickers": matched,
                    "summary": " ".join((entry.get("summary") or "").split()[:40]),
                    # A feed headline is not classified; the analysts weigh it.
                    "claim_type": "unclassified",
                    "engagement": {"score": None, "comments": None},
                }
            )
        if not records:
            warnings.append("No Yahoo headlines were available; do not invent news evidence.")
        unknown = [row["ticker"] for row in rows if not row.get("sector")]
        if unknown:
            warnings.append(
                "Sector unavailable for " + ", ".join(unknown) + "; sector risk is unknown."
            )
        document = {
            "as_of": payload["as_of"],
            "fetched_at": payload["fetched_at"],
            "scope": "Yahoo predefined US equity screeners; provider size/liquidity filters apply.",
            "symbols": [row["ticker"] for row in rows],
            "universe": rows,
            "warnings": warnings,
        }
        await asyncio.to_thread(write_json, payload["universe_path"], document)
        await asyncio.to_thread(write_json, payload["screeners_path"], screeners)
        kept = await asyncio.to_thread(_write_news, payload["news_path"], records)
        return json.dumps(
            {
                **document,
                "screeners": screeners,
                "news_count": len(records),
                "earlier_news_kept": kept,
                "universe_path": sandbox.relative(payload["universe_path"]),
                "news_path": sandbox.relative(payload["news_path"]),
                "written": [
                    sandbox.relative(payload[key])
                    for key in ("universe_path", "screeners_path", "news_path")
                ],
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )


def _company(symbol: str, origin: str) -> dict[str, Any]:
    return {
        "ticker": symbol,
        "name": None,
        "company_name": None,
        "aliases": [],
        "sector": None,
        "industry": None,
        "currency": None,
        "origins": [origin],
    }


def _configured_universe(
    payload: dict[str, Any], warnings: list[str]
) -> dict[str, dict[str, Any]]:
    universe: dict[str, dict[str, Any]] = {}
    try:
        positions_content = read_local(payload["positions_path"]).decode("utf-8-sig")
        for row in csv.DictReader(positions_content.splitlines()):
            symbol = (row.get("ticker") or "").strip().upper()
            if symbol == "CASH":
                continue
            if _SYMBOL.fullmatch(symbol) is None:
                warnings.append(f"Invalid held ticker {symbol!r}; it was not requested.")
                continue
            company = _company(symbol, "holding")
            company["sector"] = clean_text(row.get("sector"))
            company["currency"] = clean_text(row.get("currency"))
            universe[symbol] = company
    except (ToolExecutionError, OSError, UnicodeDecodeError, csv.Error) as exc:
        warnings.append(f"Some held stocks could not be read: {exc}")
    try:
        watchlist_content = read_local(payload["watchlist_path"])
        document = (
            json_object(watchlist_content, "config/watchlist.json") if watchlist_content else {}
        )
        rows = document.get("watchlist", [])
        if not isinstance(rows, list):
            raise ToolExecutionError("config/watchlist.json needs a watchlist array.")
        for row in rows[:MAX_SYMBOLS]:
            if not isinstance(row, dict):
                raise ToolExecutionError("Each watchlist entry must be an object.")
            raw_symbol = row.get("ticker", row.get("symbol", ""))
            symbol = raw_symbol.strip().upper() if isinstance(raw_symbol, str) else ""
            if _SYMBOL.fullmatch(symbol) is None or symbol == "CASH":
                warnings.append(f"Invalid watched ticker {symbol!r}; it was not requested.")
                continue
            company = universe.setdefault(symbol, _company(symbol, "watchlist"))
            if "watchlist" not in company["origins"]:
                company["origins"].append("watchlist")
            company_name = clean_text(row.get("company_name")) or clean_text(row.get("name"))
            if company_name:
                company["company_name"] = company_name
                company["name"] = company_name
            aliases = row.get("aliases", [])
            if isinstance(aliases, list):
                company["aliases"] = [
                    alias
                    for value in aliases[:20]
                    if (alias := clean_text(value, 80)) is not None
                ]
            for key in ("name", "sector", "industry", "currency"):
                if not company.get(key):
                    company[key] = clean_text(row.get(key))
    except (ToolExecutionError, OSError, UnicodeDecodeError) as exc:
        warnings.append(f"Some watched stocks could not be read: {exc}")
    for symbol in payload["symbols"]:
        universe.setdefault(symbol, _company(symbol, "requested"))
    if len(universe) > MAX_SYMBOLS:
        raise ToolExecutionError(f"Held/watched universe exceeds {MAX_SYMBOLS} stocks.")
    return universe


async def _collect_market(
    client: httpx2.AsyncClient,
    payload: dict[str, Any],
    universe: dict[str, dict[str, Any]],
    warnings: list[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    screeners: list[dict[str, Any]] = []
    for name, request in payload["screeners"].items():
        selected: list[dict[str, Any]] = []
        try:
            document = json_object(await fetch_bytes(client, request), name)
            finance = document.get("finance", {})
            result = finance.get("result")
            if not isinstance(result, list) or not result or not isinstance(result[0], dict):
                raise ToolExecutionError(f"{name} returned no screener result.")
            quotes = result[0].get("quotes")
            if not isinstance(quotes, list):
                raise ToolExecutionError(f"{name} returned malformed quotes.")
            for rank, row in enumerate(quotes[: payload["limit"]], start=1):
                if not isinstance(row, dict) or row.get("quoteType", "EQUITY") != "EQUITY":
                    continue
                symbol = row.get("symbol")
                if not isinstance(symbol, str) or _SYMBOL.fullmatch(symbol) is None:
                    continue
                if row.get("region", "US") != "US" or row.get("currency", "USD") != "USD":
                    continue
                timestamp = finite_number(row.get("regularMarketTime"))
                quote_date = None
                if timestamp is not None:
                    try:
                        quote_date = (
                            datetime.fromtimestamp(timestamp, UTC)
                            .astimezone(ZoneInfo("America/New_York"))
                            .date()
                            .isoformat()
                        )
                    except (ValueError, OverflowError, OSError):
                        warnings.append(f"{symbol} had an invalid quote timestamp.")
                selected.append(
                    {
                        "id": f"screener-{payload['as_of']}-{name}-{symbol}",
                        "ticker": symbol,
                        "rank": rank,
                        "date": quote_date,
                        "price": finite_number(row.get("regularMarketPrice")),
                        "change_pct": finite_number(row.get("regularMarketChangePercent")),
                        "volume": finite_number(row.get("regularMarketVolume")),
                        "source": request["url"],
                        "delayed_minutes": finite_number(row.get("exchangeDataDelayedBy")),
                        "market_state": clean_text(row.get("marketState")),
                    }
                )
                if symbol not in universe and len(universe) >= MAX_SYMBOLS:
                    warnings.append(
                        f"{symbol} omitted because the {MAX_SYMBOLS}-stock limit was reached."
                    )
                    continue
                company = universe.setdefault(symbol, _company(symbol, name))
                if name not in company["origins"]:
                    company["origins"].append(name)
                for key, source in (
                    ("name", "longName"),
                    ("sector", "sector"),
                    ("industry", "industry"),
                    ("currency", "currency"),
                ):
                    if not company.get(key):
                        company[key] = clean_text(row.get(source))
            if not selected:
                warnings.append(f"Yahoo {name} returned no usable US equities.")
            screeners.append(
                {"name": name, "status": "ok", "quotes": selected, "source": request["url"]}
            )
        except (ToolExecutionError, AttributeError, TypeError) as exc:
            warnings.append(f"Yahoo {name} unavailable: {exc}")
            screeners.append(
                {
                    "name": name,
                    "status": "unavailable",
                    "quotes": [],
                    "error": str(exc),
                    "source": request["url"],
                }
            )
    news: list[dict[str, Any]] = []
    try:
        request = payload["feed"]
        news = feed_document(await fetch_bytes(client, request), url=request["url"], limit=20)[
            "entries"
        ]
    except ToolExecutionError as exc:
        warnings.append(f"Yahoo market headlines unavailable: {exc}")
    return screeners, news


def feed_url(symbols: list[str]) -> str:
    return f"https://{FEED_HOST}/rss/2.0/headline?" + urlencode(
        {"s": ",".join(symbols), "region": "US", "lang": "en-US"}
    )


def _search_url(symbol: str) -> str:
    return f"https://{YAHOO_HOST}/v1/finance/search?" + urlencode(
        {"q": symbol, "quotesCount": 1, "newsCount": 0, "enableFuzzyQuery": "false"}
    )


def _headline_symbols(news: list[dict[str, Any]]) -> list[str]:
    hints: list[str] = []
    for row in news:
        text = f"{row['title']} {row.get('summary') or ''}"
        for match in _NEWS_SYMBOL.finditer(text):
            symbol = next((group for group in match.groups() if group), "")
            if _SYMBOL.fullmatch(symbol) and symbol not in hints:
                hints.append(symbol)
    return hints[:5]


async def _metadata(
    client: httpx2.AsyncClient,
    request: dict[str, str],
    universe: dict[str, dict[str, Any]],
    warnings: list[str],
) -> None:
    semaphore = asyncio.Semaphore(5)

    async def one(symbol: str, company: dict[str, Any]) -> None:
        async with semaphore:
            url = _search_url(symbol)
            try:
                document = json_object(
                    await fetch_bytes(client, request, url=url, maximum=250_000), url
                )
                rows = document.get("quotes", [])
                if not isinstance(rows, list):
                    raise ToolExecutionError("Malformed company search quotes.")
                match = next(
                    (
                        row
                        for row in rows
                        if isinstance(row, dict)
                        and row.get("symbol") == symbol
                        and row.get("quoteType") == "EQUITY"
                    ),
                    None,
                )
                if match is None:
                    raise ToolExecutionError("No exact equity match returned.")
                company["verified_equity"] = True
                company["metadata_source"] = url
                for key, candidates in (
                    ("name", ("longname", "shortname")),
                    ("sector", ("sectorDisp", "sector")),
                    ("industry", ("industryDisp", "industry")),
                ):
                    if not company.get(key):
                        company[key] = next(
                            (
                                clean_text(match.get(candidate))
                                for candidate in candidates
                                if clean_text(match.get(candidate))
                            ),
                            None,
                        )
                if not company.get("company_name"):
                    company["company_name"] = company.get("name")
            except ToolExecutionError as exc:
                warnings.append(f"{symbol} company metadata unavailable: {exc}")

    await asyncio.gather(*(one(symbol, company) for symbol, company in universe.items()))


def _mentions(text: str, company: dict[str, Any]) -> bool:
    # Case-sensitive ticker matching avoids assigning ordinary words like "now".
    symbol = company["ticker"]
    if re.search(rf"(?<![A-Z0-9]){re.escape(symbol)}(?![A-Z0-9])", text):
        return True
    names = [company.get("company_name"), company.get("name"), *company.get("aliases", [])]
    for name in names:
        if not isinstance(name, str):
            continue
        plain_name = re.sub(
            r",?\s+(?:Corporation|Corp\.?|Inc\.?|Limited|Ltd\.?|plc)\b.*$",
            "",
            name,
            flags=re.IGNORECASE,
        )
        if len(plain_name) >= 3 and re.search(
            rf"(?<!\w){re.escape(plain_name)}(?!\w)", text, re.IGNORECASE
        ):
            return True
    return False
