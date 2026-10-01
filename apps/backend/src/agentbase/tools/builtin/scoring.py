"""Deterministic scoring for the Phase 17 prediction ledger."""

from __future__ import annotations

import asyncio
import csv
import json
import re
import threading
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal, DecimalException
from io import StringIO
from typing import TYPE_CHECKING, Any, Final
from uuid import UUID

from agentbase.tools.base import Prepared, ToolArgumentError, ToolExecutionError
from agentbase.tools.catalogue import RiskLevel, lookup

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable
    from pathlib import Path

    from agentbase.tools.sandbox import Sandbox

__all__ = ["ScorePredictionsTool"]

_LEDGER_PATH: Final[str] = "scores/predictions.jsonl"
_ACCURACY_PATH: Final[str] = "scores/accuracy.csv"
_CALIBRATION_PATH: Final[str] = "scores/calibration.csv"
_MONTH: Final[re.Pattern[str]] = re.compile(r"^\d{4}-(?:0[1-9]|1[0-2])$")
_THESIS_FILE: Final[re.Pattern[str]] = re.compile(r"^(bull|bear)-(\d{4}-\d{2}-\d{2})\.jsonl$")
_TICKER: Final[re.Pattern[str]] = re.compile(r"^[A-Z0-9^=._-]{1,20}$")
_HORIZONS: Final[frozenset[int]] = frozenset({1, 3, 5, 7})
_BANDS: Final[frozenset[str]] = frozenset({"0-1%", "1-3%", "3-5%", "5%+"})
_AGENTS: Final[tuple[str, ...]] = ("bull", "bear")
_FOUR_PLACES: Final[Decimal] = Decimal("0.0001")
_TWO_PLACES: Final[Decimal] = Decimal("0.01")
_HALF: Final[Decimal] = Decimal("0.50")
_TENTH: Final[Decimal] = Decimal("0.10")
_SCORE_LOCK: Final[threading.Lock] = threading.Lock()


@dataclass(frozen=True, slots=True)
class _Thesis:
    fields: dict[str, Any]
    pred_id: str
    as_of: datetime
    month: str
    agent: str
    ticker: str
    horizon: int
    direction: str
    band: str
    confidence: Decimal


@dataclass(frozen=True, slots=True)
class _Session:
    date: date
    close: Decimal


@dataclass(frozen=True, slots=True)
class _Resolved:
    record: dict[str, Any]
    pred_id: str
    month: str
    agent: str
    horizon: int
    confidence: Decimal
    brier: Decimal
    hit: bool
    rose: bool


@dataclass(frozen=True, slots=True)
class _Problem:
    path: str
    line: int
    error: str
    month: str

    def public(self) -> dict[str, Any]:
        return {"path": self.path, "line": self.line, "error": self.error}


@dataclass(frozen=True, slots=True)
class _Unresolved:
    pred_id: str
    ticker: str
    month: str
    reason: str

    def public(self) -> dict[str, str]:
        return {
            "pred_id": self.pred_id,
            "ticker": self.ticker,
            "reason": self.reason,
        }


def _declaration(name: str) -> tuple[str, RiskLevel]:
    declaration = lookup(name)
    if declaration is None:  # pragma: no cover: registry test pins this
        msg = f"{name!r} has an implementation but no catalogue entry"
        raise RuntimeError(msg)
    return declaration.description, declaration.risk


