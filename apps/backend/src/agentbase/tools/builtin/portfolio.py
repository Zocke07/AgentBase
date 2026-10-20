"""Deterministic portfolio arithmetic over the stable Phase 17 files."""

from __future__ import annotations

import asyncio
import csv
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal, DecimalException, InvalidOperation
from io import StringIO
from typing import TYPE_CHECKING, Any, Final

from agentbase.tools.base import Prepared, ToolArgumentError, ToolExecutionError
from agentbase.tools.catalogue import RiskLevel, lookup

if TYPE_CHECKING:
    from pathlib import Path

    from agentbase.tools.sandbox import Sandbox

__all__ = ["ComputePortfolioTool", "is_supported_currency"]

_POSITIONS_PATH: Final[str] = "portfolio/positions.csv"
_PRICES_PATH: Final[str] = "raw/prices/summary.csv"
_LIMITS_PATH: Final[str] = "config/limits.json"
_COMPUTED_PATH: Final[str] = "portfolio/computed.json"
_WEIGHTS_PATH: Final[str] = "portfolio/weights.csv"
_POSITION_COLUMNS: Final[frozenset[str]] = frozenset(
    {"ticker", "shares", "cost_per_share", "opened", "sector", "currency"}
)
_PRICE_COLUMNS: Final[frozenset[str]] = frozenset(
    {"ticker", "date", "close", "prev_close", "currency"}
)
_LIMIT_NAMES: Final[tuple[str, ...]] = (
    "max_position_pct",
    "max_sector_pct",
    "max_daily_loss_pct",
)
_TICKER: Final[re.Pattern[str]] = re.compile(r"^[A-Z0-9^=._-]{1,20}$")
_DATE: Final[re.Pattern[str]] = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MONEY: Final[Decimal] = Decimal("0.01")
_PERCENT: Final[Decimal] = Decimal("0.0001")

# Active ISO 4217 alphabetic codes, including funds, metals, testing, and
# no-currency codes. Checked against the SIX Maintenance Agency's List One on
# 2026-09-30. Keeping the set here makes validation deterministic and avoids a
# network or locale dependency in a local arithmetic tool.
_CURRENCIES: Final[frozenset[str]] = frozenset(
    """
    AED AFN ALL AMD AOA ARS AUD AWG AZN BAM BBD BDT BHD BIF BMD BND
    BOB BOV BRL BSD BTN BWP BYN BZD CAD CDF CHE CHF CHW CLF CLP CNY COP
    COU CRC CUP CVE CZK DJF DKK DOP DZD EGP ERN ETB EUR FJD FKP GBP GEL
    GHS GIP GMD GNF GTQ GYD HKD HNL HTG HUF IDR ILS INR IQD IRR ISK JMD
    JOD JPY KES KGS KHR KMF KPW KRW KWD KYD KZT LAK LBP LKR LRD LSL LYD
    MAD MDL MGA MKD MMK MNT MOP MRU MUR MVR MWK MXN MXV MYR MZN NAD NGN
    NIO NOK NPR NZD OMR PAB PEN PGK PHP PKR PLN PYG QAR RON RSD RUB RWF
    SAR SBD SCR SDG SEK SGD SHP SLE SOS SRD SSP STN SVC SYP SZL THB TJS
    TMT TND TOP TRY TTD TWD TZS UAH UGX USD USN UYI UYU UYW UZS VED VES
    VND VUV WST XAD XAF XAG XAU XBA XBB XBC XBD XCD XCG XDR XOF XPD XPF XPT XSU
    XTS XUA XXX YER ZAR ZMW ZWG
    """.split()  # noqa: SIM905 - the official list is reviewable in this form
)


def is_supported_currency(code: str) -> bool:
    """Whether a book currency is accepted by the portfolio arithmetic."""
    return code in _CURRENCIES


@dataclass(frozen=True, slots=True)
class _Position:
    ticker: str
    shares: Decimal
    cost_per_share: Decimal | None
    opened: date | None
    sector: str
    currency: str


@dataclass(frozen=True, slots=True)
class _Price:
    ticker: str
    date: date
    close: Decimal
    previous: Decimal
    currency: str


