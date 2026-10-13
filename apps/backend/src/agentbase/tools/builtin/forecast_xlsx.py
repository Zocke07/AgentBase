"""Small, deterministic Excel exports for the forecast ledger.

A month's workbook has one sheet per market session: a row per ticker, with
each horizon's prediction beside the actual close once that session arrives.
A last sheet lists every forecast of the month with its method, assumption
band, rationale and evidence, for filtering.

This writes the documented SpreadsheetML ZIP format using the standard library.
Text is always an inline string, so a headline or rationale cannot become a
spreadsheet formula. The JSON ledger remains the source of truth.
"""

from __future__ import annotations

import re
from collections import defaultdict
from io import BytesIO
from typing import Any, Final
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

__all__ = ["DETAIL_SHEET", "forecast_workbook"]

_NS: Final[str] = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL: Final[str] = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_CONTROL: Final[re.Pattern[str]] = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_LABELS: Final[dict[int, str]] = {
    1: "1 day",
    2: "2 days",
    3: "3 days",
    5: "1 week",
    21: "1 month",
}
_METHODS: Final[dict[str, str]] = {
    "random_walk_baseline": "Random-walk baseline",
    "analyst_thesis": "Analyst thesis",
    "agent_scenario": "Agent scenario",
}
DETAIL_SHEET: Final[str] = "All forecasts"

#: Cell styles in ``_styles``: plain, bold header, two decimal places.
_PLAIN, _HEADER, _DECIMAL = 0, 1, 2

_DETAIL_FIELDS: Final[tuple[tuple[str, str], ...]] = (
    ("ticker", "Ticker"),
    ("horizon_days", "Trading sessions"),
    ("horizon_label", "Horizon"),
    ("as_of", "Baseline session"),
    ("baseline_close", "Baseline close (USD)"),
    ("predicted_close", "Prediction (USD)"),
    ("assumption_return_pct", "Assumed return %"),
    ("interval_low", "Assumption band low"),
    ("interval_high", "Assumption band high"),
    ("method", "Method"),
    ("confidence", "Agent confidence (uncalibrated)"),
    ("actual_date", "Actual session"),
    ("actual_close", "Actual close (USD)"),
    ("error_pct", "Prediction error %"),
    ("actual_return_pct", "Actual return %"),
    ("status", "Status"),
    ("created_at", "Issued at (UTC)"),
    ("rationale", "Assumptions and rationale"),
    ("evidence_ids", "Evidence IDs"),
)
_DETAIL_DECIMALS: Final[frozenset[str]] = frozenset(
    {"baseline_close", "predicted_close", "actual_close", "interval_low", "interval_high"}
)


def forecast_workbook(rows: list[dict[str, Any]]) -> bytes:
    """Return one month's workbook: a sheet per session, then every forecast."""
    sessions: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        sessions[row["as_of"]].append(row)
    sheets = [(name, _session_sheet(sessions[name])) for name in sorted(sessions)]
    sheets.append((DETAIL_SHEET, _detail_sheet(rows)))
    count = len(sheets)
    workbook = (
        f'<workbook xmlns="{_NS}" xmlns:r="{_REL}"><sheets>'
        + "".join(
            f'<sheet name="{escape(name)}" sheetId="{index}" r:id="rId{index}"/>'
            for index, (name, _) in enumerate(sheets, start=1)
        )
        + "</sheets></workbook>"
    )
    relationships = (
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + "".join(
            f'<Relationship Id="rId{index}" Type="{_REL}/worksheet" '
            f'Target="worksheets/sheet{index}.xml"/>'
            for index in range(1, count + 1)
        )
        + f'<Relationship Id="rId{count + 1}" Type="{_REL}/styles" '
        'Target="styles.xml"/></Relationships>'
    )
    types = (
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        + "".join(
            f'<Override PartName="/xl/worksheets/sheet{index}.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            for index in range(1, count + 1)
        )
        + "</Types>"
    )
    files = {
        "[Content_Types].xml": types,
        "_rels/.rels": (
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'<Relationship Id="rId1" Type="{_REL}/officeDocument" Target="xl/workbook.xml"/>'
            "</Relationships>"
        ),
        "xl/workbook.xml": workbook,
        "xl/_rels/workbook.xml.rels": relationships,
        "xl/styles.xml": _styles(),
    }
    for index, (_, content) in enumerate(sheets, start=1):
        files[f"xl/worksheets/sheet{index}.xml"] = content
    buffer = BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
        for name, content in files.items():
            # Fixed timestamps also make repeated exports byte-for-byte stable.
            info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            archive.writestr(info, '<?xml version="1.0" encoding="UTF-8"?>' + content)
    return buffer.getvalue()


