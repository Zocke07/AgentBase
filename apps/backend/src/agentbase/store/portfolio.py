"""User-owned portfolio forms over the canonical CSV and JSON run inputs."""

from __future__ import annotations

import contextlib
import csv
import hashlib
import json
import re
import shutil
import threading
import uuid
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from io import StringIO
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agentbase.tools.builtin.portfolio import is_supported_currency
from agentbase.tools.sandbox import Sandbox

_PATHS = ("portfolio/positions.csv", "config/watchlist.json", "config/limits.json")
_COLUMNS = ("ticker", "shares", "cost_per_share", "opened", "sector", "currency")
_LOCK = threading.RLock()


class PortfolioInputError(ValueError):
    """An existing input cannot be safely represented by the form."""


class PortfolioConflictError(ValueError):
    """The form's original files have changed."""


def _number(value: str, *, positive: bool = False, percent: bool = False) -> str:
    if len(value) > 40 or re.fullmatch(r"(?:\d+(?:\.\d*)?|\.\d+)", value) is None:
        raise ValueError(
            "Use a number with a decimal point, without commas or currency symbols."
        )
    number = Decimal(value)
    if positive and number <= 0:
        raise ValueError("Enter a number greater than zero.")
    if percent and number > 100:
        raise ValueError("Enter a percentage from 0 to 100.")
    return format(number, "f")