@dataclass(frozen=True, slots=True)
class _Calculated:
    position: _Position
    price: _Price
    value: Decimal
    previous_value: Decimal
    unrealised: Decimal | None
    weight: Decimal


def _declaration(name: str) -> tuple[str, RiskLevel]:
    declaration = lookup(name)
    if declaration is None:  # pragma: no cover: registry test pins this
        msg = f"{name!r} has an implementation but no catalogue entry"
        raise RuntimeError(msg)
    return declaration.description, declaration.risk


class ComputePortfolioTool:
    """Read the saved book and prices, then write exact portfolio figures."""

    name = "compute_portfolio"

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
                "as_of": {
                    "type": "string",
                    "description": (
                        "Optional calculation date as YYYY-MM-DD. Leave it out in "
                        "the daily pipeline: the book is then computed for the "
                        "newest saved market session, the date the theses and "
                        "limit checks use. Give it only to recompute an earlier date."
                    ),
                }
            },
            "required": [],
        }

    def prepare(self, arguments: dict[str, Any], sandbox: Sandbox) -> Prepared:
        as_of = arguments.get("as_of")
        if as_of is not None:
            if not isinstance(as_of, str):
                msg = f"{self.name}'s 'as_of' must be a YYYY-MM-DD string."
                raise ToolArgumentError(msg)
            try:
                parsed = _parse_date(as_of, "as_of")
            except ToolExecutionError as exc:
                raise ToolArgumentError(str(exc)) from exc
            as_of = parsed.isoformat()

        return Prepared(
            tool_name=self.name,
            summary=("compute the portfolio from portfolio/positions.csv and the saved prices"),
            payload={
                "as_of": as_of,
                "positions_path": sandbox.resolve_path(_POSITIONS_PATH),
                "prices_path": sandbox.resolve_path(_PRICES_PATH),
                "limits_path": sandbox.resolve_path(_LIMITS_PATH),
                "computed_path": sandbox.resolve_write_path(_COMPUTED_PATH),
                "weights_path": sandbox.resolve_write_path(_WEIGHTS_PATH),
            },
            raw_arguments=dict(arguments),
        )

    async def execute(self, prepared: Prepared, sandbox: Sandbox) -> str:
        try:
            result = await asyncio.to_thread(_compute, prepared.payload, sandbox)
        except DecimalException as exc:
            raise ToolExecutionError(
                "portfolio inputs contain a number outside the supported range."
            ) from exc
        # For the run view only; computed.json was written without it.
        reported = {**result, "written": [_COMPUTED_PATH, _WEIGHTS_PATH]}
        return json.dumps(reported, ensure_ascii=False, separators=(",", ":"))


