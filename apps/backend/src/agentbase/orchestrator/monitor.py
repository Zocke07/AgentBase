"""Market watch (BUILD_SPEC Phase 18): notice sudden moves, alert, explain.

The watcher is app code beside the scheduler, not an agent. It watches the
default space alone: it is part of that space's investment pipeline, which
stays there (2026-10-13). While the space's
``config/monitor.json`` turns it on, it reads quotes every few minutes from
US pre-market open to after-hours close, compares them with the reference
close and with the price a few minutes earlier, and records an alert for a
move past the person's thresholds. No model is involved in noticing a move.

Each check's alerts are explained together by one ordinary run, origin
``monitor``, so every call the explaining agent makes passes the approval
gate and the run can be replayed. The watcher never answers an approval and
never changes a schedule. Like the scheduler it lives in the sidecar, so it
stops with the app: nothing is watched while AgentBase is closed.
"""

from __future__ import annotations

import asyncio
import contextlib
import csv
import json
import logging
import math
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta
from io import StringIO
from typing import TYPE_CHECKING, Any, Final, Literal
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import httpx2
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from agentbase.store.alerts import NewAlert
from agentbase.store.spaces import DEFAULT_SPACE_ID
from agentbase.tools.base import ToolExecutionError
from agentbase.tools.builtin.fetching import (
    checked_request,
    clean_text,
    fetch_bytes,
    finite_number,
    json_object,
    read_local,
)
from agentbase.tools.sandbox import Sandbox, SandboxViolationError

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterable
    from pathlib import Path

    from agentbase.events.store import EventStore
    from agentbase.orchestrator.launcher import RunLauncher
    from agentbase.orchestrator.power import Wakefulness
    from agentbase.store.alerts import AlertStore, MarketAlert
    from agentbase.store.spaces import Space, SpaceStore

__all__ = [
    "MONITOR_PATH",
    "MarketMonitor",
    "MonitorConfig",
    "MonitorConfigError",
    "MonitorStatus",
    "Quote",
    "Seen",
    "default_config_text",
    "detect",
    "parse_config",
    "parse_spark",
    "within_market_hours",
]

logger = logging.getLogger("agentbase.monitor")

MONITOR_PATH: Final[str] = "config/monitor.json"
NEW_YORK: Final[ZoneInfo] = ZoneInfo("America/New_York")
#: US pre-market opens at 04:00 and after-hours trading ends at 20:00, New York time.
MARKET_OPENS: Final[time] = time(4)
MARKET_CLOSES: Final[time] = time(20)
SPARK_HOST: Final[str] = "query1.finance.yahoo.com"
#: Yahoo's spark endpoint answers for up to 20 symbols a request.
SYMBOLS_PER_REQUEST: Final[int] = 20
MAX_SYMBOLS: Final[int] = 60
#: A quote older than this during trading hours, as on a holiday, alerts nothing.
STALE_AFTER: Final[timedelta] = timedelta(minutes=30)
#: How often the loop looks at each space's file; each space's own interval
#: decides when its quotes are read.
POLL_SECONDS: Final[float] = 60.0
#: An explanation is a short research task; it may not hold the space for long.
EXPLANATION_SECONDS: Final[int] = 420
_SYMBOL: Final[re.Pattern[str]] = re.compile(r"^\^?[A-Z0-9][A-Z0-9.=_-]{0,19}$")
_UNFINISHED: Final[frozenset[str]] = frozenset({"pending", "running", "paused"})

Session = Literal["pre", "regular", "post"]


class MonitorConfigError(ValueError):
    """``config/monitor.json`` cannot be used, in words the person can act on."""