class PortfolioStock(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    ticker: str = Field(min_length=1, max_length=20)
    sector: str = Field(min_length=1, max_length=100)
    company_name: str = Field(default="", max_length=160)
    industry: str = Field(default="", max_length=160)
    exchange: str = Field(default="US", max_length=80)

    @field_validator("ticker")
    @classmethod
    def ticker_valid(cls, value: str) -> str:
        value = value.upper()
        if value == "CASH" or re.fullmatch(r"[A-Z0-9^=._-]{1,20}", value) is None:
            raise ValueError("Enter a stock ticker such as MU or AAPL. Enter cash separately.")
        return value


class PortfolioHolding(PortfolioStock):
    shares: str
    cost_per_share: str | None = None
    opened: str | None = None

    @field_validator("shares")
    @classmethod
    def shares_valid(cls, value: str) -> str:
        return _number(value, positive=True)

    @field_validator("cost_per_share")
    @classmethod
    def cost_valid(cls, value: str | None) -> str | None:
        return _number(value, positive=True) if value else None

    @field_validator("opened")
    @classmethod
    def date_valid(cls, value: str | None) -> str | None:
        if not value:
            return None
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is None:
            raise ValueError("Enter the purchase date as YYYY-MM-DD, or leave it blank.")
        date.fromisoformat(value)
        return value


class PortfolioLimits(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    max_position_pct: str
    max_sector_pct: str
    max_daily_loss_pct: str

    @field_validator("max_position_pct", "max_sector_pct", "max_daily_loss_pct")
    @classmethod
    def percent_valid(cls, value: str) -> str:
        return _number(value, percent=True)


class PersonalPortfolio(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    currency: str
    cash: str
    holdings: list[PortfolioHolding] = Field(max_length=50)
    watchlist: list[PortfolioStock] = Field(max_length=50)
    limits: PortfolioLimits

    @field_validator("currency")
    @classmethod
    def currency_valid(cls, value: str) -> str:
        value = value.upper()
        if not is_supported_currency(value):
            raise ValueError("Enter a supported currency code such as USD, TWD or HKD.")
        return value

    @field_validator("cash")
    @classmethod
    def cash_valid(cls, value: str) -> str:
        return _number(value)

    @model_validator(mode="after")
    def unique_stocks(self) -> PersonalPortfolio:
        symbols = [row.ticker for row in [*self.holdings, *self.watchlist]]
        if len(set(symbols)) != len(symbols):
            raise ValueError("List each stock once. Stocks you own are already watched.")
        if len(symbols) > 50:
            raise ValueError("Keep at most 50 owned and additional watched stocks in total.")
        return self


class PortfolioResponse(BaseModel):
    portfolio: PersonalPortfolio
    revision: str


class SavePortfolioRequest(PortfolioResponse):
    model_config = ConfigDict(extra="forbid")


def _paths(root: Path) -> list[Path]:
    if root.is_symlink():
        raise PortfolioInputError(
            "The space folder is a symlink; portfolio data was not changed."
        )
    sandbox = Sandbox(root)
    paths = []
    for name in _PATHS:
        path = root / name
        for part in (path.parent, path):
            if part.is_symlink():
                raise PortfolioInputError(
                    f"{name} is reached through a symlink; data was not changed."
                )
        paths.append(sandbox.resolve_path(name))
    return paths


def _read(paths: list[Path]) -> list[bytes | None]:
    return [path.read_bytes() if path.exists() else None for path in paths]


def _revision(contents: Sequence[bytes | None]) -> str:
    digest = hashlib.sha256()
    for name, content in zip(_PATHS, contents, strict=True):
        digest.update(name.encode())
        digest.update(
            b"missing" if content is None else str(len(content)).encode() + b":" + content
        )
    return digest.hexdigest()


def _object(content: bytes | None, name: str) -> dict[str, Any]:
    if content is None:
        return {}

    def reject_constant(value: str) -> None:
        raise PortfolioInputError(f"{name} contains a non-finite number: {value}.")

    result = json.loads(
        content, parse_float=Decimal, parse_int=Decimal, parse_constant=reject_constant
    )
    if not isinstance(result, dict):
        raise PortfolioInputError(f"{name} must contain a JSON object.")
    return result


def _json_text(value: Any) -> str:
    """Write JSON numbers without rounding them or turning them into strings."""
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise PortfolioInputError("Portfolio settings contain a non-finite number.")
        return format(value, "f")
    if isinstance(value, dict):
        items = [
            f"{json.dumps(key, ensure_ascii=False)}: {_json_text(item)}"
            for key, item in value.items()
        ]
        return (
            "{\n" + ",\n".join("  " + item.replace("\n", "\n  ") for item in items) + "\n}"
            if items
            else "{}"
        )
    if isinstance(value, list):
        return (
            "[\n"
            + ",\n".join("  " + _json_text(item).replace("\n", "\n  ") for item in value)
            + "\n]"
            if value
            else "[]"
        )
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def _decode(
    contents: list[bytes | None],
) -> tuple[PersonalPortfolio, dict[str, Any], dict[str, Any], list[dict[str, str]], list[str]]:
    watch = _object(contents[1], _PATHS[1])
    limits = _object(contents[2], _PATHS[2])
    raw_watch = watch.get("watchlist", [])
    if not isinstance(raw_watch, list) or any(not isinstance(row, dict) for row in raw_watch):
        raise PortfolioInputError(
            "config/watchlist.json needs a watchlist array of stock objects."
        )
    # Keep source metadata separately: aliases and unknown fields survive saves.
    metadata: dict[str, dict[str, Any]] = {}
    for row in raw_watch:
        stock = PortfolioStock.model_validate(
            {key: row[key] for key in PortfolioStock.model_fields if key in row}
        )
        if stock.ticker in metadata:
            raise PortfolioInputError(f"The watchlist repeats {stock.ticker}.")
        metadata[stock.ticker] = row
    rows: list[dict[str, str]] = []
    columns = list(_COLUMNS)
    if contents[0] and contents[0].strip():
        reader = csv.DictReader(StringIO(contents[0].decode("utf-8-sig")))
        columns = list(reader.fieldnames or [])
        if not set(_COLUMNS).issubset(columns) or len(set(columns)) != len(columns):
            raise PortfolioInputError(
                "positions.csv needs ticker, shares, cost_per_share, opened, sector and currency columns."
            )
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise PortfolioInputError("positions.csv contains an incomplete row.")
            rows.append(row)
    holdings = []
    currency = "USD"
    cash = "0"
    currencies = {row["currency"].strip().upper() for row in rows}
    if len(currencies) > 1:
        raise PortfolioInputError(
            "This portfolio has more than one currency. Keep separate currencies in separate spaces."
        )
    if currencies:
        currency = next(iter(currencies))
    seen = set()
    for row in rows:
        ticker = row["ticker"].strip().upper()
        if ticker in seen:
            raise PortfolioInputError(f"positions.csv repeats {ticker}.")
        seen.add(ticker)
        if ticker == "CASH":
            cash = row["shares"].strip()
            continue
        detail = metadata.get(ticker, {})
        holdings.append(
            PortfolioHolding(
                ticker=ticker,
                shares=row["shares"],
                cost_per_share=row["cost_per_share"] or None,
                opened=row["opened"] or None,
                sector=row["sector"],
                company_name=detail.get("company_name", ""),
                industry=detail.get("industry", ""),
                exchange=detail.get("exchange", "US"),
            )
        )
    held = {row.ticker for row in holdings}
    watched = [
        PortfolioStock.model_validate(
            {key: row[key] for key in PortfolioStock.model_fields if key in row}
        )
        for symbol, row in metadata.items()
        if symbol not in held
    ]
    if contents[2] is not None and any(
        key not in limits for key in PortfolioLimits.model_fields
    ):
        raise PortfolioInputError("config/limits.json needs all three percentage limits.")
    percentages = PortfolioLimits.model_validate(
        {"max_position_pct": "10", "max_sector_pct": "70", "max_daily_loss_pct": "3"}
        if contents[2] is None
        else {
            key: format(limits[key], "f")
            if isinstance(limits[key], Decimal)
            else str(limits[key])
            for key in PortfolioLimits.model_fields
        }
    )
    return (
        PersonalPortfolio(
            currency=currency,
            cash=cash,
            holdings=holdings,
            watchlist=watched,
            limits=percentages,
        ),
        watch,
        limits,
        rows,
        columns,
    )


class SinceReport(BaseModel):
    """What changed since the report before, as compute_portfolio recorded it."""

    session: str
    skipped_sessions: list[str]
    total_value: float
    value_change: float
    value_change_pct: float | None
    price_change_pct: dict[str, float | None]


class PortfolioValuation(BaseModel):
    """The newest valuation, for Home's portfolio card. Read-only."""

    as_of: str
    currency: str
    total_value: float
    day_change: float
    day_change_pct: float | None
    positions_date: str | None = None
    since_previous: SinceReport | None = None


_VALUATION = "portfolio/computed.json"
_MAX_VALUATION_BYTES = 1_000_000


def load_valuation(root: Path) -> PortfolioValuation | None:
    """The last saved valuation; nothing, rather than an error, if there is none
    or it cannot be read, since the next run writes a new one."""
    path = root / _VALUATION
    if root.is_symlink() or path.parent.is_symlink() or path.is_symlink():
        return None
    try:
        if not path.is_file() or path.stat().st_size > _MAX_VALUATION_BYTES:
            return None
        return PortfolioValuation.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, UnicodeError, ValueError):
        return None


def load_portfolio(root: Path) -> PortfolioResponse:
    with _LOCK:
        contents = _read(_paths(root))
        try:
            portfolio, *_ = _decode(contents)
        except (ValueError, UnicodeError, csv.Error, TypeError) as exc:
            raise PortfolioInputError(
                f"Could not read your portfolio data: {exc}. Check the input in Knowledge → Technical Details → Agent files."
            ) from exc
        return PortfolioResponse(portfolio=portfolio, revision=_revision(contents))


def _replace(path: Path, content: bytes) -> None:
    temporary = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_bytes(content)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def save_portfolio(root: Path, body: SavePortfolioRequest) -> PortfolioResponse:
    with _LOCK:
        paths = _paths(root)
        originals = _read(paths)
        if _revision(originals) != body.revision:
            raise PortfolioConflictError(
                "Your portfolio changed since this form opened. Reload the latest data before saving."
            )
        _, watch, limits, old_rows, columns = _decode(originals)
        portfolio = body.portfolio
        previous = {row["ticker"].strip().upper(): row for row in old_rows}
        output = StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        for holding in portfolio.holdings:
            row = {
                **previous.get(holding.ticker, {}),
                **{key: getattr(holding, key) or "" for key in _COLUMNS if key != "currency"},
                "currency": portfolio.currency,
            }
            writer.writerow(row)
        writer.writerow(
            {
                **previous.get("CASH", {}),
                "ticker": "CASH",
                "shares": portfolio.cash,
                "cost_per_share": "",
                "opened": "",
                "sector": "Cash",
                "currency": portfolio.currency,
            }
        )
        old_metadata = {
            str(row["ticker"]).strip().upper(): row for row in watch.get("watchlist", [])
        }
        watch["watchlist"] = [
            {
                **old_metadata.get(row.ticker, {}),
                **row.model_dump(include=set(PortfolioStock.model_fields)),
            }
            for row in [*portfolio.holdings, *portfolio.watchlist]
        ]
        # Limits must remain JSON numbers for the deterministic tools. Emit the
        # validated decimal strings directly rather than rounding through float.
        values = {key: Decimal(value) for key, value in portfolio.limits.model_dump().items()}
        limit_text = _json_text(limits | values) + "\n"
        contents = [
            output.getvalue().encode(),
            (_json_text(watch) + "\n").encode(),
            limit_text.encode(),
        ]
        # Back up before replacing any canonical input. A failed later replace
        # rolls back already written files; saved originals remain recoverable.
        backup = root / ".agentbase" / "backups" / f"portfolio-{uuid.uuid4().hex}"
        if (root / ".agentbase").is_symlink() or (root / ".agentbase/backups").is_symlink():
            raise PortfolioInputError("The backup folder is a symlink; data was not changed.")
        restore = backup / ".restore"
        for path, original in zip(paths, originals, strict=True):
            if original is not None:
                destination = backup / path.relative_to(root)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(original)
                staged = restore / path.relative_to(root)
                staged.parent.mkdir(parents=True, exist_ok=True)
                staged.write_bytes(original)
        changed = []
        try:
            for path, content in zip(paths, contents, strict=True):
                path.parent.mkdir(parents=True, exist_ok=True)
                _replace(path, content)
                changed.append(path)
        except OSError as failure:
            unrestored = []
            for path in reversed(changed):
                original = originals[paths.index(path)]
                try:
                    if original is None:
                        path.unlink(missing_ok=True)
                    else:
                        (restore / path.relative_to(root)).replace(path)
                except OSError:
                    unrestored.append(path.relative_to(root).as_posix())
            if unrestored:
                raise PortfolioInputError(
                    f"Saving failed and these files could not be restored: {', '.join(unrestored)}. Original files are kept in {backup.relative_to(root).as_posix()}. Close files open in another app before restoring them."
                ) from failure
            raise
        if restore.exists():
            # Keep spare recovery copies when cleanup is refused.
            with contextlib.suppress(OSError):
                shutil.rmtree(restore)
        return PortfolioResponse(portfolio=portfolio, revision=_revision(contents))
