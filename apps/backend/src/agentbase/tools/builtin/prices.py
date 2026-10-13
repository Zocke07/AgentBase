"""Deterministic daily prices from Yahoo's fixed chart endpoint.

The endpoint is keyless and unofficial. Each name is checked and pinned before
approval, each response is bounded, and arithmetic stays in ``Decimal`` until
the CSV and JSON files are written.
"""

from __future__ import annotations

import asyncio
import csv
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from io import StringIO
from typing import TYPE_CHECKING, Any, Final
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx2

from agentbase.tools.base import Prepared, ToolArgumentError, ToolExecutionError
from agentbase.tools.builtin.forecasts import FORECAST_HORIZONS
from agentbase.tools.catalogue import RiskLevel, lookup

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from pathlib import Path

    from agentbase.tools.sandbox import Sandbox

__all__ = ["MAX_PRICE_BYTES", "MAX_PRICE_SYMBOLS", "ReadPricesTool"]

PRICE_HOST: Final[str] = "query1.finance.yahoo.com"
PRICE_URL: Final[str] = (
    "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=1y&interval=1d"
)
MAX_PRICE_SYMBOLS: Final[int] = 50
MAX_TRACKED_SYMBOLS: Final[int] = 500
MAX_PRICE_BYTES: Final[int] = 1_000_000
REQUEST_TIMEOUT_SECONDS: Final[float] = 30.0
_SYMBOL: Final[re.Pattern[str]] = re.compile(r"^[A-Z0-9^=._-]{1,20}$")
_MOVERS: Final[re.Pattern[str]] = re.compile(r"^movers-(\d{4}-\d{2}-\d{2})\.json$")


@dataclass(frozen=True, slots=True)
class _Session:
    date: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int


@dataclass(frozen=True, slots=True)
class _History:
    ticker: str
    currency: str
    price_places: int
    sessions: tuple[_Session, ...]


def _declaration(name: str) -> tuple[str, RiskLevel]:
    declaration = lookup(name)
    if declaration is None:  # pragma: no cover: registry test pins this
        msg = f"{name!r} has an implementation but no catalogue entry"
        raise RuntimeError(msg)
    return declaration.description, declaration.risk


