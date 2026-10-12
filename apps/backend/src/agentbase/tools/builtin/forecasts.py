"""Immutable price forecasts, completed-session outcomes, and monthly Excel books.

The fallback is an explicitly labeled random-walk baseline: tomorrow's price is
conditional on today's close, with an assumption band estimated from historical
volatility. It is a benchmark, not a news-aware or calibrated recommendation.
Agent scenarios require a rationale and saved, dated evidence. Neither forecasts
nor actuals are overwritten on reruns.
"""

from __future__ import annotations

import asyncio
import csv
import json
import re
import threading
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import ROUND_HALF_UP, Decimal, DecimalException
from itertools import pairwise
from typing import TYPE_CHECKING, Any, Final
from zoneinfo import ZoneInfo

from agentbase.tools.base import Prepared, ToolArgumentError, ToolExecutionError
from agentbase.tools.builtin.forecast_xlsx import forecast_workbook
from agentbase.tools.catalogue import RiskLevel, lookup

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from agentbase.tools.sandbox import Sandbox

__all__ = ["FORECAST_HORIZONS", "TrackForecastsTool"]

FORECAST_HORIZONS: Final[tuple[int, ...]] = (1, 2, 3, 5, 21)
_LEDGER: Final[str] = "predictions/forecasts.json"
_SYMBOL: Final[re.Pattern[str]] = re.compile(r"^[A-Z0-9^=._-]{1,20}$")
_DATE_IN_NAME: Final[re.Pattern[str]] = re.compile(r"(\d{4}-\d{2}-\d{2})")
_LOCK: Final[threading.Lock] = threading.Lock()
_NY: Final[ZoneInfo] = ZoneInfo("America/New_York")
_MAX_FILE_BYTES: Final[int] = 5_000_000
# When a piece of evidence was published, and when the file holding it was
# collected; a row without the first is available from the second.
_OWN_STAMPS: Final[tuple[str, ...]] = ("published_at", "published", "filed", "date")
_COLLECTED_STAMPS: Final[tuple[str, ...]] = ("fetched_at", "as_of")
_MAX_RETURN_ROWS: Final[int] = 100


@dataclass(frozen=True, slots=True)
class _Session:
    date: date
    close: Decimal