def _compute(payload: dict[str, Any], sandbox: Sandbox) -> dict[str, Any]:
    positions_path: Path = payload["positions_path"]
    prices_path: Path = payload["prices_path"]
    limits_path: Path = payload["limits_path"]
    computed_path: Path = payload["computed_path"]
    weights_path: Path = payload["weights_path"]

    # No holdings recorded yet is a state to report, not a failure: an error
    # here stopped the whole daily chain before any thesis was written.
    empty = _records_nothing(positions_path)
    positions = [] if empty else _read_positions(positions_path)
    held = [position for position in positions if position.ticker != "CASH"]
    prices = _read_prices(prices_path, {position.ticker for position in held})
    limits = _read_limits(limits_path)
    positions_date = _modified_date(positions_path) if positions_path.exists() else None
    explicit_as_of = payload["as_of"]
    if explicit_as_of is not None:
        as_of = _parse_date(explicit_as_of, "as_of")
    elif prices:
        as_of = max(price.date for price in prices.values())
    else:
        # Nothing held sets a price date. The save date of positions.csv made
        # check_limits refuse every later session's theses, so use the session
        # the watchlist was priced for, which those theses are dated by.
        as_of = _newest_session(prices_path) or positions_date or datetime.now(UTC).date()

    book_currency = (
        _session_currency(prices_path)
        if empty
        else _one_currency(position.currency for position in positions)
    )
    all_currencies = {
        currency
        for currency in (book_currency, *(price.currency for price in prices.values()))
        if currency is not None
    }
    if len(all_currencies) > 1:
        raise ToolExecutionError(
            f"{ComputePortfolioTool.name} cannot mix currencies: "
            f"{_list_words(sorted(all_currencies))}."
        )

    by_ticker = {position.ticker: position for position in held}
    missing = sorted(set(by_ticker) - set(prices))
    if missing:
        raise ToolExecutionError(
            f"{_PRICES_PATH} has no saved price for {_list_words(missing)}. "
            "Run read_prices for every held ticker, then try again."
        )

    for ticker, price in prices.items():
        if price.date > as_of:
            raise ToolExecutionError(
                f"{ticker}'s saved price date {price.date.isoformat()} is after "
                f"the requested as_of date {as_of.isoformat()}."
            )

    cash_position = next(
        (position for position in positions if position.ticker == "CASH"), None
    )
    cash = cash_position.shares if cash_position is not None else Decimal(0)
    provisional: list[tuple[_Position, _Price, Decimal, Decimal, Decimal | None]] = []
    for ticker in sorted(by_ticker):
        position = by_ticker[ticker]
        price = prices[ticker]
        if position.opened is not None and position.opened > as_of:
            raise ToolExecutionError(
                f"{_POSITIONS_PATH} says {ticker} opened on "
                f"{position.opened.isoformat()}, after as_of {as_of.isoformat()}."
            )
        value = position.shares * price.close
        previous_value = position.shares * price.previous
        unrealised = (
            None
            if position.cost_per_share is None
            else value - (position.shares * position.cost_per_share)
        )
        provisional.append((position, price, value, previous_value, unrealised))

    invested = sum((row[2] for row in provisional), start=Decimal(0))
    total = cash + invested
    calculated = [
        _Calculated(
            position=position,
            price=price,
            value=value,
            previous_value=previous_value,
            unrealised=unrealised,
            weight=_percent(value, total) or Decimal(0),
        )
        for position, price, value, previous_value, unrealised in provisional
    ]
    previous_total = cash + sum(
        (position.previous_value for position in calculated), start=Decimal(0)
    )
    day_change = total - previous_total
    day_change_pct = _percent(day_change, previous_total)
    cost_complete = all(position.unrealised is not None for position in calculated)
    unrealised = (
        sum((position.unrealised or Decimal(0) for position in calculated), start=Decimal(0))
        if cost_complete
        else None
    )
    cost_basis = sum(
        (
            position.position.shares * (position.position.cost_per_share or Decimal(0))
            for position in calculated
        ),
        start=Decimal(0),
    )
    unrealised_pct = None if unrealised is None else _percent(unrealised, cost_basis)

    sector_values: dict[str, Decimal] = {}
    for calculated_position in calculated:
        sector_values[calculated_position.position.sector] = (
            sector_values.get(calculated_position.position.sector, Decimal(0))
            + calculated_position.value
        )
    sector_weights = {
        sector: _percent(value, total) or Decimal(0)
        for sector, value in sorted(sector_values.items())
    }
    weights = sorted((position.weight for position in calculated), reverse=True)
    largest = weights[0] if weights else Decimal(0)
    top3 = sum(weights[:3], start=Decimal(0))
    crossings = _limit_crossings(calculated, sector_weights, day_change_pct, limits)

    reason = "positions.csv is a current snapshot without transaction history."
    result: dict[str, Any] = {
        "as_of": as_of.isoformat(),
        "positions_date": None if positions_date is None else positions_date.isoformat(),
        "stale": not empty and positions_date is not None and (as_of - positions_date).days > 3,
        "empty_book": empty,
        "price_dates": {ticker: prices[ticker].date.isoformat() for ticker in sorted(prices)},
        "currency": book_currency,
        "total_value": _json_number(total, _MONEY),
        "cash": _json_number(cash, _MONEY),
        "invested": _json_number(invested, _MONEY),
        "day_change": _json_number(day_change, _MONEY),
        "day_change_pct": _json_optional(day_change_pct, _PERCENT),
        "unrealised": _json_optional(unrealised, _MONEY),
        "unrealised_pct": _json_optional(unrealised_pct, _PERCENT),
        "realised": None,
        "realised_reason": reason,
        "period_pnl": None,
        "period_pnl_reason": reason,
        "positions": [_position_result(position, as_of) for position in calculated],
        "concentration": {
            "largest_weight_pct": _json_number(largest, _PERCENT),
            "top3_weight_pct": _json_number(top3, _PERCENT),
            "sector_weights": {
                sector: _json_number(weight, _PERCENT)
                for sector, weight in sector_weights.items()
            },
            "limit_crossings": crossings,
        },
    }
    if not cost_complete:
        result["unrealised_reason"] = (
            "Purchase cost is unknown for some holdings. Fill cost_per_share in "
            "portfolio/positions.csv to calculate total unrealised P&L."
        )
    if empty:
        result["note"] = (
            f"{_POSITIONS_PATH} records no holdings or cash, so every value is 0. "
            "Add a CASH row and any holdings to it to size positions."
        )
    # Read before computed.json is replaced: the earlier valuation is the last report.
    result["since_previous"] = _since_previous(
        computed_path,
        sandbox,
        as_of,
        total,
        {item.position.ticker: item.price.close for item in calculated},
    )

    _write_outputs(
        computed_path,
        weights_path,
        result,
        calculated,
        cash_position,
        cash,
        total,
        book_currency or "",
    )
    return result


