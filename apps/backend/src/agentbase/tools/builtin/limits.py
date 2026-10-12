"""Deterministic hard-rule checks over the stable Phase 17 files."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Mapping
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, DecimalException
from typing import TYPE_CHECKING, Any, Final

from agentbase.tools.base import Prepared, ToolArgumentError, ToolExecutionError
from agentbase.tools.catalogue import RiskLevel, lookup

if TYPE_CHECKING:
    from pathlib import Path

    from agentbase.tools.sandbox import Sandbox

__all__ = ["CheckLimitsTool"]

_COMPUTED_PATH: Final[str] = "portfolio/computed.json"
_LIMITS_PATH: Final[str] = "config/limits.json"
_WATCHLIST_PATH: Final[str] = "config/watchlist.json"
_LIMIT_NAMES: Final[tuple[str, ...]] = (
    "max_position_pct",
    "max_sector_pct",
    "max_daily_loss_pct",
)
_TICKER: Final[re.Pattern[str]] = re.compile(r"^[A-Z0-9^=._-]{1,20}$")
_DATE: Final[re.Pattern[str]] = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_PERCENT: Final[Decimal] = Decimal("0.0001")
_SOURCE_ORDER: Final[tuple[str, ...]] = ("portfolio", "bull", "bear")


def _declaration(name: str) -> tuple[str, RiskLevel]:
    declaration = lookup(name)
    if declaration is None:  # pragma: no cover: registry test pins this
        msg = f"{name!r} has an implementation but no catalogue entry"
        raise RuntimeError(msg)
    return declaration.description, declaration.risk


class CheckLimitsTool:
    """Write exact PASS or FAIL checks for held and thesis tickers."""

    name = "check_limits"

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
                "date": {
                    "type": "string",
                    "description": "The thesis date to check, in YYYY-MM-DD form.",
                }
            },
            "required": ["date"],
        }

    def prepare(self, arguments: dict[str, Any], sandbox: Sandbox) -> Prepared:
        requested = arguments.get("date")
        if requested is None:
            raise ToolArgumentError(f"{self.name} requires a 'date' in YYYY-MM-DD form.")
        if not isinstance(requested, str):
            raise ToolArgumentError(f"{self.name}'s 'date' must be a YYYY-MM-DD string.")
        try:
            checked_date = _parse_date(requested, "date").isoformat()
        except ToolExecutionError as exc:
            raise ToolArgumentError(str(exc)) from exc

        bull_path = f"theses/bull-{checked_date}.jsonl"
        bear_path = f"theses/bear-{checked_date}.jsonl"
        output_path = f"risk/rule-checks-{checked_date}.json"
        return Prepared(
            tool_name=self.name,
            summary=f"check portfolio and thesis limits for {checked_date}",
            payload={
                "date": checked_date,
                "computed_path": sandbox.resolve_path(_COMPUTED_PATH),
                "limits_path": sandbox.resolve_path(_LIMITS_PATH),
                "watchlist_path": sandbox.resolve_path(_WATCHLIST_PATH),
                "universe_path": sandbox.resolve_path("raw/market/universe.json"),
                "bull_path": sandbox.resolve_path(bull_path),
                "bear_path": sandbox.resolve_path(bear_path),
                "output_path": sandbox.resolve_write_path(output_path),
            },
            raw_arguments=dict(arguments),
        )

    async def execute(self, prepared: Prepared, sandbox: Sandbox) -> str:
        try:
            result = await asyncio.to_thread(_check, prepared.payload)
        except DecimalException as exc:
            raise ToolExecutionError(
                "portfolio or limit inputs contain a number outside the supported range."
            ) from exc
        # For the run view only; the checks file was written without it.
        reported = {**result, "written": [sandbox.relative(prepared.payload["output_path"])]}
        return json.dumps(reported, ensure_ascii=False, separators=(",", ":"))


def _check(payload: dict[str, Any]) -> dict[str, Any]:
    checked_date: str = payload["date"]
    computed = _read_object(
        payload["computed_path"], _COMPUTED_PATH, "Run compute_portfolio first."
    )
    limits = _read_limits(payload["limits_path"])
    watchlist = _read_watchlist(payload["watchlist_path"])
    configured_tickers = set(watchlist)
    universe_path: Path = payload["universe_path"]
    if universe_path.exists():
        universe = _read_object(universe_path, "raw/market/universe.json", "Run read_market.")
        rows = universe.get("universe", [])
        if not isinstance(rows, list):
            raise ToolExecutionError("raw/market/universe.json needs a universe array.")
        for row in rows:
            if not isinstance(row, dict):
                continue
            ticker, sector = row.get("ticker"), row.get("sector")
            if isinstance(ticker, str) and isinstance(sector, str) and sector.strip():
                watchlist.setdefault(ticker, sector.strip())
    bull_path: Path = payload["bull_path"]
    bear_path: Path = payload["bear_path"]
    bull = _read_theses(bull_path, f"theses/bull-{checked_date}.jsonl")
    bear = _read_theses(bear_path, f"theses/bear-{checked_date}.jsonl")

    as_of = computed.get("as_of")
    if not isinstance(as_of, str):
        raise ToolExecutionError(f"{_COMPUTED_PATH} needs a YYYY-MM-DD 'as_of'.")
    parsed_as_of = _parse_date(as_of, f"{_COMPUTED_PATH} 'as_of'").isoformat()
    if parsed_as_of != checked_date:
        raise ToolExecutionError(
            f"{_COMPUTED_PATH} is for {parsed_as_of}, not thesis date {checked_date}. "
            "Run compute_portfolio for the thesis date, then try again."
        )

    positions = _read_positions(computed)
    for ticker, held_position in positions.items():
        if ticker not in configured_tickers:
            # A holding need not also be on the watchlist. The person's book
            # supplies its sector ahead of optional discovered metadata.
            watchlist[ticker] = held_position["sector"]
    sector_weights = _read_sector_weights(computed)
    daily_change = _optional_decimal(
        computed.get("day_change_pct"),
        f"{_COMPUTED_PATH} 'day_change_pct'",
    )
    daily_loss = max(Decimal(0), -(daily_change or Decimal(0)))

    thesis_tickers = bull | bear
    for ticker in sorted(thesis_tickers):
        if ticker not in watchlist:
            raise ToolExecutionError(
                f"thesis ticker {ticker} is not in {_WATCHLIST_PATH}. Add it with a "
                "non-empty sector, then try again."
            )
    for ticker, held_position in positions.items():
        configured_sector = watchlist.get(ticker)
        if ticker in thesis_tickers and configured_sector != held_position["sector"]:
            raise ToolExecutionError(
                f"{ticker} has sector {configured_sector!r} in {_WATCHLIST_PATH} but "
                f"{held_position['sector']!r} in {_COMPUTED_PATH}. Make the sectors match."
            )

    sources: dict[str, set[str]] = {}
    for ticker in positions:
        sources.setdefault(ticker, set()).add("portfolio")
    for ticker in bull:
        sources.setdefault(ticker, set()).add("bull")
    for ticker in bear:
        sources.setdefault(ticker, set()).add("bear")

    items: list[dict[str, Any]] = []
    for ticker in sorted(sources):
        position = positions.get(ticker)
        held = position is not None
        sector = position["sector"] if position is not None else watchlist[ticker]
        weight = position["weight"] if position is not None else Decimal(0)
        if sector not in sector_weights and held:
            raise ToolExecutionError(
                f"{_COMPUTED_PATH} has position {ticker} in {sector!r} but no matching "
                "sector weight. Run compute_portfolio again."
            )
        sector_weight = sector_weights.get(sector, Decimal(0))
        items.append(
            {
                "ticker": ticker,
                "sector": sector,
                "held": held,
                "sources": [source for source in _SOURCE_ORDER if source in sources[ticker]],
                "checks": [
                    _result("max_position_pct", weight, limits["max_position_pct"]),
                    _result("max_sector_pct", sector_weight, limits["max_sector_pct"]),
                    _result(
                        "max_daily_loss_pct",
                        daily_loss,
                        limits["max_daily_loss_pct"],
                    ),
                ],
            }
        )

    result: dict[str, Any] = {
        "date": checked_date,
        "portfolio_as_of": parsed_as_of,
        "limits": {name: _json_number(limits[name]) for name in _LIMIT_NAMES},
        "items": items,
    }
    _write(payload["output_path"], result)
    return result


def _read_object(path: Path, shown: str, missing_help: str) -> dict[str, Any]:
    if not path.exists():
        raise ToolExecutionError(f"{shown} is missing. {missing_help}")
    if path.is_dir():
        raise ToolExecutionError(f"{shown} is a directory, not a JSON file.")
    try:
        document = json.loads(
            path.read_text(encoding="utf-8"),
            parse_float=Decimal,
            parse_int=Decimal,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ToolExecutionError(f"{shown} is not readable JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise ToolExecutionError(f"{shown} must contain one JSON object.")
    return document


def _read_limits(path: Path) -> dict[str, Decimal]:
    document = _read_object(path, _LIMITS_PATH, "Create it from the pipeline template.")
    limits: dict[str, Decimal] = {}
    for name in _LIMIT_NAMES:
        limits[name] = _non_negative(document.get(name), f"{_LIMITS_PATH} {name!r}")
    return limits


def _read_watchlist(path: Path) -> dict[str, str]:
    document = _read_object(path, _WATCHLIST_PATH, "Create it from the pipeline template.")
    rows = document.get("watchlist")
    if not isinstance(rows, list):
        raise ToolExecutionError(f"{_WATCHLIST_PATH} needs a 'watchlist' array.")
    watchlist: dict[str, str] = {}
    for number, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise ToolExecutionError(f"{_WATCHLIST_PATH} entry {number} must be a JSON object.")
        ticker = _ticker(row.get("ticker"), f"{_WATCHLIST_PATH} entry {number}")
        if ticker in watchlist:
            raise ToolExecutionError(f"{_WATCHLIST_PATH} has duplicate ticker {ticker}.")
        sector = row.get("sector")
        if not isinstance(sector, str) or not sector.strip():
            raise ToolExecutionError(
                f"{_WATCHLIST_PATH} entry {number} needs a non-empty sector for {ticker}."
            )
        watchlist[ticker] = sector.strip()
    return watchlist


def _read_theses(path: Path, shown: str) -> set[str]:
    if not path.exists():
        raise ToolExecutionError(f"{shown} is missing. Run the thesis stage first.")
    if path.is_dir():
        raise ToolExecutionError(f"{shown} is a directory, not a JSONL file.")
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise ToolExecutionError(f"{shown} could not be read: {exc}") from exc
    tickers: set[str] = set()
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line, parse_float=Decimal, parse_int=Decimal)
        except json.JSONDecodeError as exc:
            raise ToolExecutionError(f"{shown} line {number} is not valid JSON: {exc}") from exc
        if not isinstance(row, dict):
            raise ToolExecutionError(f"{shown} line {number} must be one JSON object.")
        tickers.add(_ticker(row.get("ticker"), f"{shown} line {number}"))
    return tickers


def _read_positions(computed: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    rows = computed.get("positions")
    if not isinstance(rows, list):
        raise ToolExecutionError(f"{_COMPUTED_PATH} needs a 'positions' array.")
    positions: dict[str, dict[str, Any]] = {}
    for number, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise ToolExecutionError(
                f"{_COMPUTED_PATH} position {number} must be a JSON object."
            )
        ticker = _ticker(row.get("ticker"), f"{_COMPUTED_PATH} position {number}")
        if ticker in positions:
            raise ToolExecutionError(f"{_COMPUTED_PATH} has duplicate ticker {ticker}.")
        sector = row.get("sector")
        if not isinstance(sector, str) or not sector.strip():
            raise ToolExecutionError(
                f"{_COMPUTED_PATH} position {number} needs a non-empty sector for {ticker}."
            )
        positions[ticker] = {
            "sector": sector.strip(),
            "weight": _non_negative(
                row.get("weight_pct"),
                f"{_COMPUTED_PATH} position {ticker} 'weight_pct'",
            ),
        }
    return positions


def _read_sector_weights(computed: Mapping[str, Any]) -> dict[str, Decimal]:
    concentration = computed.get("concentration")
    if not isinstance(concentration, dict):
        raise ToolExecutionError(f"{_COMPUTED_PATH} needs a 'concentration' object.")
    rows = concentration.get("sector_weights")
    if not isinstance(rows, dict):
        raise ToolExecutionError(
            f"{_COMPUTED_PATH} concentration needs a 'sector_weights' object."
        )
    result: dict[str, Decimal] = {}
    for sector, value in rows.items():
        if not isinstance(sector, str) or not sector.strip():
            raise ToolExecutionError(f"{_COMPUTED_PATH} has an empty sector weight name.")
        result[sector] = _non_negative(
            value,
            f"{_COMPUTED_PATH} sector weight {sector!r}",
        )
    return result


def _result(rule: str, value: Decimal, threshold: Decimal) -> dict[str, Any]:
    return {
        "rule": rule,
        "status": "PASS" if value <= threshold else "FAIL",
        "value": _json_number(value),
        "threshold": _json_number(threshold),
        "headroom_pct": _json_number(threshold - value),
    }


def _ticker(value: object, label: str) -> str:
    ticker = value.strip().upper() if isinstance(value, str) else ""
    if _TICKER.fullmatch(ticker) is None:
        raise ToolExecutionError(f"{label} has an invalid ticker {ticker!r}.")
    return ticker


def _non_negative(value: object, label: str) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
        raise ToolExecutionError(f"{label} must be a non-negative number.")
    return value


def _optional_decimal(value: object, label: str) -> Decimal | None:
    if value is None:
        return None
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ToolExecutionError(f"{label} must be a finite number or null.")
    return value


def _parse_date(value: str, label: str) -> date:
    try:
        if _DATE.fullmatch(value) is None:
            raise ValueError
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ToolExecutionError(f"{label} must be a real date in YYYY-MM-DD form.") from exc


def _json_number(value: Decimal) -> int | float:
    rendered = f"{value.quantize(_PERCENT, rounding=ROUND_HALF_UP):.4f}"
    parsed = Decimal(rendered)
    return int(parsed) if parsed == parsed.to_integral() else float(rendered)


def _write(path: Path, result: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="",
        )
    except OSError as exc:
        raise ToolExecutionError(f"risk checks could not be written: {exc}") from exc