def _session_sheet(rows: list[dict[str, Any]]) -> str:
    """A ticker per row: each horizon's prediction, actual close and error."""
    by_ticker: dict[str, dict[int, dict[str, Any]]] = defaultdict(dict)
    for row in rows:
        by_ticker[row["ticker"]][row["horizon_days"]] = row
    header: list[tuple[object, int]] = [("Ticker", _HEADER), ("Baseline close (USD)", _HEADER)]
    for label in _LABELS.values():
        header += [
            (f"{label} prediction (USD)", _HEADER),
            (f"{label} actual (USD)", _HEADER),
            (f"{label} error %", _HEADER),
        ]
    header += [("Method", _HEADER), ("Notes", _HEADER)]
    table: list[list[tuple[object, int]]] = [header]
    for ticker in sorted(by_ticker):
        forecasts = by_ticker[ticker]
        first = next(iter(forecasts.values()))
        cells: list[tuple[object, int]] = [
            (ticker, _PLAIN),
            (first["baseline_close"], _DECIMAL),
        ]
        for horizon in _LABELS:
            forecast = forecasts.get(horizon, {})
            cells += [
                (forecast.get("predicted_close"), _DECIMAL),
                (forecast.get("actual_close"), _DECIMAL),
                (forecast.get("error_pct"), _DECIMAL),
            ]
        claims = {
            horizon: forecasts[horizon]["method"]
            for horizon in _LABELS
            if forecasts.get(horizon, {}).get("method", "random_walk_baseline")
            != "random_walk_baseline"
        }
        cells += [(_method_summary(claims), _PLAIN), (_notes(forecasts, claims), _PLAIN)]
        table.append(cells)
    widths = [(1, 1, 10), (2, 17, 14), (18, 18, 40), (19, 19, 90)]
    return _worksheet(table, widths, frozen_columns=1)


def _method_summary(claims: dict[int, str]) -> str:
    """Which horizons carry a thesis or scenario, by method, and that the rest are baselines."""
    if not claims:
        return _METHODS["random_walk_baseline"]
    by_method: dict[str, list[str]] = {}
    for horizon, method in claims.items():
        by_method.setdefault(method, []).append(_LABELS[horizon])
    parts = [
        f"{_METHODS.get(method, method)} for "
        + ("every horizon" if len(labels) == len(_LABELS) else ", ".join(labels))
        for method, labels in by_method.items()
    ]
    if len(claims) < len(_LABELS):
        parts.append("random-walk baseline for the rest")
    return "; ".join(parts)


def _notes(forecasts: dict[int, dict[str, Any]], claims: dict[int, str]) -> str | None:
    """Each thesis's or scenario's assumption; a baseline needs no note of its own."""
    notes = [f"{_LABELS[horizon]}: {forecasts[horizon]['rationale']}" for horizon in claims]
    return " | ".join(notes) or None


def _detail_sheet(rows: list[dict[str, Any]]) -> str:
    table: list[list[tuple[object, int]]] = [[(label, _HEADER) for _, label in _DETAIL_FIELDS]]
    for row in sorted(rows, key=lambda r: (r["as_of"], r["ticker"], r["horizon_days"])):
        cells: list[tuple[object, int]] = []
        for field, _ in _DETAIL_FIELDS:
            value = row.get(field)
            if field == "horizon_label":
                value = _LABELS[row["horizon_days"]]
            elif field == "evidence_ids":
                value = ", ".join(row["evidence_ids"])
            cells.append((value, _DECIMAL if field in _DETAIL_DECIMALS else _PLAIN))
        table.append(cells)
    widths = [(1, 17, 21), (18, 19, 75)]
    return _worksheet(table, widths, frozen_columns=0)


def _worksheet(
    table: list[list[tuple[object, int]]],
    widths: list[tuple[int, int, int]],
    *,
    frozen_columns: int,
) -> str:
    rendered = [
        f'<row r="{number}">'
        + "".join(
            _cell(column, number, value, style=style)
            for column, (value, style) in enumerate(cells, start=1)
        )
        + "</row>"
        for number, cells in enumerate(table, start=1)
    ]
    last = f"{_column(len(table[0]))}{len(table)}"
    pane = (
        f'<pane xSplit="{frozen_columns}" ySplit="1" topLeftCell="{_column(frozen_columns + 1)}2" '
        'activePane="bottomRight" state="frozen"/>'
        if frozen_columns
        else '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
    )
    return (
        f'<worksheet xmlns="{_NS}"><dimension ref="A1:{last}"/>'
        f'<sheetViews><sheetView workbookViewId="0">{pane}</sheetView></sheetViews>'
        "<cols>"
        + "".join(
            f'<col min="{first}" max="{final}" width="{width}" customWidth="1"/>'
            for first, final, width in widths
        )
        + "</cols>"
        "<sheetData>" + "".join(rendered) + "</sheetData>"
        f'<autoFilter ref="A1:{last}"/></worksheet>'
    )


def _column(index: int) -> str:
    result = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _cell(index: int, row: int, value: object, *, style: int = _PLAIN) -> str:
    address = f"{_column(index)}{row}"
    if value is None:
        return f'<c r="{address}"/>'
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f'<c r="{address}" s="{style}"><v>{value}</v></c>'
    text = escape(_CONTROL.sub("", str(value)))
    return (
        f'<c r="{address}" s="{style}" t="inlineStr">'
        f'<is><t xml:space="preserve">{text}</t></is></c>'
    )


def _styles() -> str:
    return (
        f'<styleSheet xmlns="{_NS}">'
        '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
        '<font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
        '<fills count="2"><fill><patternFill patternType="none"/></fill>'
        '<fill><patternFill patternType="gray125"/></fill></fills>'
        '<borders count="1"><border/></borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="3"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
        '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>'
        '<xf numFmtId="2" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
        '</cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/>'
        "</cellStyles></styleSheet>"
    )