class MonitorConfig(BaseModel):
    """The person's thresholds, from ``config/monitor.json``; unknown keys are refused."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    check_every_minutes: int = Field(default=5, ge=1, le=60)
    follow_holdings: bool = True
    follow_watchlist: bool = True
    symbols: list[str] = Field(default_factory=list, max_length=MAX_SYMBOLS)
    indexes: list[str] = Field(
        default_factory=lambda: ["^GSPC", "^IXIC", "^DJI"], max_length=10
    )
    stock_move_pct: float = Field(default=5, gt=0, le=50)
    stock_jump_pct: float = Field(default=2.5, gt=0, le=50)
    index_move_pct: float = Field(default=1.5, gt=0, le=50)
    index_jump_pct: float = Field(default=1, gt=0, le=50)
    jump_window_minutes: int = Field(default=15, ge=5, le=120)
    step_pct: float = Field(default=3, gt=0, le=50)
    explain: bool = True
    max_explanations_per_day: int = Field(default=10, ge=0, le=50)

    @field_validator("symbols", "indexes")
    @classmethod
    def _symbols(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        for value in values:
            symbol = value.strip().upper()
            if _SYMBOL.fullmatch(symbol) is None:
                msg = f"{value!r} is not a ticker symbol"
                raise ValueError(msg)
            if symbol not in cleaned:
                cleaned.append(symbol)
        return cleaned


def parse_config(text: str) -> MonitorConfig:
    try:
        raw = json.loads(text)
    except ValueError as exc:
        msg = f"{MONITOR_PATH} is not valid JSON: {exc}"
        raise MonitorConfigError(msg) from exc
    if not isinstance(raw, dict):
        msg = f"{MONITOR_PATH} must hold one JSON object."
        raise MonitorConfigError(msg)
    try:
        return MonitorConfig.model_validate(raw)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors()
        )
        msg = f"{MONITOR_PATH} has a problem: {problems}"
        raise MonitorConfigError(msg) from exc


def default_config_text(*, enabled: bool) -> str:
    """The starter file: every setting spelled out, so the person sees what to change."""
    return json.dumps(MonitorConfig(enabled=enabled).model_dump(), indent=2) + "\n"


def within_market_hours(now: datetime) -> bool:
    """Weekdays from 04:00 to 20:00 in New York, pre-market through after-hours."""
    local = now.astimezone(NEW_YORK)
    return local.weekday() < 5 and MARKET_OPENS <= local.time() < MARKET_CLOSES


# --- quotes ---------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Quote:
    """One symbol's latest price with what it is compared against."""

    symbol: str
    name: str | None
    is_index: bool
    price: float
    quoted_at: datetime
    session: Session | None
    previous_close: float | None
    #: The regular session's last price; after-hours moves are measured from it.
    regular_close: float | None
    #: Five-minute closes up to ``quoted_at``, oldest first.
    bars: tuple[tuple[datetime, float], ...]


def spark_url(symbols: Iterable[str]) -> str:
    return f"https://{SPARK_HOST}/v7/finance/spark?" + urlencode(
        {
            "symbols": ",".join(symbols),
            "range": "1d",
            "interval": "5m",
            "includePrePost": "true",
        }
    )


def parse_spark(body: bytes) -> dict[str, Quote]:
    """Quotes from a spark response; a malformed symbol is left out, not guessed."""
    document = json_object(body, "Yahoo spark")
    spark = document.get("spark")
    results = spark.get("result") if isinstance(spark, dict) else None
    if not isinstance(results, list):
        msg = "Yahoo spark returned no results."
        raise ToolExecutionError(msg)
    quotes: dict[str, Quote] = {}
    for result in results:
        quote = _spark_quote(result)
        if quote is not None:
            quotes[quote.symbol] = quote
    return quotes