class ReadPricesTool:
    """Fetch and persist a year of daily prices for a bounded watchlist."""

    name = "read_prices"

    def __init__(
        self,
        client: httpx2.AsyncClient | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._client = client
        #: Decides whether the latest bar's regular session has closed yet.
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
                    "minItems": 1,
                    "maxItems": MAX_PRICE_SYMBOLS,
                    "description": (
                        "Optional one to 50 symbols. Omit to follow holdings, "
                        "watchlist, discovered market candidates and refresh "
                        "every pending forecast's price history."
                    ),
                }
            },
            "required": [],
        }

    def prepare(self, arguments: dict[str, Any], sandbox: Sandbox) -> Prepared:
        raw = arguments.get("symbols")
        active: list[str] | None = None
        held: list[str] | None = None
        omitted: list[str] = []
        if raw is None:
            active, raw, held, omitted = _automatic_symbols(sandbox)
        if not isinstance(raw, list) or not raw:
            msg = f"{self.name} needs a non-empty 'symbols' array."
            raise ToolArgumentError(msg)
        maximum = MAX_PRICE_SYMBOLS if active is None else MAX_TRACKED_SYMBOLS
        if len(raw) > maximum:
            msg = f"{self.name} accepts at most {maximum} symbols."
            raise ToolArgumentError(msg)

        symbols: list[str] = []
        for value in raw:
            if not isinstance(value, str):
                msg = f"{self.name}'s symbols must all be strings."
                raise ToolArgumentError(msg)
            symbol = value.strip().upper()
            if _SYMBOL.fullmatch(symbol) is None:
                msg = (
                    f"{value!r} is not a supported ticker symbol. Use 1 to 20 "
                    "letters, digits, dots, dashes, underscores, ^ or =."
                )
                raise ToolArgumentError(msg)
            if symbol not in symbols:
                symbols.append(symbol)

        requests: list[dict[str, Any]] = []
        for symbol in symbols:
            url = PRICE_URL.format(symbol=quote(symbol, safe=""))
            checked = sandbox.resolve_url(url)
            path = sandbox.resolve_write_path(f"raw/prices/{symbol}.csv")
            requests.append(
                {
                    "symbol": symbol,
                    "url": checked.url,
                    "host": checked.host,
                    "address": str(checked.address),
                    "path": path,
                }
            )

        summary_path = sandbox.resolve_write_path("raw/prices/summary.csv")
        movers_probe = sandbox.resolve_write_path("raw/movers-SESSION.json")
        shown = _list_words(symbols)
        return Prepared(
            tool_name=self.name,
            summary=f"read one year of daily prices for {shown}",
            payload={
                "host": PRICE_HOST,
                "requests": requests,
                "summary_path": summary_path,
                "movers_dir": movers_probe.parent,
                "active_symbols": active,
                "held_symbols": held,
                "omitted_discovered_symbols": omitted,
            },
            raw_arguments=dict(arguments),
        )

    async def execute(self, prepared: Prepared, sandbox: Sandbox) -> str:
        client = self._client
        owned = client is None
        if client is None:
            client = httpx2.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS)

        semaphore = asyncio.Semaphore(5)
        now = self._clock()

        async def one(request: dict[str, Any]) -> tuple[_History | None, str | None]:
            async with semaphore:
                try:
                    body = await _fetch(client, request)
                    return _parse_history(body, expected=request["symbol"], now=now), None
                except ToolExecutionError as exc:
                    return None, str(exc)

        try:
            outcomes = await asyncio.gather(
                *(one(request) for request in prepared.payload["requests"])
            )
        finally:
            if owned:
                await client.aclose()

        histories: list[_History] = []
        failures: list[dict[str, str]] = []
        # Reported so the run view can list and open what this call wrote.
        written: list[str] = []
        for request, (history, error) in zip(
            prepared.payload["requests"], outcomes, strict=True
        ):
            if history is None:
                failures.append({"ticker": request["symbol"], "error": error or "failed"})
                continue
            histories.append(history)
            await asyncio.to_thread(_write_history, request["path"], history)
            written.append(sandbox.relative(request["path"]))

        active_symbols = prepared.payload.get("active_symbols")
        active_histories = (
            histories
            if active_symbols is None
            else [history for history in histories if history.ticker in active_symbols]
        )
        rows = _mover_rows(active_histories)
        history_failures = (
            []
            if active_symbols is None
            else [failure for failure in failures if failure["ticker"] not in active_symbols]
        )
        failures = [failure for failure in failures if failure not in history_failures]
        held_symbols = prepared.payload.get("held_symbols")
        required_failures = (
            failures
            if held_symbols is None
            else [failure for failure in failures if failure["ticker"] in held_symbols]
        )
        summary_path: Path = prepared.payload["summary_path"]
        await asyncio.to_thread(_write_summary, summary_path, rows)
        written.append(sandbox.relative(summary_path))

        movers_dir: Path = prepared.payload["movers_dir"]
        as_of = max((row["date"] for row in rows), default=None)
        previous = _latest_movers_date(movers_dir)
        new_session = as_of is not None and (previous is None or as_of > previous)
        movers_path: Path | None = None
        if as_of is not None:
            movers_path = sandbox.resolve_write_path(f"raw/movers-{as_of}.json")
            await asyncio.to_thread(_write_json, movers_path, rows)
            written.append(sandbox.relative(movers_path))

        returned = {
            "as_of": as_of,
            "new_session": new_session,
            "research_needed": _research_needed(sandbox, as_of, rows, now),
            "summary_path": sandbox.relative(summary_path),
            "movers_path": None if movers_path is None else sandbox.relative(movers_path),
            "summary": rows,
            "failures": failures,
            "required_failures": required_failures,
            "history_failures": history_failures,
            "refreshed_histories": len(histories),
            "omitted_discovered_symbols": prepared.payload.get(
                "omitted_discovered_symbols", []
            ),
            "written": written,
        }
        return json.dumps(returned, ensure_ascii=False, separators=(",", ":"))