class ScorePredictionsTool:
    """Resolve prediction outcomes and rebuild deterministic score summaries."""

    name = "score_predictions"

    def __init__(self, now: Callable[[], datetime] | None = None) -> None:
        self._now = now or (lambda: datetime.now(UTC))

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
                "month": {
                    "type": "string",
                    "pattern": r"^\d{4}-(0[1-9]|1[0-2])$",
                    "description": "Scorecard month in YYYY-MM form.",
                }
            },
            "required": ["month"],
        }

    def prepare(self, arguments: dict[str, Any], sandbox: Sandbox) -> Prepared:
        raw_month = arguments.get("month")
        if not isinstance(raw_month, str) or _MONTH.fullmatch(raw_month) is None:
            raise ToolArgumentError(f"{self.name} requires a real 'month' in YYYY-MM form.")
        try:
            date.fromisoformat(f"{raw_month}-01")
        except ValueError as exc:
            raise ToolArgumentError(
                f"{self.name} requires a real 'month' in YYYY-MM form."
            ) from exc
        month = raw_month
        return Prepared(
            tool_name=self.name,
            summary=f"score resolved predictions and write the {month} scorecard",
            payload={
                "month": month,
                "root": sandbox.root,
                "theses_dir": sandbox.resolve_path("theses"),
                "prices_dir": sandbox.resolve_path("raw/prices"),
                "ledger_path": sandbox.resolve_write_path(_LEDGER_PATH),
                "accuracy_path": sandbox.resolve_write_path(_ACCURACY_PATH),
                "calibration_path": sandbox.resolve_write_path(_CALIBRATION_PATH),
                "scorecard_path": sandbox.resolve_write_path(f"scores/scorecard-{month}.json"),
            },
            raw_arguments=dict(arguments),
        )

    async def execute(self, prepared: Prepared, sandbox: Sandbox) -> str:
        del sandbox
        try:
            result = await asyncio.to_thread(
                _score_and_write,
                prepared.payload,
                self._now(),
            )
        except DecimalException as exc:
            raise ToolExecutionError(
                "prediction or price inputs contain a number outside the supported range."
            ) from exc
        return json.dumps(result, ensure_ascii=False, separators=(",", ":"))


def _score_and_write(payload: dict[str, Any], now: datetime) -> dict[str, Any]:
    with _SCORE_LOCK:
        return _score_and_write_locked(payload, now)


def _score_and_write_locked(payload: dict[str, Any], now: datetime) -> dict[str, Any]:
    ledger_path: Path = payload["ledger_path"]
    existing = _read_ledger(ledger_path)
    existing_ids = {row.pred_id for row in existing}
    theses, malformed = _read_theses(payload["theses_dir"], payload["root"])

    seen_input: set[str] = set()
    price_cache: dict[str, tuple[_Session, ...] | str] = {}
    newly_resolved: list[_Resolved] = []
    unresolved: list[_Unresolved] = []
    already_scored = 0
    scored_at = _utc_iso(now)

    for thesis, source, line in theses:
        if thesis.pred_id in seen_input:
            malformed.append(
                _Problem(
                    path=source,
                    line=line,
                    error=f"duplicate pred_id {thesis.pred_id}",
                    month=thesis.month,
                )
            )
            continue
        seen_input.add(thesis.pred_id)
        if thesis.pred_id in existing_ids:
            already_scored += 1
            continue

        cached = price_cache.get(thesis.ticker)
        if cached is None:
            try:
                price_path = _safe_child(
                    payload["prices_dir"] / f"{thesis.ticker}.csv",
                    payload["root"],
                    f"raw/prices/{thesis.ticker}.csv",
                )
                cached = _read_prices(price_path, thesis.ticker)
            except _PriceUnavailableError as exc:
                cached = str(exc)
            price_cache[thesis.ticker] = cached

        if isinstance(cached, str):
            unresolved.append(_Unresolved(thesis.pred_id, thesis.ticker, thesis.month, cached))
            continue
        outcome = _resolve(thesis, cached, scored_at)
        if isinstance(outcome, str):
            unresolved.append(_Unresolved(thesis.pred_id, thesis.ticker, thesis.month, outcome))
            continue
        newly_resolved.append(outcome)
        existing_ids.add(thesis.pred_id)

    if newly_resolved:
        _append_ledger(ledger_path, [row.record for row in newly_resolved])

    resolved = [*existing, *newly_resolved]
    all_accuracy = _accuracy(resolved)
    all_calibration = _calibration(resolved)
    _write_accuracy(payload["accuracy_path"], all_accuracy)
    _write_calibration(payload["calibration_path"], all_calibration)

    month: str = payload["month"]
    monthly_resolved = [row for row in resolved if row.month == month]
    monthly_unresolved = [row for row in unresolved if row.month == month]
    monthly_malformed = [row for row in malformed if row.month == month]
    scorecard = {
        "month": month,
        "resolved_predictions": len(monthly_resolved),
        "unresolved_predictions": len(monthly_unresolved),
        "malformed_thesis_lines": len(monthly_malformed),
        "baselines": {
            "constant_0_5_brier": _json_number(Decimal("0.25")),
            "windows_up_rate": _rate(
                sum(row.rose for row in monthly_resolved), len(monthly_resolved)
            ),
        },
        "accuracy": _accuracy(monthly_resolved),
        "calibration": _calibration(monthly_resolved),
    }
    _write_json(payload["scorecard_path"], scorecard, "scorecard")

    return {
        "month": month,
        "appended": len(newly_resolved),
        "already_scored": already_scored,
        "unresolved": len(monthly_unresolved),
        "unresolved_predictions": [row.public() for row in monthly_unresolved],
        "malformed": len(malformed),
        "malformed_lines": [row.public() for row in malformed],
        "ledger_path": _LEDGER_PATH,
        "scorecard_path": f"scores/scorecard-{month}.json",
        "accuracy_path": _ACCURACY_PATH,
        "calibration_path": _CALIBRATION_PATH,
    }