class TrackForecastsTool:
    """Record five-horizon price scenarios and refresh every month's outcomes."""

    name = "track_forecasts"

    def __init__(self, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock or (lambda: datetime.now(UTC))

    @property
    def description(self) -> str:
        return self._declaration()[0]

    @property
    def risk(self) -> RiskLevel:
        return self._declaration()[1]

    def _declaration(self) -> tuple[str, RiskLevel]:
        declaration = lookup(self.name)
        if declaration is None:  # pragma: no cover: registry tests pin this
            raise RuntimeError(f"{self.name!r} has no catalogue entry")
        return declaration.description, declaration.risk

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "as_of": {
                    "type": "string",
                    "description": "Latest completed US session, YYYY-MM-DD; inferred from saved prices when omitted.",
                },
                "symbols": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "maxItems": 50,
                    "description": "US tickers to forecast; defaults to saved price summary.",
                },
                "refresh_only": {
                    "type": "boolean",
                    "description": "Only fill due actuals in all monthly workbooks; create no predictions.",
                },
                "forecasts": {
                    "type": "array",
                    "maxItems": 250,
                    "items": {
                        "type": "object",
                        "properties": {
                            "ticker": {"type": "string"},
                            "horizon_days": {
                                "type": "integer",
                                "enum": list(FORECAST_HORIZONS),
                            },
                            "predicted_close": {"type": "number", "exclusiveMinimum": 0},
                            "scenario_return_pct": {
                                "type": "number",
                                "description": "Alternative to predicted_close: an explicitly assumed return in percent, greater than -100. The tool computes the target from the immutable baseline close. Supply exactly one target input.",
                            },
                            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                            "rationale": {
                                "type": "string",
                                "description": "Explain the conditional scenario and assumptions; not a promised price.",
                            },
                            "evidence_ids": {
                                "type": "array",
                                "items": {"type": "string"},
                                "minItems": 1,
                                "maxItems": 20,
                            },
                        },
                        "required": ["ticker", "horizon_days", "rationale", "evidence_ids"],
                    },
                    "description": "Optional evidence-backed agent scenarios. Unspecified horizons receive a clearly labeled unchanged-close baseline with historical volatility bands. Existing predictions stay immutable.",
                },
            },
        }

    def prepare(self, arguments: dict[str, Any], sandbox: Sandbox) -> Prepared:
        try:
            as_of = (
                None
                if arguments.get("as_of") is None
                else _date(arguments["as_of"], "as_of").isoformat()
            )
            refresh = arguments.get("refresh_only", False)
            if not isinstance(refresh, bool):
                raise ValueError("refresh_only must be a boolean")
            symbols = arguments.get("symbols")
            if symbols is not None and (
                not isinstance(symbols, list) or not 1 <= len(symbols) <= 50
            ):
                raise ValueError("symbols must contain between one and 50 US tickers")
            checked_symbols = (
                None
                if symbols is None
                else list(dict.fromkeys(_symbol(value) for value in symbols))
            )
            forecasts = arguments.get("forecasts", [])
            if not isinstance(forecasts, list) or len(forecasts) > 250:
                raise ValueError("forecasts must be an array of at most 250 scenarios")
            if refresh and forecasts:
                raise ValueError("refresh_only cannot also submit forecasts")
            checked: list[dict[str, Any]] = []
            seen: set[tuple[str, int]] = set()
            for row in forecasts:
                parsed = _scenario(row)
                key = (parsed["ticker"], parsed["horizon_days"])
                if key in seen:
                    raise ValueError(f"duplicate scenario for {key[0]} horizon {key[1]}")
                seen.add(key)
                checked.append(parsed)
        except (ValueError, DecimalException) as exc:
            raise ToolArgumentError(f"{self.name}: {exc}") from exc
        return Prepared(
            tool_name=self.name,
            summary="refresh actual closes in all monthly forecast workbooks"
            if refresh
            else "record immutable five-horizon forecasts and update monthly Excel workbooks",
            payload={
                "as_of": as_of,
                "symbols": checked_symbols,
                "forecasts": checked,
                "refresh_only": refresh,
                "ledger": sandbox.resolve_write_path(_LEDGER),
                "summary": sandbox.resolve_path("raw/prices/summary.csv"),
                "raw": sandbox.resolve_path("raw"),
                "prices": sandbox.resolve_path("raw/prices"),
                # Resolve the write directory before approval; individual months
                # come from validated dates in the ledger at execution time.
                "workbook_dir": sandbox.resolve_write_path("predictions/2000-01.xlsx").parent,
            },
            raw_arguments=dict(arguments),
        )

    async def execute(self, prepared: Prepared, sandbox: Sandbox) -> str:
        try:
            result = await asyncio.to_thread(_track, prepared.payload, sandbox, self._clock())
        except (OSError, UnicodeError, DecimalException, csv.Error) as exc:
            raise ToolExecutionError(f"Forecast tracking failed: {exc}") from exc
        return json.dumps(result, ensure_ascii=False, separators=(",", ":"))


def _track(payload: dict[str, Any], sandbox: Sandbox, now: datetime) -> dict[str, Any]:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ToolExecutionError("track_forecasts' clock must include a UTC offset.")
    with _LOCK:
        return _track_locked(payload, sandbox, now)