def _spark_quote(result: Any) -> Quote | None:
    if not isinstance(result, dict) or not isinstance(result.get("symbol"), str):
        return None
    responses = result.get("response")
    if not isinstance(responses, list) or not responses or not isinstance(responses[0], dict):
        return None
    response = responses[0]
    meta = response.get("meta")
    timestamps = response.get("timestamp")
    indicators = response.get("indicators")
    if not isinstance(meta, dict) or not isinstance(timestamps, list):
        return None
    quote_list = indicators.get("quote") if isinstance(indicators, dict) else None
    closes = (
        quote_list[0].get("close")
        if isinstance(quote_list, list) and quote_list and isinstance(quote_list[0], dict)
        else None
    )
    if not isinstance(closes, list):
        return None
    bars = tuple(
        (datetime.fromtimestamp(stamp, UTC), float(close))
        for stamp, close in zip(timestamps, closes, strict=False)
        if _positive(stamp) and _positive(close)
    )
    if not bars:
        return None
    quoted_at, price = bars[-1]
    return Quote(
        symbol=result["symbol"].upper(),
        name=clean_text(meta.get("longName")) or clean_text(meta.get("shortName")),
        is_index=meta.get("instrumentType") == "INDEX" or result["symbol"].startswith("^"),
        price=price,
        quoted_at=quoted_at,
        session=_session(meta.get("currentTradingPeriod"), quoted_at),
        previous_close=_price(meta.get("previousClose"))
        or _price(meta.get("chartPreviousClose")),
        regular_close=_price(meta.get("regularMarketPrice")),
        bars=bars,
    )


def _positive(value: Any) -> bool:
    number = finite_number(value)
    return number is not None and number > 0


def _price(value: Any) -> float | None:
    number = finite_number(value)
    return float(number) if number is not None and number > 0 else None


def _session(periods: Any, at: datetime) -> Session | None:
    if not isinstance(periods, dict):
        return None
    stamp = at.timestamp()
    names: tuple[Session, ...] = ("pre", "regular", "post")
    for name in names:
        period = periods.get(name)
        if not isinstance(period, dict):
            continue
        start, end = finite_number(period.get("start")), finite_number(period.get("end"))
        if start is not None and end is not None and start <= stamp < end:
            return name
    return None


async def fetch_quotes(
    client: httpx2.AsyncClient, sandbox: Sandbox, symbols: list[str]
) -> tuple[dict[str, Quote], list[str]]:
    """Every symbol's quote, twenty a request; a failed request is a reported gap."""
    quotes: dict[str, Quote] = {}
    problems: list[str] = []
    for start in range(0, len(symbols), SYMBOLS_PER_REQUEST):
        chunk = symbols[start : start + SYMBOLS_PER_REQUEST]
        url = spark_url(chunk)
        try:
            # The address check resolves DNS, which blocks; keep it off the loop.
            request = await asyncio.to_thread(checked_request, sandbox, url)
            quotes.update(parse_spark(await fetch_bytes(client, request, maximum=1_000_000)))
        except (ToolExecutionError, SandboxViolationError) as exc:
            problems.append(f"Quotes for {', '.join(chunk)} unavailable: {exc}")
    missing = [symbol for symbol in symbols if symbol not in quotes]
    if missing and not problems:
        problems.append(f"No quote for {', '.join(missing)}.")
    return quotes, problems


# --- detection ------------------------------------------------------------------


@dataclass(slots=True)
class Seen:
    """What a space was already told today, so a move alerts once per step."""

    #: Highest level alerted per symbol, direction and reference.
    levels: dict[tuple[str, str, str], float] = field(default_factory=dict)
    #: When each symbol last jumped in each direction.
    jumps: dict[tuple[str, str], datetime] = field(default_factory=dict)

    @classmethod
    def from_alerts(cls, alerts: Iterable[MarketAlert]) -> Seen:
        seen = cls()
        for alert in alerts:
            if alert.kind == "move":
                key = (alert.symbol, alert.direction, alert.reference)
                seen.levels[key] = max(seen.levels.get(key, 0.0), alert.level_pct)
            else:
                stamp = datetime.fromisoformat(alert.quoted_at)
                key2 = (alert.symbol, alert.direction)
                if key2 not in seen.jumps or stamp > seen.jumps[key2]:
                    seen.jumps[key2] = stamp
        return seen