def _since_previous(
    computed_path: Path,
    sandbox: Sandbox,
    as_of: date,
    total: Decimal,
    closes: dict[str, Decimal],
) -> dict[str, Any] | None:
    """How the book moved since the last report, and the sessions between with none.

    The last report is the valuation computed.json holds before this one is
    written; valuing the same session again keeps the comparison it made.
    AgentBase closed for three mornings left 14 to 16 October unreported, and
    nothing said so (2026-10-20). Missing or unreadable history is reported
    as nothing to compare with, never as a failure of the valuation.
    """
    earlier = _earlier_valuation(computed_path)
    if earlier is None:
        return None
    valued = _iso_date(earlier.get("as_of"))
    if valued == as_of:
        kept = earlier.get("since_previous")
        if not isinstance(kept, dict):
            return None
        session = _iso_date(kept.get("session"))
        before = _number(kept.get("total_value"))
    else:
        session = valued
        before = _number(earlier.get("total_value"))
    if session is None or before is None or session >= as_of:
        return None

    histories = {ticker: _closes(sandbox, ticker) for ticker in closes}
    skipped = sorted(
        {day for history in histories.values() for day in history if session < day < as_of}
    )
    change = total - before
    return {
        "session": session.isoformat(),
        "skipped_sessions": [day.isoformat() for day in skipped],
        "total_value": _json_number(before, _MONEY),
        "value_change": _json_number(change, _MONEY),
        "value_change_pct": _json_optional(_percent(change, before), _PERCENT),
        "price_change_pct": {
            ticker: _json_optional(
                None
                if (then := histories[ticker].get(session)) is None
                else _percent(closes[ticker] - then, then),
                _PERCENT,
            )
            for ticker in sorted(closes)
        },
    }


def _earlier_valuation(path: Path) -> dict[str, Any] | None:
    try:
        earlier = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return None
    return earlier if isinstance(earlier, dict) else None


def _iso_date(value: Any) -> date | None:
    if not isinstance(value, str) or _DATE.fullmatch(value) is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _number(value: Any) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def _closes(sandbox: Sandbox, ticker: str) -> dict[date, Decimal]:
    """A holding's saved daily closes, from the year of history read_prices writes."""
    try:
        path = sandbox.resolve_path(f"raw/prices/{ticker}.csv")
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except (OSError, UnicodeError, csv.Error, ValueError):
        return {}
    closes: dict[date, Decimal] = {}
    for row in rows:
        day = _iso_date((row.get("date") or "").strip())
        try:
            close = Decimal((row.get("close") or "").strip())
        except InvalidOperation:
            continue
        if day is not None and close.is_finite() and close > 0:
            closes[day] = close
    return closes