def _track_locked(payload: dict[str, Any], sandbox: Sandbox, now: datetime) -> dict[str, Any]:
    records = _read_ledger(payload["ledger"])
    original = (
        json.dumps({"version": 1, "forecasts": records}, indent=2, ensure_ascii=False) + "\n"
    )
    existing = {row["forecast_id"] for row in records}
    submitted = {(row["ticker"], row["horizon_days"]): row for row in payload["forecasts"]}
    symbols = payload["symbols"]
    if symbols is None:
        symbols = [] if payload["refresh_only"] else _summary_symbols(payload["summary"])
    symbols = sorted(set(symbols) | {ticker for ticker, _ in submitted})
    if len(symbols) > 50:
        raise ToolExecutionError("At most 50 US tickers can receive new forecasts per call.")
    needed = sorted(
        set(symbols) | {row["ticker"] for row in records if row["status"] == "pending"}
    )
    histories: dict[str, tuple[_Session, ...]] = {}
    problems: dict[str, str] = {}
    for symbol in needed:
        try:
            histories[symbol] = _read_prices(
                sandbox.resolve_path(f"raw/prices/{symbol}.csv"), now
            )
        except ToolExecutionError as exc:
            problems[symbol] = str(exc)
    as_of = payload["as_of"] or max(
        (
            history[-1].date.isoformat()
            for symbol, history in histories.items()
            if payload["refresh_only"] or symbol in symbols
        ),
        default=None,
    )
    issued = now.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    appended = 0
    preserved = 0
    skipped = [{"ticker": symbol, "reason": reason} for symbol, reason in problems.items()]
    if not payload["refresh_only"]:
        if as_of is None:
            raise ToolExecutionError(
                "No complete saved price sessions are available; run read_prices first."
            )
        evidence = _evidence_index(payload["raw"], sandbox, now) if submitted else {}
        for symbol in symbols:
            history = histories.get(symbol)
            if history is None:
                if any(ticker == symbol for ticker, _ in submitted):
                    raise ToolExecutionError(
                        f"Cannot record a scenario for {symbol}: {problems[symbol]}"
                    )
                continue
            if history[-1].date.isoformat() != as_of:
                reason = f"latest complete session {history[-1].date} differs from {as_of}; historical forecasts cannot be backfilled"
                if any(ticker == symbol for ticker, _ in submitted):
                    raise ToolExecutionError(f"{symbol}: {reason}")
                skipped.append({"ticker": symbol, "reason": reason})
                continue
            if (now.astimezone(_NY).date() - history[-1].date).days > 7:
                if any(ticker == symbol for ticker, _ in submitted):
                    raise ToolExecutionError(
                        f"{symbol}'s latest saved close is more than seven days old; "
                        "refresh prices before submitting a scenario."
                    )
                skipped.append(
                    {
                        "ticker": symbol,
                        "reason": "latest saved close is more than seven calendar days old; refresh prices before forecasting",
                    }
                )
                continue
            for horizon in FORECAST_HORIZONS:
                forecast_id = f"{as_of}-{symbol}-{horizon}"
                if forecast_id in existing:
                    preserved += 1
                    continue
                scenario = submitted.get((symbol, horizon))
                if scenario is not None:
                    _check_evidence(scenario["evidence_ids"], evidence, symbol, as_of, now)
                record = _new_record(symbol, horizon, history, scenario, issued)
                records.append(record)
                existing.add(forecast_id)
                appended += 1
    # Validate every new scenario before modifying the ledger or an Excel file.
    newly_resolved = 0
    unresolved: list[dict[str, str]] = []
    for record in records:
        if record["status"] == "resolved":
            continue
        history = histories.get(record["ticker"])
        if history is None:
            continue
        baseline_index = next(
            (
                index
                for index, session in enumerate(history)
                if session.date.isoformat() == record["as_of"]
            ),
            None,
        )
        if baseline_index is None:
            unresolved.append(
                {
                    "forecast_id": record["forecast_id"],
                    "reason": "baseline session is absent from saved history; refresh complete history to count sessions safely",
                }
            )
            continue
        actual_index = baseline_index + record["horizon_days"]
        if actual_index >= len(history):
            continue
        actual = history[actual_index]
        target = _number(record["predicted_close"], "predicted_close")
        baseline = _number(record["baseline_close"], "baseline_close")
        record.update(
            actual_date=actual.date.isoformat(),
            actual_close=_json_number(actual.close),
            error_pct=_json_number((target - actual.close) / actual.close * 100),
            actual_return_pct=_json_number((actual.close / baseline - 1) * 100),
            resolved_at=issued,
            status="resolved",
        )
        newly_resolved += 1
    records.sort(key=lambda row: (row["as_of"], row["ticker"], row["horizon_days"]))
    content = (
        json.dumps({"version": 1, "forecasts": records}, indent=2, ensure_ascii=False) + "\n"
    )
    books: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        books[record["as_of"][:7]].append(record)
    # Build every workbook before writing, so invalid inputs never partly save.
    exports = {month: forecast_workbook(rows) for month, rows in books.items()}
    written: list[str] = []
    ledger: Path = payload["ledger"]
    if content != original or not ledger.exists():
        _atomic_write(ledger, content.encode("utf-8"), sandbox)
        written.append(_LEDGER)
    for month, body in exports.items():
        path = sandbox.resolve_write_path(f"predictions/{month}.xlsx")
        if not path.exists() or path.read_bytes() != body:
            _atomic_write(path, body, sandbox)
            written.append(sandbox.relative(path))
    current = [record for record in records if record["as_of"] == as_of]
    return {
        "as_of": as_of,
        "appended": appended,
        "preserved": preserved,
        "newly_resolved": newly_resolved,
        "pending": sum(row["status"] == "pending" for row in records),
        "total_forecasts": len(records),
        "current_forecasts": len(current),
        "forecasts": current[:_MAX_RETURN_ROWS],
        "truncated": len(current) > _MAX_RETURN_ROWS,
        "skipped": skipped,
        "unresolved": unresolved[:_MAX_RETURN_ROWS],
        "ledger_path": _LEDGER,
        "workbooks": [f"predictions/{month}.xlsx" for month in sorted(books)],
        "horizon_basis": "1, 2, 3, 5 and 21 complete trading sessions after the immutable baseline session; weekends and holidays add no sessions",
        "baseline_note": "Unchanged-close random-walk benchmark; 80% bands use historical daily volatility and a normal-return assumption, not calibrated forecast confidence. Agent scenarios remain conditional and uncalibrated.",
        "written": written,
    }