class _PriceUnavailableError(Exception):
    """A ticker has no usable saved history, so its predictions stay open."""


def _safe_child(path: Path, root: Path, shown: str) -> Path:
    try:
        resolved = path.resolve()
    except (OSError, RuntimeError) as exc:
        raise ToolExecutionError(f"{shown} is not a usable workspace path: {exc}") from exc
    if not resolved.is_relative_to(root):
        raise ToolExecutionError(f"{shown} resolves outside the workspace.")
    return resolved


def _read_theses(
    directory: Path,
    root: Path,
) -> tuple[list[tuple[_Thesis, str, int]], list[_Problem]]:
    if not directory.exists():
        return [], []
    if not directory.is_dir():
        raise ToolExecutionError("theses is not a directory.")

    theses: list[tuple[_Thesis, str, int]] = []
    malformed: list[_Problem] = []
    try:
        candidates = sorted(
            [*directory.glob("bull-*.jsonl"), *directory.glob("bear-*.jsonl")],
            key=lambda path: path.name,
        )
    except OSError as exc:
        raise ToolExecutionError(f"theses could not be listed: {exc}") from exc

    for candidate in candidates:
        match = _THESIS_FILE.fullmatch(candidate.name)
        if match is None:  # glob shape makes this defensive
            continue
        expected_agent, source_date = match.groups()
        source_month = source_date[:7]
        shown = f"theses/{candidate.name}"
        path = _safe_child(candidate, root, shown)
        if path.is_dir():
            raise ToolExecutionError(f"{shown} is a directory, not a JSONL file.")
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError) as exc:
            raise ToolExecutionError(f"{shown} could not be read: {exc}") from exc
        for number, line in enumerate(lines, start=1):
            if not line.strip():
                malformed.append(_Problem(shown, number, "line is blank", source_month))
                continue
            try:
                row = json.loads(line, parse_float=Decimal, parse_int=Decimal)
                if not isinstance(row, dict):
                    raise ValueError("line must contain one JSON object")
                thesis = _parse_thesis(row, expected_agent, f"{shown} line {number}")
            except (json.JSONDecodeError, ValueError) as exc:
                malformed.append(_Problem(shown, number, str(exc), source_month))
                continue
            theses.append((thesis, shown, number))
    return theses, malformed


def _parse_thesis(row: dict[str, Any], expected_agent: str, label: str) -> _Thesis:
    pred_id = _uuid(row.get("pred_id"), f"{label} pred_id")
    as_of_text = _text(row.get("as_of"), f"{label} as_of")
    as_of = _datetime(as_of_text, f"{label} as_of")
    agent = _text(row.get("agent"), f"{label} agent")
    if agent != expected_agent:
        raise ValueError(f"{label} agent must be {expected_agent!r}")
    ticker = _text(row.get("ticker"), f"{label} ticker").upper()
    if _TICKER.fullmatch(ticker) is None:
        raise ValueError(f"{label} ticker {ticker!r} is invalid")
    horizon = _integer(row.get("horizon_days"), f"{label} horizon_days")
    if horizon not in _HORIZONS:
        raise ValueError(f"{label} horizon_days must be 1, 3, 5, or 7")
    direction = _text(row.get("direction"), f"{label} direction")
    wanted_direction = "up" if agent == "bull" else "down"
    if direction != wanted_direction:
        raise ValueError(f"{label} direction must be {wanted_direction!r}")
    band = _text(row.get("magnitude_band"), f"{label} magnitude_band")
    if band not in _BANDS:
        raise ValueError(f"{label} magnitude_band is not supported")
    confidence = _number(row.get("confidence"), f"{label} confidence")
    if confidence < _HALF or confidence > Decimal("0.95"):
        raise ValueError(f"{label} confidence must be from 0.50 through 0.95")

    thesis_text = _text(row.get("thesis"), f"{label} thesis")
    if len(thesis_text.split()) > 80:
        raise ValueError(f"{label} thesis must be at most 80 words")
    evidence = row.get("evidence_ids")
    if not isinstance(evidence, list) or not evidence:
        raise ValueError(f"{label} evidence_ids must be a non-empty array")
    evidence_ids = [
        _text(value, f"{label} evidence_ids entry {index}")
        for index, value in enumerate(evidence, start=1)
    ]
    invalidation = _text(row.get("invalidation"), f"{label} invalidation")
    base_rate = _text(row.get("base_rate_note"), f"{label} base_rate_note")

    fields: dict[str, Any] = {
        "pred_id": pred_id,
        "as_of": as_of_text,
        "agent": agent,
        "ticker": ticker,
        "horizon_days": horizon,
        "direction": direction,
        "magnitude_band": band,
        "confidence": _json_number(confidence),
        "thesis": thesis_text,
        "evidence_ids": evidence_ids,
        "invalidation": invalidation,
        "base_rate_note": base_rate,
    }
    return _Thesis(
        fields=fields,
        pred_id=pred_id,
        as_of=as_of,
        month=as_of.astimezone(UTC).strftime("%Y-%m"),
        agent=agent,
        ticker=ticker,
        horizon=horizon,
        direction=direction,
        band=band,
        confidence=confidence,
    )