def _read_positions(path: Path) -> list[_Position]:
    rows = _read_csv(path, _POSITIONS_PATH, _POSITION_COLUMNS)
    positions: list[_Position] = []
    seen: set[str] = set()
    for number, row in enumerate(rows, start=2):
        if not any((value or "").strip() for value in row.values()):
            continue
        ticker = (row.get("ticker") or "").strip().upper()
        if _TICKER.fullmatch(ticker) is None:
            raise ToolExecutionError(
                f"{_POSITIONS_PATH} row {number} has an invalid ticker {ticker!r}."
            )
        if ticker in seen:
            raise ToolExecutionError(
                f"{_POSITIONS_PATH} has duplicate ticker {ticker} on row {number}."
            )
        seen.add(ticker)
        currency = _currency(row.get("currency"), _POSITIONS_PATH, number)
        shares = _decimal(row.get("shares"), _POSITIONS_PATH, number, "shares")
        if shares < 0 or (ticker != "CASH" and shares == 0):
            raise ToolExecutionError(
                f"{_POSITIONS_PATH} row {number} shares must be positive, or "
                "zero only for CASH."
            )
        sector = (row.get("sector") or "").strip()
        if ticker == "CASH":
            positions.append(_Position(ticker, shares, None, None, sector or "Cash", currency))
            continue
        if not sector:
            raise ToolExecutionError(
                f"{_POSITIONS_PATH} row {number} needs a sector for {ticker}."
            )
        cost_text = (row.get("cost_per_share") or "").strip()
        cost = (
            _decimal(cost_text, _POSITIONS_PATH, number, "cost_per_share")
            if cost_text
            else None
        )
        if cost is not None and cost <= 0:
            raise ToolExecutionError(
                f"{_POSITIONS_PATH} row {number} cost_per_share must be positive."
            )
        opened_text = (row.get("opened") or "").strip()
        opened = (
            _parse_date(opened_text, f"{_POSITIONS_PATH} row {number} opened")
            if opened_text
            else None
        )
        positions.append(_Position(ticker, shares, cost, opened, sector, currency))

    if not positions:
        raise ToolExecutionError(
            f"{_POSITIONS_PATH} has no positions. Keep at least the CASH row."
        )
    _one_currency(position.currency for position in positions)
    return positions


def _read_prices(path: Path, wanted: set[str]) -> dict[str, _Price]:
    if not wanted:
        return {}
    rows = _read_csv(path, _PRICES_PATH, _PRICE_COLUMNS)
    prices: dict[str, _Price] = {}
    for number, row in enumerate(rows, start=2):
        ticker = (row.get("ticker") or "").strip().upper()
        if ticker not in wanted:
            continue
        if ticker in prices:
            raise ToolExecutionError(
                f"{_PRICES_PATH} has duplicate ticker {ticker} on row {number}."
            )
        close = _decimal(row.get("close"), _PRICES_PATH, number, "close")
        previous = _decimal(row.get("prev_close"), _PRICES_PATH, number, "prev_close")
        if close <= 0 or previous <= 0:
            raise ToolExecutionError(f"{_PRICES_PATH} row {number} prices must be positive.")
        prices[ticker] = _Price(
            ticker=ticker,
            date=_parse_date(
                (row.get("date") or "").strip(),
                f"{_PRICES_PATH} row {number} date",
            ),
            close=close,
            previous=previous,
            currency=_currency(row.get("currency"), _PRICES_PATH, number),
        )
    return prices


def _newest_session(path: Path) -> date | None:
    """The latest session date in the saved price summary, if one was saved."""
    if not path.exists():
        return None
    rows = _read_csv(path, _PRICES_PATH, _PRICE_COLUMNS)
    return max(
        (
            _parse_date((row.get("date") or "").strip(), f"{_PRICES_PATH} row {number} date")
            for number, row in enumerate(rows, start=2)
        ),
        default=None,
    )