def _new_record(
    symbol: str,
    horizon: int,
    history: tuple[_Session, ...],
    scenario: dict[str, Any] | None,
    issued: str,
) -> dict[str, Any]:
    baseline = history[-1]
    target = baseline.close
    low: int | float | None = None
    high: int | float | None = None
    if scenario is None:
        returns = [right.close / left.close - 1 for left, right in pairwise(history[-61:])]
        if len(returns) >= 2:
            mean = sum(returns, Decimal(0)) / len(returns)
            variance = sum(((value - mean) ** 2 for value in returns), Decimal(0)) / (
                len(returns) - 1
            )
            spread = Decimal("1.281552") * variance.sqrt() * Decimal(horizon).sqrt()
            low = _json_number(max(Decimal("0.000001"), baseline.close * (1 - spread)))
            high = _json_number(baseline.close * (1 + spread))
        rationale = "Random-walk benchmark conditional on an unchanged last completed close. No directional news or earnings claim. Assumption bands scale historical daily return volatility by the square root of trading sessions; they are not calibrated confidence."
        evidence_ids = [f"prices-{baseline.date.isoformat()}-{symbol}"]
    else:
        rationale = scenario["rationale"]
        evidence_ids = scenario["evidence_ids"]
        if scenario.get("scenario_return_pct") is not None:
            target = baseline.close * (
                1 + _number(scenario["scenario_return_pct"], "scenario_return_pct") / 100
            )
        else:
            target = _number(scenario["predicted_close"], "predicted_close")
        if not Decimal("0.000001") <= target <= Decimal("1000000000"):
            raise ToolExecutionError(
                f"Scenario for {symbol} implies an unsupported target price."
            )
    return {
        "forecast_id": f"{baseline.date.isoformat()}-{symbol}-{horizon}",
        "as_of": baseline.date.isoformat(),
        "ticker": symbol,
        "horizon_days": horizon,
        "baseline_close": _json_number(baseline.close),
        "predicted_close": _json_number(target),
        "assumption_return_pct": None
        if scenario is None
        else scenario.get("scenario_return_pct"),
        "method": "random_walk_baseline" if scenario is None else "agent_scenario",
        "confidence": None if scenario is None else scenario.get("confidence"),
        "rationale": rationale,
        "evidence_ids": evidence_ids,
        "created_at": issued,
        "evidence_cutoff_at": issued,
        "interval_low": low,
        "interval_high": high,
        "actual_date": None,
        "actual_close": None,
        "error_pct": None,
        "actual_return_pct": None,
        "status": "pending",
    }