def detect(
    quotes: Iterable[Quote], config: MonitorConfig, seen: Seen, *, now: datetime
) -> list[NewAlert]:
    """At most one alert per symbol: a move past its next level, else a sudden jump."""
    alerts: list[NewAlert] = []
    for quote in sorted(quotes, key=lambda item: item.symbol):
        if quote.session is None or now - quote.quoted_at > STALE_AFTER:
            continue
        index = quote.is_index or quote.symbol in config.indexes
        move_at = config.index_move_pct if index else config.stock_move_pct
        jump_at = config.index_jump_pct if index else config.stock_jump_pct
        best = _move(quote, index, move_at, config.step_pct, seen)
        if best is None:
            best = _jump(quote, index, jump_at, config.jump_window_minutes, seen)
        if best is not None:
            alerts.append(best)
            _remember(seen, best)
    return alerts


def _move(
    quote: Quote, index: bool, move_at: float, step: float, seen: Seen
) -> NewAlert | None:
    """A move past the next level from the session's reference close.

    Pre-market and the regular session compare with the previous close. After
    hours compares with the day's own close, so an earnings reaction alerts on
    its own instead of repeating the day's move.
    """
    reference: Literal["previous_close", "regular_close"] = "previous_close"
    base = quote.previous_close
    if quote.session == "post" and quote.regular_close is not None:
        reference, base = "regular_close", quote.regular_close
    if base is None:
        return None
    change = (quote.price / base - 1) * 100
    if abs(change) < move_at:
        return None
    level = move_at + step * math.floor((abs(change) - move_at) / step)
    direction: Literal["up", "down"] = "up" if change > 0 else "down"
    if level <= seen.levels.get((quote.symbol, direction, reference), 0.0):
        return None
    return _alert(quote, index, "move", direction, change, level, base, reference, None)


def _jump(
    quote: Quote, index: bool, jump_at: float, window: int, seen: Seen
) -> NewAlert | None:
    cutoff = quote.quoted_at - timedelta(minutes=window)
    earlier = [close for stamp, close in quote.bars if stamp <= cutoff]
    if not earlier:
        return None
    base = earlier[-1]
    change = (quote.price / base - 1) * 100
    if abs(change) < jump_at:
        return None
    direction: Literal["up", "down"] = "up" if change > 0 else "down"
    last = seen.jumps.get((quote.symbol, direction))
    if last is not None and quote.quoted_at - last < timedelta(minutes=window):
        return None
    return _alert(quote, index, "jump", direction, change, jump_at, base, "window", window)


def _alert(
    quote: Quote,
    index: bool,
    kind: Literal["move", "jump"],
    direction: Literal["up", "down"],
    change: float,
    level: float,
    base: float,
    reference: Literal["previous_close", "regular_close", "window"],
    window: int | None,
) -> NewAlert:
    return NewAlert(
        symbol=quote.symbol,
        name=quote.name,
        instrument="index" if index else "stock",
        kind=kind,
        direction=direction,
        change_pct=round(change, 2),
        level_pct=round(level, 4),
        price=quote.price,
        reference_price=base,
        reference=reference,
        window_minutes=window,
        session=quote.session or "regular",
        market_date=quote.quoted_at.astimezone(NEW_YORK).date().isoformat(),
        quoted_at=quote.quoted_at.isoformat(),
    )


def _remember(seen: Seen, alert: NewAlert) -> None:
    if alert.kind == "move":
        seen.levels[(alert.symbol, alert.direction, alert.reference)] = alert.level_pct
    else:
        seen.jumps[(alert.symbol, alert.direction)] = datetime.fromisoformat(alert.quoted_at)


# --- words ----------------------------------------------------------------------

_REFERENCE_WORDS: Final[dict[str, str]] = {
    "previous_close": "since the previous close",
    "regular_close": "since today's close, in after-hours trading",
}
_SESSION_WORDS: Final[dict[str, str]] = {
    "pre": "pre-market",
    "regular": "regular session",
    "post": "after hours",
}


def describe(alert: NewAlert | MarketAlert) -> str:
    """``MU (Micron Technology, Inc.) down 5.21% since the previous close, at 975.40``."""
    label = alert.symbol if alert.name is None else f"{alert.symbol} ({alert.name})"
    since = (
        f"in {alert.window_minutes} minutes"
        if alert.reference == "window"
        else _REFERENCE_WORDS[alert.reference]
    )
    unit = "" if alert.instrument == "index" else " USD"
    return (
        f"{label} {alert.direction} {abs(alert.change_pct):.2f}% {since}, "
        f"at {alert.price:,.2f}{unit}"
    )