def _research_needed(
    sandbox: Sandbox, as_of: str | None, rows: list[dict[str, Any]], now: datetime
) -> bool:
    """A same-session retry may finish an interrupted decision and workbook."""
    if as_of is None or (now.date() - datetime.fromisoformat(as_of).date()).days > 7:
        return False
    decision = sandbox.resolve_path(f"decisions/{as_of}.md")
    ledger = sandbox.resolve_path("predictions/forecasts.json")
    if not decision.is_file() or not ledger.is_file():
        return True
    try:
        reviewed = decision.stat().st_mtime_ns
        for name in ("portfolio/positions.csv", "config/watchlist.json", "config/limits.json"):
            personal = sandbox.resolve_path(name)
            if personal.is_file() and personal.stat().st_mtime_ns > reviewed:
                return True
        document = json.loads(ledger.read_text(encoding="utf-8"))
        forecasts = document.get("forecasts", []) if isinstance(document, dict) else []
        if not isinstance(forecasts, list):
            return True
        covered = {
            (row.get("ticker"), row.get("horizon_days"))
            for row in forecasts
            if isinstance(row, dict) and row.get("as_of") == as_of
        }
        return any(
            (row["ticker"], horizon) not in covered
            for row in rows
            if row["date"] == as_of and row["currency"] == "USD"
            for horizon in FORECAST_HORIZONS
        )
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError):
        return True


def _automatic_symbols(sandbox: Sandbox) -> tuple[list[str], list[str], list[str], list[str]]:
    """Holdings always participate; retired discoveries stay until scored."""
    active: list[str] = []
    tracked: list[str] = []
    held: list[str] = []
    omitted: list[str] = []

    def add(value: object, target: list[str]) -> None:
        if not isinstance(value, str) or _SYMBOL.fullmatch(value.strip().upper()) is None:
            raise ToolArgumentError("Configured market tickers must be valid symbols.")
        symbol = value.strip().upper()
        if symbol != "CASH" and symbol not in target:
            target.append(symbol)

    try:
        positions = sandbox.resolve_path("portfolio/positions.csv")
        if positions.exists():
            for row in csv.DictReader(StringIO(positions.read_text(encoding="utf-8-sig"))):
                if (row.get("ticker") or "").strip():
                    add(row["ticker"], active)
                    add(row["ticker"], held)
        for shown, key in (
            ("config/watchlist.json", "watchlist"),
            ("raw/market/universe.json", "universe"),
        ):
            path = sandbox.resolve_path(shown)
            if not path.exists():
                continue
            document = json.loads(path.read_text(encoding="utf-8"))
            entries = document.get(key, []) if isinstance(document, dict) else document
            if not isinstance(entries, list):
                raise ToolArgumentError(f"{shown} needs a {key} array.")
            for entry in entries:
                candidate: list[str] = []
                add(entry.get("ticker") if isinstance(entry, dict) else entry, candidate)
                for symbol in candidate:
                    if symbol in active:
                        continue
                    if key == "universe" and len(active) >= MAX_PRICE_SYMBOLS:
                        omitted.append(symbol)
                    else:
                        active.append(symbol)
        if len(active) > MAX_PRICE_SYMBOLS:
            raise ToolArgumentError(
                "The active market universe may contain at most 50 symbols."
            )
        tracked.extend(active)
        ledger = sandbox.resolve_path("predictions/forecasts.json")
        if ledger.exists():
            document = json.loads(ledger.read_text(encoding="utf-8"))
            if not isinstance(document, dict) or not isinstance(
                document.get("forecasts"), list
            ):
                raise ToolArgumentError("predictions/forecasts.json needs a forecasts array.")
            for row in document["forecasts"]:
                if isinstance(row, dict) and row.get("actual_close") is None:
                    add(row.get("ticker"), tracked)
    except (OSError, UnicodeError, json.JSONDecodeError, csv.Error) as exc:
        raise ToolArgumentError(f"The market universe could not be read: {exc}") from exc
    if not active:
        raise ToolArgumentError("Add holdings or a watchlist, or run read_market first.")
    return active, tracked, held, omitted


