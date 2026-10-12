"""Authentic, bounded annual/quarterly financial evidence for equity research.

Yahoo's keyless financial time series provides dated secondary-source figures
by default. With a configured SEC contact header, EDGAR adds filing links,
official reported facts and bounded filing excerpts. A missing source is a
reported limitation, never fabricated financial data.
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Final
from urllib.parse import quote, urlencode

import httpx2

from agentbase.tools.base import Prepared, ToolArgumentError, ToolExecutionError
from agentbase.tools.builtin.fetching import (
    checked_request,
    clean_text,
    fetch_bytes,
    finite_number,
    json_object,
    read_local,
    write_json,
)
from agentbase.tools.builtin.market import YAHOO_HOST, parse_symbols
from agentbase.tools.builtin.network import plain_text
from agentbase.tools.catalogue import RiskLevel, lookup

if TYPE_CHECKING:
    from collections.abc import Callable

    from agentbase.tools.sandbox import Sandbox

__all__ = ["ReadCompanyReportsTool"]

MAX_REPORT_SYMBOLS: Final[int] = 50
MAX_SEC_BYTES: Final[int] = 10_000_000
MAX_FILING_BYTES: Final[int] = 3_000_000
MAX_EXCERPT_CHARS: Final[int] = 8_000
_TYPES: Final[tuple[str, ...]] = (
    "annualTotalRevenue",
    "quarterlyTotalRevenue",
    "annualNetIncome",
    "quarterlyNetIncome",
)
_CONCEPTS: Final[tuple[str, ...]] = (
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Revenues",
    "SalesRevenueNet",
    "NetIncomeLoss",
    "EarningsPerShareDiluted",
    "Assets",
    "CashAndCashEquivalentsAtCarryingValue",
    "NetCashProvidedByUsedInOperatingActivities",
)
_SEC_CONTACT: Final[re.Pattern[str]] = re.compile(r"\S+@\S+\.\S+")
_ACCESSION: Final[re.Pattern[str]] = re.compile(r"^\d{10}-\d{2}-\d{6}$")
_DOCUMENT: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9_-][A-Za-z0-9_.-]{0,149}$")


def _declaration(name: str) -> tuple[str, RiskLevel]:
    declaration = lookup(name)
    if declaration is None:  # pragma: no cover: catalogue test pins this
        raise RuntimeError(f"{name!r} has an implementation but no catalogue entry")
    return declaration.description, declaration.risk


class ReadCompanyReportsTool:
    """Persist annual/quarterly report evidence with traceable dates and sources."""

    name = "read_company_reports"

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
                    "minItems": 1,
                    "maxItems": MAX_REPORT_SYMBOLS,
                    "description": "US equity tickers to read annual and quarterly financial evidence for.",
                },
                "sec_user_agent": {
                    "type": "string",
                    "description": "Optional identifying SEC contact header; otherwise config/sources.json reports.sec_user_agent is used.",
                },
            },
            "required": ["symbols"],
            "additionalProperties": False,
        }

    def prepare(self, arguments: dict[str, Any], sandbox: Sandbox) -> Prepared:
        symbols = parse_symbols(
            arguments.get("symbols"), required=True, maximum=MAX_REPORT_SYMBOLS
        )
        if not symbols:
            raise ToolArgumentError("At least one equity ticker is required.")
        sources = sandbox.resolve_path("config/sources.json")
        contact = arguments.get("sec_user_agent")
        if contact is None:
            try:
                content = read_local(sources)
                document = json_object(content, "config/sources.json") if content else {}
                reports = document.get("reports", {})
                contact = reports.get("sec_user_agent", "") if isinstance(reports, dict) else ""
            except (OSError, ToolExecutionError) as exc:
                raise ToolArgumentError(
                    f"Could not read report source configuration: {exc}"
                ) from exc
        if (
            not isinstance(contact, str)
            or len(contact) > 250
            or "\r" in contact
            or "\n" in contact
        ):
            raise ToolArgumentError(
                "sec_user_agent must be a plain header below 250 characters."
            )
        contact = contact.strip()
        if contact and _SEC_CONTACT.search(contact) is None:
            raise ToolArgumentError(
                "SEC contact must identify your app and include a contact email."
            )
        now = self._clock().astimezone(UTC)
        date = now.date().isoformat()
        requests = [
            {"symbol": symbol, **checked_request(sandbox, _financials_url(symbol, now))}
            for symbol in symbols
        ]
        hosts = [YAHOO_HOST]
        sec: dict[str, dict[str, str]] = {}
        if contact:
            hosts.extend(["www.sec.gov", "data.sec.gov"])
            sec = {
                "tickers": checked_request(
                    sandbox, "https://www.sec.gov/files/company_tickers.json"
                ),
                "data": checked_request(
                    sandbox, "https://data.sec.gov/submissions/CIK0000000000.json"
                ),
            }
        return Prepared(
            tool_name=self.name,
            summary=f"read dated annual/quarterly financial evidence for {', '.join(symbols)}"
            + (" from Yahoo Finance and SEC filings" if contact else " from Yahoo Finance"),
            payload={
                "host": YAHOO_HOST,
                "hosts": hosts,
                "symbols": symbols,
                "requests": requests,
                "sec": sec,
                "sec_user_agent": contact,
                "as_of": date,
                "fetched_at": now.isoformat(),
                "paths": {
                    symbol: sandbox.resolve_write_path(f"raw/filings/{symbol}.json")
                    for symbol in symbols
                },
                "reports_path": sandbox.resolve_write_path(f"raw/filings/reports-{date}.json"),
            },
            raw_arguments=dict(arguments),
        )

    async def execute(self, prepared: Prepared, sandbox: Sandbox) -> str:
        payload = prepared.payload
        client = self._client or httpx2.AsyncClient(timeout=20)
        warnings: list[str] = []
        if not payload["sec_user_agent"]:
            warnings.append(
                "SEC filing bodies are unavailable until reports.sec_user_agent in "
                "config/sources.json contains your app name and contact email. "
                "Yahoo annual/quarterly figures are secondary-source financial evidence; "
                "they do not supply an official filing publication date."
            )
        try:
            reports = await _yahoo_reports(client, payload)
            if payload["sec_user_agent"]:
                await _sec_reports(client, payload, reports, warnings)
        finally:
            if self._client is None:
                await client.aclose()
        written: list[str] = []
        for report in reports:
            path = payload["paths"][report["ticker"]]
            await asyncio.to_thread(write_json, path, report)
            written.append(sandbox.relative(path))
        document = {
            "as_of": payload["as_of"],
            "fetched_at": payload["fetched_at"],
            "reports": reports,
            "warnings": warnings,
        }
        await asyncio.to_thread(write_json, payload["reports_path"], document)
        written.append(sandbox.relative(payload["reports_path"]))
        return json.dumps(
            {
                "as_of": document["as_of"],
                "fetched_at": document["fetched_at"],
                "warnings": warnings,
                "reports": [
                    _report_summary(
                        report, sandbox.relative(payload["paths"][report["ticker"]])
                    )
                    for report in reports
                ],
                "reports_path": sandbox.relative(payload["reports_path"]),
                "failures": [
                    {"ticker": row["ticker"], "errors": row["errors"]}
                    for row in reports
                    if not row["financials"] and not row["filings"]
                ],
                "written": written,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )


def _financials_url(symbol: str, now: datetime) -> str:
    return (
        f"https://{YAHOO_HOST}/ws/fundamentals-timeseries/v1/finance/timeseries/{quote(symbol, safe='')}?"
        + urlencode(
            {
                "symbol": symbol,
                "type": ",".join(_TYPES),
                "period1": int((now - timedelta(days=730)).timestamp()),
                "period2": int(now.timestamp()),
            }
        )
    )


async def _yahoo_reports(
    client: httpx2.AsyncClient, payload: dict[str, Any]
) -> list[dict[str, Any]]:
    semaphore = asyncio.Semaphore(5)

    async def one(request: dict[str, str]) -> dict[str, Any]:
        symbol = request["symbol"]
        report: dict[str, Any] = {
            "ticker": symbol,
            "fetched_at": payload["fetched_at"],
            "financials": [],
            "filings": [],
            "errors": [],
        }
        async with semaphore:
            try:
                document = json_object(await fetch_bytes(client, request), request["url"])
                series = document.get("timeseries", {})
                if not isinstance(series, dict) or series.get("error"):
                    raise ToolExecutionError("Yahoo returned a financial-series error.")
                rows = series.get("result")
                if not isinstance(rows, list):
                    raise ToolExecutionError(
                        "Yahoo returned no annual/quarterly financial series."
                    )
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    metadata = row.get("meta", {})
                    if not isinstance(metadata, dict) or metadata.get("symbol") != [symbol]:
                        raise ToolExecutionError(
                            "Yahoo returned a different financial-series symbol."
                        )
                    for kind in _TYPES:
                        values = row.get(kind, [])
                        if not isinstance(values, list):
                            continue
                        parsed = [
                            _financial_value(value, kind, request["url"], symbol)
                            for value in values
                        ]
                        valid = [
                            value
                            for value in parsed
                            if value is not None and value["period_end"] <= payload["as_of"]
                        ]
                        # Two latest reported periods permit an evidence-based comparison.
                        report["financials"].extend(
                            sorted(valid, key=lambda value: value["period_end"], reverse=True)[
                                :2
                            ]
                        )
                if not report["financials"]:
                    raise ToolExecutionError(
                        "Yahoo supplied no valid annual/quarterly figures."
                    )
            except ToolExecutionError as exc:
                report["errors"].append(str(exc))
        return report

    return await asyncio.gather(*(one(request) for request in payload["requests"]))


def _financial_value(value: Any, kind: str, url: str, symbol: str) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    period_end = value.get("asOfDate")
    reported = value.get("reportedValue")
    number = finite_number(reported.get("raw")) if isinstance(reported, dict) else None
    if number is None or not _date(period_end):
        return None
    return {
        "id": f"financials-{symbol}-{period_end}-{kind}",
        "metric": kind,
        "period_end": period_end,
        "period_type": clean_text(value.get("periodType")),
        "value": number,
        "currency": clean_text(value.get("currencyCode")),
        "published": None,
        "source": url,
        "source_kind": "Yahoo Finance secondary financial data",
    }


def _report_summary(report: dict[str, Any], path: str) -> dict[str, Any]:
    latest: dict[str, dict[str, Any]] = {}
    for fact in report["financials"]:
        key = fact["metric"] + (fact.get("form") or "")
        if key not in latest or fact["period_end"] > latest[key]["period_end"]:
            latest[key] = fact
    return {
        "ticker": report["ticker"],
        "path": path,
        "status": "available" if report["financials"] or report["filings"] else "unavailable",
        "latest_financials": [
            {
                key: fact[key]
                for key in ("id", "metric", "period_end", "value", "source_kind", "published")
            }
            | {"currency": fact.get("currency", fact.get("unit"))}
            for fact in list(latest.values())[:12]
        ],
        "filings": [
            {key: value for key, value in filing.items() if key != "excerpt"}
            for filing in report["filings"]
        ],
        "errors": report["errors"],
    }


def _date(value: Any) -> bool:
    if not isinstance(value, str) or re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is None:
        return False
    try:
        datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError:
        return False
    return True


async def _sec_reports(
    client: httpx2.AsyncClient,
    payload: dict[str, Any],
    reports: list[dict[str, Any]],
    warnings: list[str],
) -> None:
    sec = payload["sec"]
    contact = payload["sec_user_agent"]
    try:
        document = json_object(
            await fetch_bytes(
                client, sec["tickers"], user_agent=contact, maximum=MAX_SEC_BYTES
            ),
            "SEC ticker map",
        )
        ciks = {
            row["ticker"]: int(row["cik_str"])
            for row in document.values()
            if isinstance(row, dict)
            and isinstance(row.get("ticker"), str)
            and isinstance(row.get("cik_str"), int)
            and not isinstance(row["cik_str"], bool)
            and 0 < row["cik_str"] < 10_000_000_000
        }
    except ToolExecutionError as exc:
        warnings.append(f"SEC ticker index unavailable; Yahoo evidence retained: {exc}")
        return

    # Sequential requests with a minimum interval stay below SEC's 10/sec ceiling.
    for report in reports:
        symbol = report["ticker"]
        cik = ciks.get(symbol)
        if cik is None:
            report["errors"].append(f"No SEC CIK found for {symbol}.")
            continue
        url = f"https://data.sec.gov/submissions/CIK{cik:010d}.json"
        await asyncio.sleep(0.15)
        try:
            document = json_object(
                await fetch_bytes(
                    client, sec["data"], url=url, user_agent=contact, maximum=MAX_SEC_BYTES
                ),
                url,
            )
            if int(document.get("cik", 0)) != cik:
                raise ToolExecutionError("SEC submissions returned a different company CIK.")
            report["company_name"] = clean_text(document.get("name"))
            report["filings"] = _filings(document, cik, symbol, payload["as_of"])
            if not report["filings"]:
                report["errors"].append(
                    "No recent annual/quarterly filing was available in SEC submissions."
                )
        except (ToolExecutionError, ValueError, TypeError) as exc:
            report["errors"].append(f"SEC submissions unavailable: {exc}")
            continue
        await asyncio.sleep(0.15)
        facts_url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
        try:
            facts = json_object(
                await fetch_bytes(
                    client,
                    sec["data"],
                    url=facts_url,
                    user_agent=contact,
                    maximum=MAX_SEC_BYTES,
                ),
                facts_url,
            )
            if int(facts.get("cik", 0)) != cik:
                raise ToolExecutionError("SEC company facts returned a different company CIK.")
            report["financials"].extend(_official_facts(facts, report["filings"], facts_url))
        except (ToolExecutionError, ValueError, TypeError) as exc:
            report["errors"].append(f"SEC financial facts unavailable: {exc}")
        for filing in report["filings"]:
            await asyncio.sleep(0.15)
            try:
                body = await fetch_bytes(
                    client,
                    sec["tickers"],
                    url=filing["url"],
                    user_agent=contact,
                    maximum=MAX_FILING_BYTES,
                )
                text = plain_text(body.decode("utf-8", errors="replace"))
                filing["excerpt"] = _excerpt(text)
                filing["body_fetched"] = True
                filing["excerpt_truncated"] = len(text) > len(filing["excerpt"])
            except ToolExecutionError as exc:
                filing["body_fetched"] = False
                filing["excerpt"] = None
                report["errors"].append(f"SEC {filing['form']} text unavailable: {exc}")


def _filings(
    document: dict[str, Any], cik: int, symbol: str, as_of: str
) -> list[dict[str, Any]]:
    filing_object = document.get("filings", {})
    recent = filing_object.get("recent", {}) if isinstance(filing_object, dict) else {}
    if not isinstance(recent, dict):
        raise ToolExecutionError("SEC submissions has malformed recent filings.")
    fields: list[list[Any]] = []
    for key in ("form", "filingDate", "reportDate", "accessionNumber", "primaryDocument"):
        field = recent.get(key)
        if not isinstance(field, list):
            raise ToolExecutionError("SEC submissions lacks filing arrays.")
        fields.append(field)
    if len({len(value) for value in fields}) != 1:
        raise ToolExecutionError("SEC submissions has inconsistent filing array lengths.")
    rows: list[dict[str, Any]] = []
    for form, filed, period_end, accession, filename in zip(*fields, strict=True):
        if (
            form not in {"10-K", "10-Q", "20-F", "40-F"}
            or not _date(filed)
            or not _date(period_end)
            or filed > as_of
            or period_end > filed
        ):
            continue
        if not isinstance(accession, str) or _ACCESSION.fullmatch(accession) is None:
            continue
        if not isinstance(filename, str) or _DOCUMENT.fullmatch(filename) is None:
            continue
        rows.append(
            {
                "id": f"filing-{symbol}-{accession}",
                "ticker": symbol,
                "form": form,
                "published": filed,
                "period_end": period_end,
                "accession": accession,
                "url": f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-', '')}/{filename}",
                "source_kind": "Official SEC filing",
            }
        )
    rows.sort(key=lambda row: row["published"], reverse=True)
    selected: list[dict[str, Any]] = []
    for group in ({"10-K", "20-F", "40-F"}, {"10-Q"}):
        match = next((row for row in rows if row["form"] in group), None)
        if match is not None:
            selected.append(match)
    return selected


def _official_facts(
    document: dict[str, Any], filings: list[dict[str, Any]], url: str
) -> list[dict[str, Any]]:
    fact_object = document.get("facts", {})
    gaap = fact_object.get("us-gaap", {}) if isinstance(fact_object, dict) else {}
    if not isinstance(gaap, dict):
        raise ToolExecutionError("SEC financial facts has malformed GAAP concepts.")
    by_accession = {filing["accession"]: filing for filing in filings}
    selected: list[dict[str, Any]] = []
    for name in _CONCEPTS:
        concept = gaap.get(name, {})
        units = concept.get("units", {}) if isinstance(concept, dict) else {}
        if not isinstance(units, dict):
            continue
        for unit, values in list(units.items())[:2]:
            if not isinstance(values, list):
                continue
            matches: dict[str, dict[str, Any]] = {}
            for value in values:
                if not isinstance(value, dict):
                    continue
                accession = value.get("accn")
                if (
                    not isinstance(accession, str)
                    or accession not in by_accession
                    or finite_number(value.get("val")) is None
                ):
                    continue
                filing = by_accession[accession]
                if value.get("end") != filing["period_end"] or not _date(value.get("filed")):
                    continue
                # Prefer the current period rather than comparative prior-period facts.
                current = matches.get(accession)
                if current is None or str(value.get("start", "")) > str(
                    current.get("start", "")
                ):
                    matches[accession] = value
            for accession, value in matches.items():
                filing = by_accession[accession]
                selected.append(
                    {
                        "id": f"financials-{filing['ticker']}-{accession}-{name}-{unit}",
                        "metric": name,
                        "value": value["val"],
                        "unit": clean_text(unit),
                        "period_start": value.get("start")
                        if _date(value.get("start"))
                        else None,
                        "period_end": value["end"],
                        "published": value["filed"],
                        "form": filing["form"],
                        "source": url,
                        "filing_url": filing["url"],
                        "source_kind": "Official SEC XBRL financial fact",
                    }
                )
    return selected


def _excerpt(text: str) -> str:
    # Include bounded contexts around named report sections, rather than only
    # its cover page. Text is evidence, never instructions for the agent.
    terms = (
        r"item\s+1\.?\s+business",
        r"item\s+1a\.?\s+risk factors",
        r"management.s discussion and analysis",
        r"results of operations",
    )
    excerpts: list[str] = []
    for pattern in terms:
        matches = list(re.finditer(pattern, text, re.IGNORECASE))
        if matches:
            match = matches[-1]  # Usually skip a table-of-contents occurrence.
            excerpts.append(text[match.start() : match.start() + 2_000])
    return "\n\n".join(excerpts)[:MAX_EXCERPT_CHARS] if excerpts else text[:MAX_EXCERPT_CHARS]