def _when(alerts: list[NewAlert] | list[MarketAlert]) -> str:
    first = alerts[0]
    at = datetime.fromisoformat(first.quoted_at).astimezone(NEW_YORK)
    return f"{at:%A %Y-%m-%d %H:%M} New York time ({_SESSION_WORDS[first.session]})"


def explanation_goal(alerts: list[MarketAlert], note_path: str) -> str:
    lines = "\n".join(f"- {describe(alert)}." for alert in alerts)
    return (
        f"Market alert, {_when(alerts)}:\n{lines}\n\n"
        f"Ask market-explainer to find the most likely reason for these moves from "
        f"today's headlines and the space's saved research, and to write {note_path}. "
        "If no source explains a move, the note says so plainly. This explains what "
        "happened for a person to read; it predicts and recommends nothing, and "
        "nothing is bought or sold."
    )


def explanation_title(alerts: list[MarketAlert]) -> str:
    """The Runs view's name for an explaining run: `Market alert: MU, ^IXIC`."""
    return "Market alert: " + ", ".join(dict.fromkeys(alert.symbol for alert in alerts))


def alert_message(alerts: list[NewAlert] | list[MarketAlert], *, explaining: bool) -> str:
    lines = "\n".join(f"- {describe(alert)}" for alert in alerts)
    tail = "\nLooking for the reason now." if explaining else ""
    return f"Market alert, {_when(alerts)}:\n{lines}{tail}"


# --- the watcher ----------------------------------------------------------------


class MonitorStatus(BaseModel):
    """What the window shows about one space's watch."""

    enabled: bool
    error: str | None = None
    symbols: list[str] = Field(default_factory=list)
    check_every_minutes: int = 5
    market_open: bool = False
    last_checked_at: str | None = None
    next_check_at: str | None = None
    problems: list[str] = Field(default_factory=list)
    explain: bool = True
    explanations_today: int = 0
    max_explanations_per_day: int = 10
    #: The thresholds in force, so the window can say what raises an alert.
    stock_move_pct: float = 5
    stock_jump_pct: float = 2.5
    index_move_pct: float = 1.5
    index_jump_pct: float = 1
    jump_window_minutes: int = 15