def _read_prices(path: Path, ticker: str) -> tuple[_Session, ...]:
    shown = f"raw/prices/{ticker}.csv"
    if not path.exists():
        raise _PriceUnavailableError(f"{shown} is missing; run read_prices first")
    if path.is_dir():
        raise ToolExecutionError(f"{shown} is a directory, not a CSV file.")
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            fields = set(reader.fieldnames or ())
            if not {"date", "close"}.issubset(fields):
                raise ToolExecutionError(f"{shown} needs date and close columns.")
            sessions: list[_Session] = []
            for number, row in enumerate(reader, start=2):
                parsed_date = _date(row.get("date"), f"{shown} row {number} date")
                close = _number(row.get("close"), f"{shown} row {number} close")
                if close <= 0:
                    raise ToolExecutionError(f"{shown} row {number} close must be positive.")
                if sessions and parsed_date <= sessions[-1].date:
                    raise ToolExecutionError(
                        f"{shown} dates must be unique and oldest first; row {number} is not."
                    )
                sessions.append(_Session(parsed_date, close))
    except ToolExecutionError:
        raise
    except (OSError, UnicodeError, csv.Error) as exc:
        raise ToolExecutionError(f"{shown} could not be read: {exc}") from exc
    if not sessions:
        raise _PriceUnavailableError(f"{shown} has no price sessions")
    return tuple(sessions)


def _resolve(
    thesis: _Thesis,
    sessions: tuple[_Session, ...],
    scored_at: str,
) -> _Resolved | str:
    prediction_date = thesis.as_of.astimezone(UTC).date()
    entry_index: int | None = None
    for index, session in enumerate(sessions):
        if session.date <= prediction_date:
            entry_index = index
        else:
            break
    if entry_index is None:
        return f"no saved session on or before {prediction_date.isoformat()}"
    exit_index = entry_index + thesis.horizon
    if exit_index >= len(sessions):
        available = len(sessions) - entry_index - 1
        return (
            f"needs {thesis.horizon} later sessions after "
            f"{sessions[entry_index].date.isoformat()}; only {available} available"
        )

    entry = sessions[entry_index]
    exit_session = sessions[exit_index]
    return_pct = ((exit_session.close - entry.close) / entry.close) * 100
    rose = return_pct > 0
    hit = return_pct > 0 if thesis.direction == "up" else return_pct < 0
    band_hit = hit and _in_band(abs(return_pct), thesis.band)
    outcome = Decimal(1) if hit else Decimal(0)
    brier = (thesis.confidence - outcome) ** 2
    record = {
        **thesis.fields,
        "entry_date": entry.date.isoformat(),
        "entry_close": _json_number(entry.close),
        "exit_date": exit_session.date.isoformat(),
        "exit_close": _json_number(exit_session.close),
        "return_pct": _json_number(return_pct),
        "hit": hit,
        "band_hit": band_hit,
        "brier": _json_number(brier),
        "scored_at": scored_at,
    }
    return _Resolved(
        record=record,
        pred_id=thesis.pred_id,
        month=thesis.month,
        agent=thesis.agent,
        horizon=thesis.horizon,
        confidence=thesis.confidence,
        brier=brier,
        hit=hit,
        rose=rose,
    )