async def _fetch(client: httpx2.AsyncClient, request: dict[str, Any]) -> bytes:
    url: str = request["url"]
    host: str = request["host"]
    parsed = httpx2.URL(url)
    pinned = parsed.copy_with(host=request["address"])
    headers = {
        "host": host,
        "accept": "application/json",
        "user-agent": "AgentBase/price-reader",
    }
    extensions: dict[str, Any] = {"sni_hostname": host}
    try:
        async with client.stream(
            "GET", pinned, headers=headers, extensions=extensions, follow_redirects=False
        ) as response:
            if 300 <= response.status_code < 400:
                raise ToolExecutionError(f"redirected with HTTP {response.status_code}")
            if response.status_code >= 400:
                raise ToolExecutionError(f"returned HTTP {response.status_code}")
            advertised = response.headers.get("content-length")
            if (
                advertised is not None
                and advertised.isdigit()
                and int(advertised) > MAX_PRICE_BYTES
            ):
                raise ToolExecutionError(f"exceeded the {MAX_PRICE_BYTES}-byte response limit")
            chunks: list[bytes] = []
            size = 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > MAX_PRICE_BYTES:
                    raise ToolExecutionError(
                        f"exceeded the {MAX_PRICE_BYTES}-byte response limit"
                    )
                chunks.append(chunk)
    except ToolExecutionError:
        raise
    except httpx2.HTTPError as exc:
        msg = f"could not be fetched: {exc}"
        raise ToolExecutionError(msg) from exc
    return b"".join(chunks)


def _parse_history(body: bytes, *, expected: str, now: datetime) -> _History:
    try:
        document = json.loads(body, parse_float=Decimal)
        chart = document["chart"]
        if chart.get("error") is not None:
            raise ValueError(str(chart["error"]))
        result = chart["result"][0]
        meta = result["meta"]
        timestamps = result["timestamp"]
        quote_data = result["indicators"]["quote"][0]
        timezone = ZoneInfo(str(meta["exchangeTimezoneName"]))
        places = int(meta.get("priceHint", 2))
        currency = str(meta["currency"])
        returned_symbol = str(meta["symbol"]).upper()
    except (
        IndexError,
        KeyError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
        ZoneInfoNotFoundError,
    ) as exc:
        msg = f"returned malformed chart data: {exc}"
        raise ToolExecutionError(msg) from exc
    if returned_symbol != expected:
        raise ToolExecutionError(f"returned symbol {returned_symbol!r} instead of {expected!r}")
    if not 0 <= places <= 8:
        raise ToolExecutionError("returned an unsupported price precision")

    fields = [quote_data.get(name) for name in ("open", "high", "low", "close", "volume")]
    if any(not isinstance(field, list) or len(field) != len(timestamps) for field in fields):
        raise ToolExecutionError("returned chart arrays with different lengths")

    sessions: list[_Session] = []
    for timestamp, open_, high, low, close, volume in zip(timestamps, *fields, strict=True):
        if any(value is None for value in (open_, high, low, close, volume)):
            continue
        try:
            date = (
                datetime.fromtimestamp(int(timestamp), UTC)
                .astimezone(timezone)
                .date()
                .isoformat()
            )
            session = _Session(
                date=date,
                open=Decimal(open_),
                high=Decimal(high),
                low=Decimal(low),
                close=Decimal(close),
                volume=int(volume),
            )
        except (ValueError, TypeError, OverflowError) as exc:
            msg = f"returned an invalid daily price: {exc}"
            raise ToolExecutionError(msg) from exc
        if session.volume < 0:
            raise ToolExecutionError("returned a negative daily volume")
        sessions.append(session)
    sessions.sort(key=lambda session: session.date)
    if sessions and _still_trading(meta, timezone, sessions[-1].date, now):
        # A bar for a session that has not closed is a partial day, not a session.
        sessions.pop()
    if len(sessions) < 2:
        raise ToolExecutionError("returned fewer than two complete daily sessions")
    return _History(
        ticker=expected,
        currency=currency,
        price_places=places,
        sessions=tuple(sessions),
    )


def _write_history(path: Path, history: _History) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    output = StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(("date", "open", "high", "low", "close", "volume"))
    for session in history.sessions:
        writer.writerow(
            (
                session.date,
                _price(session.open, history.price_places),
                _price(session.high, history.price_places),
                _price(session.low, history.price_places),
                _price(session.close, history.price_places),
                session.volume,
            )
        )
    path.write_text(output.getvalue(), encoding="utf-8", newline="")