@dataclass
class MarketMonitor:
    """One task in the sidecar that watches every space that asks for it."""

    spaces: SpaceStore
    alerts: AlertStore
    launcher: RunLauncher
    events: EventStore
    #: Post a message to the alerts channel; ``False`` when none is set up.
    announce: Callable[[str], Awaitable[bool]] | None = None
    clock: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))
    client_factory: Callable[[], httpx2.AsyncClient] = field(
        default=lambda: httpx2.AsyncClient(timeout=20)
    )
    poll_seconds: float = POLL_SECONDS
    #: Nothing is checked or explained while the computer has only just woken.
    wakefulness: Wakefulness | None = None
    _status: dict[str, MonitorStatus] = field(default_factory=dict, init=False)
    _checked: dict[str, datetime] = field(default_factory=dict, init=False)
    _task: asyncio.Task[None] | None = field(default=None, init=False)
    _wake: asyncio.Event = field(default_factory=asyncio.Event, init=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)
    _closed: bool = field(default=False, init=False)

    # --- lifecycle ----------------------------------------------------------

    async def start(self) -> None:
        self._task = asyncio.create_task(self._drive(), name="market-monitor")

    async def aclose(self) -> None:
        self._closed = True
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    def wake(self) -> None:
        """Look again now, as after the person turns a watch on."""
        self._wake.set()

    async def _drive(self) -> None:
        while not self._closed:
            try:
                await self.tick()
            except Exception:
                logger.exception("a market watch pass failed")
            self._wake.clear()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), timeout=self.poll_seconds)

    # --- one pass -----------------------------------------------------------

    async def tick(self) -> None:
        if self.wakefulness is not None and not self.wakefulness.settled():
            return
        async with self._lock:
            space = await self.spaces.get(DEFAULT_SPACE_ID)
            if space is None or space.archived:
                return
            try:
                await self._check_space(space)
            except Exception:
                logger.exception("watching space %s failed", space.id)

    def status(self, space_id: str) -> MonitorStatus | None:
        return self._status.get(space_id)

    async def read_status(self, space: Space) -> MonitorStatus:
        """The file as it is now, with what the loop last saw.

        The file is read on every request: a person who just edited it should
        not see the previous version's settings or error for a minute.
        """
        config, error = self._config(space)
        known = self._status.get(space.id)
        market_date = self.clock().astimezone(NEW_YORK).date().isoformat()
        return self._describe(
            space,
            config,
            error,
            problems=[] if known is None else known.problems,
            symbols=None if known is None else known.symbols,
            explanations=await self.alerts.explanations_started(space.id, market_date),
        )

    def _config(self, space: Space) -> tuple[MonitorConfig | None, str | None]:
        sandbox = Sandbox(self.spaces.folder_for(space.id))
        try:
            body = read_local(sandbox.resolve_path(MONITOR_PATH), 100_000)
        except (ToolExecutionError, SandboxViolationError, OSError) as exc:
            return None, str(exc)
        if not body:
            return None, None
        try:
            return parse_config(body.decode("utf-8-sig")), None
        except (MonitorConfigError, UnicodeDecodeError) as exc:
            return None, str(exc)

    def _describe(
        self,
        space: Space,
        config: MonitorConfig | None,
        error: str | None,
        *,
        problems: list[str],
        symbols: list[str] | None = None,
        explanations: int = 0,
    ) -> MonitorStatus:
        now = self.clock()
        checked = self._checked.get(space.id)
        enabled = config is not None and config.enabled
        due = (
            None
            if config is None or not enabled
            else (checked + timedelta(minutes=config.check_every_minutes) if checked else now)
        )
        shown = config if config is not None else MonitorConfig()
        return MonitorStatus(
            enabled=enabled,
            error=error,
            symbols=symbols or [],
            check_every_minutes=shown.check_every_minutes,
            market_open=within_market_hours(now),
            last_checked_at=None if checked is None else checked.isoformat(),
            next_check_at=None if due is None else due.isoformat(),
            problems=problems,
            explain=shown.explain,
            explanations_today=explanations,
            max_explanations_per_day=shown.max_explanations_per_day,
            stock_move_pct=shown.stock_move_pct,
            stock_jump_pct=shown.stock_jump_pct,
            index_move_pct=shown.index_move_pct,
            index_jump_pct=shown.index_jump_pct,
            jump_window_minutes=shown.jump_window_minutes,
        )

    async def _check_space(self, space: Space) -> None:
        config, error = self._config(space)
        if config is None or not config.enabled:
            self._status[space.id] = self._describe(space, config, error, problems=[])
            return
        now = self.clock()
        market_date = now.astimezone(NEW_YORK).date().isoformat()
        await self._start_queued(space, config, market_date)
        last = self._checked.get(space.id)
        due = last is None or now - last >= timedelta(minutes=config.check_every_minutes)
        if not within_market_hours(now) or not due:
            explanations = await self.alerts.explanations_started(space.id, market_date)
            known = self._status.get(space.id)
            self._status[space.id] = self._describe(
                space,
                config,
                None,
                problems=[] if known is None else known.problems,
                symbols=None if known is None else known.symbols,
                explanations=explanations,
            )
            return
        sandbox = Sandbox(self.spaces.folder_for(space.id))
        problems: list[str] = []
        symbols = _followed(sandbox, config, problems)
        self._checked[space.id] = now
        quotes: dict[str, Quote] = {}
        if symbols:
            client = self.client_factory()
            try:
                quotes, fetch_problems = await fetch_quotes(client, sandbox, symbols)
            finally:
                await client.aclose()
            problems.extend(fetch_problems)
        seen = Seen.from_alerts(await self.alerts.day(space.id, market_date))
        found = detect(quotes.values(), config, seen, now=now)
        if found:
            await self._alert(space, config, found, now)
        explanations = await self.alerts.explanations_started(space.id, market_date)
        self._status[space.id] = self._describe(
            space, config, None, problems=problems, symbols=symbols, explanations=explanations
        )

    async def _alert(
        self, space: Space, config: MonitorConfig, found: list[NewAlert], now: datetime
    ) -> None:
        market_date = found[0].market_date
        started = await self.alerts.explanations_started(space.id, market_date)
        if not config.explain:
            status: Literal["queued", "skipped", "off"] = "off"
        elif started >= config.max_explanations_per_day:
            status = "skipped"
        else:
            status = "queued"
        path = _note_path(self.spaces.folder_for(space.id), now) if status == "queued" else None
        recorded = await self.alerts.record_batch(
            space.id, found, status=status, explanation_path=path, now=now
        )
        logger.info("space %s: %d market alert(s)", space.id, len(recorded))
        await self._announce(alert_message(recorded, explaining=status == "queued"))
        if status == "queued":
            await self._start_queued(space, config, market_date)

    async def _start_queued(
        self, space: Space, config: MonitorConfig, market_date: str
    ) -> None:
        """Start the oldest waiting explanation when nothing else runs in the space."""
        batches = await self.alerts.queued(space.id)
        if not batches or await self._busy(space.id):
            return
        batch = batches[0]
        if await self.alerts.explanations_started(space.id, market_date) >= (
            config.max_explanations_per_day
        ):
            for waiting in batches:
                await self.alerts.set_batch(waiting.batch_id, "skipped")
            return
        try:
            run = await self.launcher.launch(
                explanation_goal(list(batch.alerts), batch.explanation_path),
                space_id=space.id,
                origin="monitor",
                origin_ref=batch.batch_id,
                title=explanation_title(list(batch.alerts)),
                max_run_seconds=EXPLANATION_SECONDS,
            )
        except Exception:
            logger.exception("could not start the explanation for batch %s", batch.batch_id)
            await self.alerts.set_batch(batch.batch_id, "failed")
            return
        await self.alerts.set_batch(batch.batch_id, "running", run_id=run.id)

    async def _busy(self, space_id: str) -> bool:
        runs = await self.events.list_runs(limit=20, space_id=space_id)
        return any(run.status in _UNFINISHED for run in runs)

    # --- when an explanation ends --------------------------------------------

    async def follow(self, run_id: str) -> None:
        """Launcher hook for every finished run; never raises into the launcher."""
        try:
            await self._finished(run_id)
        except Exception:
            logger.exception("could not record the explanation from run %s", run_id)

    async def _finished(self, run_id: str) -> None:
        if self._closed:
            return
        batch = await self.alerts.for_run(run_id)
        if batch:
            run = await self.events.get_run(run_id)
            first = batch[0]
            summary = None
            if run is not None and run.status == "completed" and first.explanation_path:
                summary = _note_summary(
                    Sandbox(self.spaces.folder_for(first.space_id)), first.explanation_path
                )
            if summary is None:
                await self.alerts.set_batch(first.batch_id, "failed")
                await self._announce(
                    "The explanation for the market alert could not be completed; "
                    "its run in AgentBase shows why."
                )
            else:
                await self.alerts.set_batch(first.batch_id, "done", explanation=summary)
                symbols = ", ".join(alert.symbol for alert in batch)
                await self._announce(f"Why {symbols} moved: {summary}")
        # A space that just finished one run may start a waiting explanation.
        self.wake()

    async def _announce(self, text: str) -> None:
        if self.announce is None:
            return
        try:
            await self.announce(text)
        except Exception:
            logger.exception("could not post a market alert")

    # --- turning it on and off ---------------------------------------------------

    def set_enabled(self, space: Space, *, enabled: bool) -> None:
        """Flip ``enabled`` in the file, writing the starter file the first time."""
        sandbox = Sandbox(self.spaces.folder_for(space.id))
        path = sandbox.resolve_write_path(MONITOR_PATH)
        body = read_local(path, 100_000)
        if not body:
            text = default_config_text(enabled=enabled)
        else:
            try:
                raw = json.loads(body.decode("utf-8-sig"))
            except (ValueError, UnicodeDecodeError) as exc:
                msg = f"{MONITOR_PATH} is not valid JSON, so it was left alone: {exc}"
                raise MonitorConfigError(msg) from exc
            if not isinstance(raw, dict):
                msg = f"{MONITOR_PATH} must hold one JSON object."
                raise MonitorConfigError(msg)
            raw["enabled"] = enabled
            parse_config(json.dumps(raw))
            text = json.dumps(raw, indent=2) + "\n"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        self._status.pop(space.id, None)
        self._checked.pop(space.id, None)
        self.wake()