def _in_band(magnitude: Decimal, band: str) -> bool:
    if band == "0-1%":
        return magnitude < 1
    if band == "1-3%":
        return Decimal(1) <= magnitude < 3
    if band == "3-5%":
        return Decimal(3) <= magnitude < 5
    return magnitude >= 5


def _read_ledger(path: Path) -> list[_Resolved]:
    if not path.exists():
        return []
    if path.is_dir():
        raise ToolExecutionError(f"{_LEDGER_PATH} is a directory, not a JSONL file.")
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise ToolExecutionError(f"{_LEDGER_PATH} could not be read: {exc}") from exc
    rows: list[_Resolved] = []
    seen: set[str] = set()
    for number, line in enumerate(lines, start=1):
        label = f"{_LEDGER_PATH} line {number}"
        try:
            row = json.loads(line, parse_float=Decimal, parse_int=Decimal)
            if not isinstance(row, dict):
                raise ValueError("must contain one JSON object")
            agent = row.get("agent")
            if agent not in _AGENTS:
                raise ValueError("agent must be 'bull' or 'bear'")
            thesis = _parse_thesis(row, agent, label)
            if thesis.pred_id in seen:
                raise ValueError(f"duplicates pred_id {thesis.pred_id}")
            hit = row.get("hit")
            band_hit = row.get("band_hit")
            if not isinstance(hit, bool) or not isinstance(band_hit, bool):
                raise ValueError("hit and band_hit must be booleans")
            return_pct = _number(row.get("return_pct"), f"{label} return_pct")
            brier = _number(row.get("brier"), f"{label} brier")
            if brier < 0:
                raise ValueError(f"{label} brier must be non-negative")
            _date(row.get("entry_date"), f"{label} entry_date")
            _date(row.get("exit_date"), f"{label} exit_date")
            if _number(row.get("entry_close"), f"{label} entry_close") <= 0:
                raise ValueError(f"{label} entry_close must be positive")
            if _number(row.get("exit_close"), f"{label} exit_close") <= 0:
                raise ValueError(f"{label} exit_close must be positive")
            _datetime(row.get("scored_at"), f"{label} scored_at")
        except (json.JSONDecodeError, ValueError) as exc:
            raise ToolExecutionError(f"{label} is invalid: {exc}") from exc
        seen.add(thesis.pred_id)
        rows.append(
            _Resolved(
                record=row,
                pred_id=thesis.pred_id,
                month=thesis.month,
                agent=thesis.agent,
                horizon=thesis.horizon,
                confidence=thesis.confidence,
                brier=brier,
                hit=hit,
                rose=return_pct > 0,
            )
        )
    return rows


def _accuracy(rows: Iterable[_Resolved]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, int], list[_Resolved]] = defaultdict(list)
    for row in rows:
        groups[(row.agent, row.horizon)].append(row)
    result: list[dict[str, Any]] = []
    for agent in _AGENTS:
        for horizon in sorted(h for name, h in groups if name == agent):
            group = groups[(agent, horizon)]
            count = len(group)
            hits = sum(row.hit for row in group)
            result.append(
                {
                    "agent": agent,
                    "horizon_days": horizon,
                    "predictions": count,
                    "hits": hits,
                    "hit_rate": _rate(hits, count),
                    "mean_brier": _json_number(
                        sum((row.brier for row in group), start=Decimal(0)) / count
                    ),
                    "constant_0_5_brier": _json_number(Decimal("0.25")),
                    "windows_up_rate": _rate(sum(row.rose for row in group), count),
                }
            )
    return result


def _calibration(rows: Iterable[_Resolved]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, Decimal], list[_Resolved]] = defaultdict(list)
    for row in rows:
        groups[(row.agent, _bucket(row.confidence))].append(row)
    result: list[dict[str, Any]] = []
    for agent in _AGENTS:
        buckets = sorted(bucket for name, bucket in groups if name == agent)
        for bucket in buckets:
            group = groups[(agent, bucket)]
            count = len(group)
            hits = sum(row.hit for row in group)
            mean_confidence = sum((row.confidence for row in group), start=Decimal(0)) / count
            observed = Decimal(hits) / count
            result.append(
                {
                    "agent": agent,
                    "confidence_bucket": _json_number(bucket, _TWO_PLACES),
                    "predictions": count,
                    "hits": hits,
                    "mean_confidence": _json_number(mean_confidence),
                    "observed_hit_rate": _json_number(observed),
                    "confidence_minus_observed": _json_number(mean_confidence - observed),
                }
            )
    return result