def _scenario(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("each forecast must be an object")
    horizon = value.get("horizon_days")
    if (
        isinstance(horizon, bool)
        or not isinstance(horizon, int)
        or horizon not in FORECAST_HORIZONS
    ):
        raise ValueError("horizon_days must be 1, 2, 3, 5, or 21 trading sessions")
    has_price = value.get("predicted_close") is not None
    has_return = value.get("scenario_return_pct") is not None
    if has_price == has_return:
        raise ValueError("supply exactly one of predicted_close or scenario_return_pct")
    predicted: Decimal | None = None
    assumed_return: Decimal | None = None
    if has_price:
        predicted = _number(value["predicted_close"], "predicted_close")
        if not Decimal("0.000001") <= predicted <= Decimal("1000000000"):
            raise ValueError("predicted_close must be positive and no greater than one billion")
    else:
        assumed_return = _number(value["scenario_return_pct"], "scenario_return_pct")
        if not -100 < assumed_return <= 1000:
            raise ValueError("scenario_return_pct must be greater than -100 and at most 1000")
    confidence = value.get("confidence")
    if confidence is not None:
        confidence = _number(confidence, "confidence")
        if not 0 <= confidence <= 1:
            raise ValueError("confidence must be between zero and one")
        confidence = _json_number(confidence)
    rationale = value.get("rationale")
    if not isinstance(rationale, str) or not rationale.strip() or len(rationale) > 4000:
        raise ValueError("rationale must be non-empty text of at most 4000 characters")
    evidence = value.get("evidence_ids")
    if (
        not isinstance(evidence, list)
        or not 1 <= len(evidence) <= 20
        or any(
            not isinstance(entry, str) or not entry.strip() or len(entry) > 300
            for entry in evidence
        )
    ):
        raise ValueError("evidence_ids must contain one to 20 non-empty IDs")
    return {
        "ticker": _symbol(value.get("ticker")),
        "horizon_days": horizon,
        "predicted_close": None if predicted is None else _json_number(predicted),
        "scenario_return_pct": None if assumed_return is None else _json_number(assumed_return),
        "confidence": confidence,
        "rationale": rationale.strip(),
        "evidence_ids": list(dict.fromkeys(entry.strip() for entry in evidence)),
    }


def _read_prices(path: Path, now: datetime) -> tuple[_Session, ...]:
    if not path.is_file():
        raise ToolExecutionError(f"{path.name} is missing; run read_prices first.")
    if path.stat().st_size > _MAX_FILE_BYTES:
        raise ToolExecutionError(f"{path.name} exceeds the saved price size limit.")
    sessions: list[_Session] = []
    local = now.astimezone(_NY)
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if not {"date", "close"}.issubset(reader.fieldnames or ()):
                raise ValueError("date and close columns are required")
            prior: date | None = None
            for row in reader:
                session_date = _date(row.get("date"), "price date")
                close = _number(row.get("close"), "close")
                if not 0 < close <= Decimal("1000000000") or (
                    prior is not None and session_date <= prior
                ):
                    raise ValueError(
                        "prices must be positive and sessions unique and oldest first"
                    )
                prior = session_date
                if (
                    session_date.weekday() >= 5
                    or session_date > local.date()
                    or (session_date == local.date() and local.time() < time(16))
                ):
                    continue
                sessions.append(_Session(session_date, close))
    except (ValueError, OSError, UnicodeError, csv.Error) as exc:
        raise ToolExecutionError(f"{path.name} contains unusable prices: {exc}") from exc
    if not sessions:
        raise ToolExecutionError(f"{path.name} contains no completed US sessions.")
    return tuple(sessions)


def _summary_symbols(path: Path) -> list[str]:
    if not path.is_file():
        return []
    if path.stat().st_size > _MAX_FILE_BYTES:
        raise ToolExecutionError("Price summary exceeds the size limit.")
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        return sorted(
            {_symbol(row.get("ticker")) for row in rows if row.get("currency", "USD") == "USD"}
        )
    except ValueError as exc:
        raise ToolExecutionError(f"Price summary has invalid symbols: {exc}") from exc


def _read_ledger(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    if not path.is_file() or path.stat().st_size > 100_000_000:
        raise ToolExecutionError("Forecast ledger is not a bounded JSON file.")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        if (
            not isinstance(document, dict)
            or document.get("version") != 1
            or not isinstance(document.get("forecasts"), list)
        ):
            raise ValueError("expected version 1 and a forecasts array")
        records: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in document["forecasts"]:
            if not isinstance(row, dict):
                raise ValueError("forecast row must be an object")
            scenario = _scenario(row)
            as_of = _date(row.get("as_of"), "as_of").isoformat()
            key = f"{as_of}-{scenario['ticker']}-{scenario['horizon_days']}"
            if row.get("forecast_id") != key or key in seen:
                raise ValueError("forecast IDs must match unique date/ticker/horizon keys")
            if _number(row.get("baseline_close"), "baseline_close") <= 0:
                raise ValueError("baseline_close must be positive")
            if row.get("method") not in {"random_walk_baseline", "agent_scenario"}:
                raise ValueError("unsupported forecast method")
            _timestamp(row.get("created_at"), "created_at")
            _timestamp(row.get("evidence_cutoff_at"), "evidence_cutoff_at")
            if row.get("assumption_return_pct") is not None:
                assumed_return = _number(row["assumption_return_pct"], "assumption_return_pct")
                if not -100 < assumed_return <= 1000:
                    raise ValueError("assumption_return_pct is outside the supported range")
            if row.get("status") not in {"pending", "resolved"}:
                raise ValueError("status must be pending or resolved")
            if row["status"] == "resolved":
                if (
                    _date(row.get("actual_date"), "actual_date").isoformat() <= as_of
                    or _number(row.get("actual_close"), "actual_close") <= 0
                ):
                    raise ValueError(
                        "resolved forecast needs a later session and positive actual close"
                    )
                _number(row.get("error_pct"), "error_pct")
                _number(row.get("actual_return_pct"), "actual_return_pct")
            elif row.get("actual_date") is not None or row.get("actual_close") is not None:
                raise ValueError("pending forecast must have empty actual fields")
            for field in ("interval_low", "interval_high"):
                if row.get(field) is not None and _number(row[field], field) <= 0:
                    raise ValueError("forecast interval prices must be positive")
            seen.add(key)
            records.append(row)
        return records
    except (ValueError, KeyError, json.JSONDecodeError) as exc:
        raise ToolExecutionError(
            f"Forecast ledger is invalid; no files were changed: {exc}"
        ) from exc


def _evidence_index(raw: Path, sandbox: Sandbox, now: datetime) -> dict[str, datetime]:
    evidence: dict[str, datetime] = {}
    patterns = ("movers-*", "news-*", "filings-*", "calendar-*")
    paths = sorted(
        {
            path
            for pattern in patterns
            for path in raw.glob(pattern)
            if path.suffix in {".json", ".jsonl"}
        }
        | set(raw.glob("filings/*.json"))
        | set(raw.glob("filings/*.jsonl"))
        | set(raw.glob("market/screeners-*.json"))
    )
    for candidate in paths:
        path = sandbox.resolve_path(sandbox.relative(candidate))
        if not path.is_file() or path.stat().st_size > _MAX_FILE_BYTES:
            continue
        try:
            content = path.read_text(encoding="utf-8")
            documents = (
                [json.loads(line) for line in content.splitlines() if line.strip()]
                if path.suffix == ".jsonl"
                else [json.loads(content)]
            )
            match = _DATE_IN_NAME.search(path.name)
            fallback = None if match is None else match.group(1)
            for document in documents:
                for row, stamp in _evidence_rows(document, fallback):
                    identifier = row.get("id")
                    if not isinstance(identifier, str) or not identifier:
                        continue
                    if isinstance(stamp, str):
                        if len(stamp) == 10:
                            observed = datetime.combine(
                                _date(stamp, "evidence date"), time(0), tzinfo=_NY
                            )
                        else:
                            observed = _timestamp(stamp, "evidence timestamp")
                        if observed <= now:
                            evidence[identifier] = observed
        except (ValueError, UnicodeError, OSError, json.JSONDecodeError):
            # Invalid evidence is unavailable rather than silently accepted.
            continue
    return evidence


def _evidence_rows(
    value: object, collected: str | None
) -> list[tuple[dict[str, Any], str | None]]:
    """Every object with when it became available: its own publication time,
    else when the document holding it was fetched. A report's facts carry no
    publication time of their own, yet were saved before a forecast cites them."""
    if isinstance(value, list):
        return [pair for entry in value for pair in _evidence_rows(entry, collected)]
    if not isinstance(value, dict):
        return []
    collected = _first_text(value, _COLLECTED_STAMPS) or collected
    own = _first_text(value, _OWN_STAMPS) or collected
    return [
        (value, own),
        *[
            pair
            for entry in value.values()
            if isinstance(entry, (list, dict))
            for pair in _evidence_rows(entry, collected)
        ],
    ]


def _first_text(row: dict[str, Any], names: tuple[str, ...]) -> str | None:
    return next(
        (row[name] for name in names if isinstance(row.get(name), str) and row[name]), None
    )


def _check_evidence(
    ids: list[str], available: dict[str, datetime], symbol: str, as_of: str, now: datetime
) -> None:
    for identifier in ids:
        if identifier == f"prices-{as_of}-{symbol}":
            continue
        observed = available.get(identifier)
        if observed is None or observed > now:
            raise ToolExecutionError(
                f"Evidence {identifier!r} is unavailable, undated, or later than forecast issuance; save dated news, movers, or filings first."
            )


def _atomic_write(path: Path, body: bytes, sandbox: Sandbox) -> None:
    checked = sandbox.resolve_write_path(sandbox.relative(path))
    temporary = sandbox.resolve_write_path(
        sandbox.relative(checked.with_name(checked.name + ".tmp"))
    )
    checked.parent.mkdir(parents=True, exist_ok=True)
    try:
        temporary.write_bytes(body)
        temporary.replace(checked)
    finally:
        temporary.unlink(missing_ok=True)


def _date(value: object, label: str) -> date:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be YYYY-MM-DD")
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise ValueError(f"{label} must be YYYY-MM-DD")
    return parsed


def _timestamp(value: object, label: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be an ISO timestamp with UTC offset")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must include a UTC offset")
    return parsed


def _symbol(value: object) -> str:
    if not isinstance(value, str) or _SYMBOL.fullmatch(value.strip().upper()) is None:
        raise ValueError("ticker must be a valid symbol of at most 20 characters")
    return value.strip().upper()


def _number(value: object, label: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise ValueError(f"{label} must be a finite number")
    try:
        parsed = Decimal(str(value))
    except DecimalException as exc:
        raise ValueError(f"{label} must be a finite number") from exc
    if not parsed.is_finite():
        raise ValueError(f"{label} must be a finite number")
    return parsed


def _json_number(value: Decimal) -> int | float:
    rounded = value.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
    return int(rounded) if rounded == rounded.to_integral() else float(rounded)