def _followed(sandbox: Sandbox, config: MonitorConfig, problems: list[str]) -> list[str]:
    """Holdings, watchlist and listed symbols, then the indexes, at most 60."""
    symbols: list[str] = []

    def add(value: Any) -> None:
        if not isinstance(value, str):
            return
        symbol = value.strip().upper()
        if symbol == "CASH" or _SYMBOL.fullmatch(symbol) is None or symbol in symbols:
            return
        symbols.append(symbol)

    if config.follow_holdings:
        try:
            body = read_local(sandbox.resolve_path("portfolio/positions.csv"))
            for row in csv.DictReader(StringIO(body.decode("utf-8-sig"))):
                add(row.get("ticker"))
        except (
            ToolExecutionError,
            SandboxViolationError,
            OSError,
            UnicodeError,
            csv.Error,
        ) as exc:
            problems.append(f"Holdings could not be read: {exc}")
    if config.follow_watchlist:
        try:
            body = read_local(sandbox.resolve_path("config/watchlist.json"))
            document = json.loads(body) if body else {}
            entries = document.get("watchlist", []) if isinstance(document, dict) else []
            for entry in entries if isinstance(entries, list) else []:
                if isinstance(entry, dict):
                    add(entry.get("ticker", entry.get("symbol")))
        except (ToolExecutionError, SandboxViolationError, OSError, ValueError) as exc:
            problems.append(f"The watchlist could not be read: {exc}")
    for symbol in [*config.symbols, *config.indexes]:
        add(symbol)
    if len(symbols) > MAX_SYMBOLS:
        problems.append(f"Only the first {MAX_SYMBOLS} symbols are watched.")
    return symbols[:MAX_SYMBOLS]