def _mover_rows(histories: list[_History]) -> list[dict[str, Any]]:
    calculated: list[tuple[Decimal, dict[str, Any]]] = []
    for history in histories:
        latest = history.sessions[-1]
        previous = history.sessions[-2]
        prior_volumes = [session.volume for session in history.sessions[-21:-1]]
        average = Decimal(sum(prior_volumes)) / Decimal(len(prior_volumes))
        change = (latest.close - previous.close) / previous.close * Decimal(100)
        relative = Decimal(latest.volume) / average if average else Decimal(0)
        low_52w = min(session.low for session in history.sessions)
        high_52w = max(session.high for session in history.sessions)
        average_int = int(average.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        row: dict[str, Any] = {
            # A stable id lets a thesis cite the row as evidence, as news records are.
            "id": f"movers-{latest.date}-{history.ticker}",
            "ticker": history.ticker,
            "date": latest.date,
            "as_of": latest.date,
            "session": "regular",
            "last": _json_price(latest.close, history.price_places),
            "prev_close": _json_price(previous.close, history.price_places),
            "open": _json_price(latest.open, history.price_places),
            "high": _json_price(latest.high, history.price_places),
            "low": _json_price(latest.low, history.price_places),
            "volume": latest.volume,
            "avg_volume_20d": average_int,
            "range_52w": [
                _json_price(low_52w, history.price_places),
                _json_price(high_52w, history.price_places),
            ],
            "market_cap": None,
            "source": PRICE_HOST,
            "delayed_minutes": 0,
            "change_pct": _json_decimal(change, 4),
            "rel_volume": _json_decimal(relative, 4),
            "microcap": latest.close < Decimal(5) or average_int < 100_000,
            "rank": 0,
            "currency": history.currency,
        }
        calculated.append((change, row))
    calculated.sort(key=lambda item: (-item[0], item[1]["ticker"]))
    for rank, (_, row) in enumerate(calculated, start=1):
        row["rank"] = rank
    return sorted((row for _, row in calculated), key=lambda row: row["ticker"])


_SUMMARY_COLUMNS: Final[tuple[str, ...]] = (
    "ticker",
    "date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "prev_close",
    "change_pct",
    "avg_volume_20d",
    "rel_volume",
    "microcap",
    "rank",
    "currency",
)


def _write_summary(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    output = StringIO(newline="")
    writer = csv.DictWriter(
        output, fieldnames=_SUMMARY_COLUMNS, extrasaction="ignore", lineterminator="\n"
    )
    writer.writeheader()
    for row in rows:
        rendered = {**row, "close": row["last"]}
        writer.writerow(rendered)
    path.write_text(output.getvalue(), encoding="utf-8", newline="")


def _still_trading(
    meta: Mapping[str, Any], timezone: ZoneInfo, latest: str, now: datetime
) -> bool:
    """Whether ``latest`` is the exchange's current day and its regular hours run on.

    Without a readable trading period the bar counts as complete, as before.
    """
    try:
        regular = meta["currentTradingPeriod"]["regular"]
        start = int(regular["start"])
        end = int(regular["end"])
    except (KeyError, TypeError, ValueError):
        return False
    day = datetime.fromtimestamp(start, UTC).astimezone(timezone).date().isoformat()
    return latest == day and now.timestamp() < end


def _write_json(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(rows, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _latest_movers_date(folder: Path) -> str | None:
    if not folder.exists():
        return None
    dates = [
        match.group(1) for path in folder.iterdir() if (match := _MOVERS.fullmatch(path.name))
    ]
    return max(dates, default=None)


def _price(value: Decimal, places: int) -> str:
    quantum = Decimal(1).scaleb(-places)
    return f"{value.quantize(quantum, rounding=ROUND_HALF_UP):.{places}f}"


def _json_price(value: Decimal, places: int) -> float | int:
    rendered = _price(value, places)
    return int(rendered) if places == 0 else float(rendered)


def _json_decimal(value: Decimal, places: int) -> float:
    quantum = Decimal(1).scaleb(-places)
    return float(value.quantize(quantum, rounding=ROUND_HALF_UP))


def _list_words(values: list[str]) -> str:
    if len(values) == 1:
        return values[0]
    if len(values) == 2:
        return f"{values[0]} and {values[1]}"
    return f"{', '.join(values[:-1])} and {values[-1]}"