def _read_limits(path: Path) -> dict[str, Decimal]:
    if not path.exists():
        raise ToolExecutionError(
            f"There is no file at {_LIMITS_PATH}. Create it from the pipeline "
            "template, then try again."
        )
    try:
        document = json.loads(
            path.read_text(encoding="utf-8"),
            parse_float=Decimal,
            parse_int=Decimal,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ToolExecutionError(f"{_LIMITS_PATH} is not readable JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise ToolExecutionError(f"{_LIMITS_PATH} must contain one JSON object.")
    limits: dict[str, Decimal] = {}
    for name in _LIMIT_NAMES:
        value = document.get(name)
        if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
            raise ToolExecutionError(f"{_LIMITS_PATH} needs a non-negative numeric {name!r}.")
        limits[name] = value
    return limits


def _read_csv(
    path: Path,
    shown: str,
    required: frozenset[str],
) -> list[dict[str, str | None]]:
    if not path.exists():
        if shown == _PRICES_PATH:
            raise ToolExecutionError(f"There is no file at {shown}. Run read_prices first.")
        raise ToolExecutionError(f"There is no file at {shown} in the workspace.")
    if path.is_dir():
        raise ToolExecutionError(f"{shown} is a directory, not a CSV file.")
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            fields = set(reader.fieldnames or ())
            missing = sorted(required - fields)
            if missing:
                if missing == ["currency"] and shown == _POSITIONS_PATH:
                    raise ToolExecutionError(
                        f"{shown} is missing the required 'currency' column. "
                        "Add currency to the header and an uppercase ISO 4217 "
                        "code such as USD to every row."
                    )
                raise ToolExecutionError(
                    f"{shown} is missing required columns: {', '.join(missing)}."
                )
            return list(reader)
    except ToolExecutionError:
        raise
    except (OSError, UnicodeError, csv.Error) as exc:
        raise ToolExecutionError(f"{shown} could not be read as CSV: {exc}") from exc


def _currency(value: str | None, shown: str, row: int) -> str:
    currency = (value or "").strip()
    if currency not in _CURRENCIES:
        raise ToolExecutionError(
            f"{shown} row {row} currency {currency!r} is not a current "
            "uppercase ISO 4217 code such as USD."
        )
    return currency


def _one_currency(values: Iterable[str]) -> str:
    currencies = sorted(set(values))
    if len(currencies) != 1:
        raise ToolExecutionError(
            f"{_POSITIONS_PATH} cannot mix currencies: {_list_words(currencies)}."
        )
    return currencies[0]


def _decimal(
    value: str | None,
    shown: str,
    row: int,
    field: str,
) -> Decimal:
    try:
        parsed = Decimal((value or "").strip())
    except InvalidOperation as exc:
        raise ToolExecutionError(f"{shown} row {row} {field} must be a number.") from exc
    if not parsed.is_finite():
        raise ToolExecutionError(f"{shown} row {row} {field} must be finite.")
    return parsed


def _parse_date(value: str, label: str) -> date:
    try:
        if _DATE.fullmatch(value) is None:
            raise ValueError
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ToolExecutionError(f"{label} must be a real date in YYYY-MM-DD form.") from exc


def _records_nothing(path: Path) -> bool:
    """Missing, blank or a header alone: no holdings or cash are recorded yet."""
    if not path.exists():
        return True
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeError):
        return False  # Let the full reader report what is wrong with it.
    rows = [line for line in lines if line.strip(" ,\t")]
    return len(rows) <= 1 and (not rows or rows[0].strip().lower().startswith("ticker"))


def _session_currency(path: Path) -> str | None:
    """The saved prices' one currency, for an empty book; none when unclear."""
    if not path.exists():
        return None
    currencies = {
        (row.get("currency") or "").strip().upper()
        for row in _read_csv(path, _PRICES_PATH, _PRICE_COLUMNS)
    } - {""}
    return next(iter(currencies)) if len(currencies) == 1 else None


def _modified_date(path: Path) -> date:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, UTC).date()
    except OSError as exc:
        raise ToolExecutionError(
            f"{_POSITIONS_PATH}'s modified date could not be read: {exc}"
        ) from exc