def _bucket(confidence: Decimal) -> Decimal:
    steps = int((confidence - _HALF) // _TENTH)
    return _HALF + (Decimal(steps) * _TENTH)


def _rate(numerator: int, denominator: int) -> int | float | None:
    if denominator == 0:
        return None
    return _json_number(Decimal(numerator) / denominator)


def _append_ledger(path: Path, rows: list[dict[str, Any]]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        needs_newline = (
            path.exists() and path.stat().st_size > 0 and not path.read_bytes().endswith(b"\n")
        )
        with path.open("a", encoding="utf-8", newline="") as handle:
            if needs_newline:
                handle.write("\n")
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
                handle.write("\n")
    except OSError as exc:
        raise ToolExecutionError(f"{_LEDGER_PATH} could not be appended: {exc}") from exc


def _write_accuracy(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = (
        "agent",
        "horizon_days",
        "predictions",
        "hits",
        "hit_rate",
        "mean_brier",
        "constant_0_5_brier",
        "windows_up_rate",
    )
    _write_csv(path, fields, rows, _ACCURACY_PATH)


def _write_calibration(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = (
        "agent",
        "confidence_bucket",
        "predictions",
        "hits",
        "mean_confidence",
        "observed_hit_rate",
        "confidence_minus_observed",
    )
    _write_csv(path, fields, rows, _CALIBRATION_PATH)


def _write_csv(
    path: Path,
    fields: tuple[str, ...],
    rows: list[dict[str, Any]],
    shown: str,
) -> None:
    buffer = StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        rendered = dict(row)
        for key, value in row.items():
            if key in {
                "hit_rate",
                "mean_brier",
                "constant_0_5_brier",
                "windows_up_rate",
                "mean_confidence",
                "observed_hit_rate",
                "confidence_minus_observed",
            }:
                rendered[key] = "" if value is None else f"{Decimal(str(value)):.4f}"
            elif key == "confidence_bucket":
                rendered[key] = f"{Decimal(str(value)):.2f}"
        writer.writerow(rendered)
    _write_text(path, buffer.getvalue(), shown)


def _write_json(path: Path, document: dict[str, Any], shown: str) -> None:
    _write_text(
        path,
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        shown,
    )


def _write_text(path: Path, content: str, shown: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="")
    except OSError as exc:
        raise ToolExecutionError(f"{shown} could not be written: {exc}") from exc


def _uuid(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a UUID string")
    try:
        return str(UUID(value))
    except ValueError as exc:
        raise ValueError(f"{label} must be a UUID string") from exc


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


def _integer(value: object, label: str) -> int:
    if not isinstance(value, Decimal) or not value.is_finite() or value != value.to_integral():
        raise ValueError(f"{label} must be an integer")
    return int(value)


def _number(value: object, label: str) -> Decimal:
    if isinstance(value, str):
        try:
            parsed = Decimal(value)
        except DecimalException as exc:
            raise ValueError(f"{label} must be a finite number") from exc
    elif isinstance(value, Decimal):
        parsed = value
    else:
        raise ValueError(f"{label} must be a finite number")
    if not parsed.is_finite():
        raise ValueError(f"{label} must be a finite number")
    return parsed


def _datetime(value: object, label: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be an ISO8601 timestamp with an offset")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} must be an ISO8601 timestamp with an offset") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must include a UTC offset")
    return parsed


def _date(value: object, label: str) -> date:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a real date in YYYY-MM-DD form")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{label} must be a real date in YYYY-MM-DD form") from exc
    if parsed.isoformat() != value:
        raise ValueError(f"{label} must be a real date in YYYY-MM-DD form")
    return parsed


def _utc_iso(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ToolExecutionError("score_predictions' clock must include a UTC offset.")
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _json_number(
    value: Decimal,
    places: Decimal = _FOUR_PLACES,
) -> int | float:
    rendered = f"{value.quantize(places, rounding=ROUND_HALF_UP):f}"
    parsed = Decimal(rendered)
    return int(parsed) if parsed == parsed.to_integral() else float(rendered)