def _note_path(folder: Path, now: datetime) -> str:
    """``alerts/2026-10-13-1205.md`` in New York time, unique in the folder."""
    local = now.astimezone(NEW_YORK)
    stem = f"alerts/{local:%Y-%m-%d-%H%M}"
    candidate, copy = f"{stem}.md", 2
    while (folder / candidate).exists():
        candidate, copy = f"{stem}-{copy}.md", copy + 1
    return candidate


def _note_summary(sandbox: Sandbox, path: str) -> str | None:
    """The note's likely reason, else its first paragraph, as plain text."""
    try:
        body = read_local(sandbox.resolve_path(path), 200_000)
    except (ToolExecutionError, SandboxViolationError, OSError):
        return None
    if not body:
        return None
    text = body.decode("utf-8", errors="replace")
    reason = re.search(r"\*\*Likely reason:\*\*\s*(.+?)(?:\n\s*\n|\n\*\*|$)", text, re.DOTALL)
    if reason is not None:
        found = reason.group(1)
    else:
        paragraphs = [
            block.strip()
            for block in re.split(r"\n\s*\n", text)
            if block.strip() and not block.lstrip().startswith("#")
        ]
        if not paragraphs:
            return None
        found = paragraphs[0]
    plain = " ".join(re.sub(r"[*_`#>]", "", found).split())
    return plain[:400] or None