def _percent(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    if denominator == 0:
        return None
    return numerator / denominator * Decimal(100)


def _position_result(position: _Calculated, as_of: date) -> dict[str, Any]:
    cost = position.position.cost_per_share
    opened = position.position.opened
    unrealised_pct = (
        None
        if cost is None or position.unrealised is None
        else _percent(position.unrealised, position.position.shares * cost)
    )
    return {
        "ticker": position.position.ticker,
        "shares": _json_number(position.position.shares),
        "weight_pct": _json_number(position.weight, _PERCENT),
        "cost_per_share": None if cost is None else _json_number(cost),
        "close": _json_number(position.price.close),
        "value": _json_number(position.value, _MONEY),
        "unrealised": _json_optional(position.unrealised, _MONEY),
        "unrealised_pct": _json_optional(unrealised_pct, _PERCENT),
        "days_held": None if opened is None else (as_of - opened).days,
        "sector": position.position.sector,
    }


def _limit_crossings(
    positions: list[_Calculated],
    sector_weights: dict[str, Decimal],
    day_change_pct: Decimal | None,
    limits: dict[str, Decimal],
) -> list[dict[str, Any]]:
    crossings: list[dict[str, Any]] = []
    for position in positions:
        threshold = limits["max_position_pct"]
        if position.weight > threshold:
            crossings.append(
                _crossing(
                    "max_position_pct",
                    position.position.ticker,
                    position.weight,
                    threshold,
                )
            )
    for sector, weight in sector_weights.items():
        threshold = limits["max_sector_pct"]
        if weight > threshold:
            crossings.append(_crossing("max_sector_pct", sector, weight, threshold))
    daily_threshold = limits["max_daily_loss_pct"]
    if day_change_pct is not None and day_change_pct < -daily_threshold:
        crossings.append(
            _crossing(
                "max_daily_loss_pct",
                "portfolio",
                day_change_pct,
                daily_threshold,
            )
        )
    return crossings


def _crossing(
    rule: str,
    subject: str,
    value: Decimal,
    threshold: Decimal,
) -> dict[str, Any]:
    return {
        "rule": rule,
        "subject": subject,
        "value": _json_number(value, _PERCENT),
        "threshold": _json_number(threshold, _PERCENT),
    }


def _write_outputs(
    computed_path: Path,
    weights_path: Path,
    result: dict[str, Any],
    positions: list[_Calculated],
    cash_position: _Position | None,
    cash: Decimal,
    total: Decimal,
    currency: str,
) -> None:
    try:
        computed_path.parent.mkdir(parents=True, exist_ok=True)
        computed_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="",
        )

        rows = [
            (
                position.position.ticker,
                position.weight,
                position.value,
                position.position.sector,
            )
            for position in positions
        ]
        if cash_position is not None:
            rows.append(
                ("CASH", _percent(cash, total) or Decimal(0), cash, cash_position.sector)
            )
        rows.sort(key=lambda row: row[0])
        output = StringIO(newline="")
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow(("ticker", "weight_pct", "value", "sector", "currency"))
        for ticker, weight, value, sector in rows:
            writer.writerow(
                (
                    ticker,
                    _fixed(weight, _PERCENT),
                    _fixed(value, _MONEY),
                    sector,
                    currency,
                )
            )
        weights_path.parent.mkdir(parents=True, exist_ok=True)
        weights_path.write_text(output.getvalue(), encoding="utf-8", newline="")
    except OSError as exc:
        raise ToolExecutionError(f"portfolio outputs could not be written: {exc}") from exc


def _fixed(value: Decimal, quantum: Decimal) -> str:
    exponent = quantum.as_tuple().exponent
    if not isinstance(exponent, int):  # pragma: no cover: fixed finite constants
        raise ValueError("quantum must be finite")
    places = -exponent
    rounded = value.quantize(quantum, rounding=ROUND_HALF_UP)
    return f"{rounded:.{places}f}"


def _json_number(value: Decimal, quantum: Decimal | None = None) -> int | float:
    rendered = _fixed(value, quantum) if quantum is not None else format(value, "f")
    parsed = Decimal(rendered)
    return int(parsed) if parsed == parsed.to_integral() else float(rendered)


def _json_optional(
    value: Decimal | None,
    quantum: Decimal,
) -> int | float | None:
    return None if value is None else _json_number(value, quantum)


def _list_words(values: list[str]) -> str:
    if not values:
        return "no currencies"
    if len(values) == 1:
        return values[0]
    if len(values) == 2:
        return f"{values[0]} and {values[1]}"
    return f"{', '.join(values[:-1])} and {values[-1]}"
