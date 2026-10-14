"""Forecast persistence and Excel exports against small recorded US sessions."""

from __future__ import annotations

import csv
import json
from datetime import UTC, datetime
from io import BytesIO, StringIO
from pathlib import Path
from typing import Any
from zipfile import ZipFile

import pytest
from defusedxml.ElementTree import fromstring

from agentbase.tools.base import ToolArgumentError, ToolExecutionError
from agentbase.tools.builtin.forecasts import FORECAST_HORIZONS, TrackForecastsTool
from agentbase.tools.catalogue import RiskLevel
from agentbase.tools.sandbox import Sandbox, SandboxViolationError

pytestmark = pytest.mark.anyio
_NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
_RECORDED = (
    ("2026-09-28", 100),
    ("2026-09-29", 103),
    ("2026-09-30", 102),
    ("2026-10-01", 104),
    ("2026-10-02", 105),
    ("2026-10-05", 106),
    ("2026-10-06", 108),
    ("2026-10-07", 107),
    ("2026-10-08", 109),
    ("2026-10-09", 111),
    ("2026-10-12", 110),
    ("2026-10-13", 112),
    ("2026-10-14", 113),
    ("2026-10-15", 114),
    ("2026-10-16", 115),
    ("2026-10-19", 116),
    ("2026-10-20", 117),
    ("2026-10-21", 118),
    ("2026-10-22", 119),
    ("2026-10-23", 120),
    ("2026-10-26", 121),
    ("2026-10-27", 122),
    ("2026-10-28", 123),
    ("2026-10-29", 124),
    ("2026-10-30", 125),
)


@pytest.fixture
def sandbox(tmp_path: Path) -> Sandbox:
    return Sandbox(tmp_path)


def _prices(
    sandbox: Sandbox, sessions: tuple[tuple[str, int], ...], ticker: str = "MU"
) -> None:
    directory = sandbox.root / "raw/prices"
    directory.mkdir(parents=True, exist_ok=True)
    buffer = StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(("date", "open", "high", "low", "close", "volume"))
    for session, close in sessions:
        writer.writerow((session, close, close, close, close, 1000))
    (directory / f"{ticker}.csv").write_text(buffer.getvalue(), encoding="utf-8")
    (directory / "summary.csv").write_text(
        f"ticker,date,close,currency\n{ticker},{sessions[-1][0]},{sessions[-1][1]},USD\n",
        encoding="utf-8",
    )


async def _run(sandbox: Sandbox, now: str, **arguments: Any) -> dict[str, Any]:
    tool = TrackForecastsTool(clock=lambda: datetime.fromisoformat(now))
    result: dict[str, Any] = json.loads(
        await tool.execute(tool.prepare(arguments, sandbox), sandbox)
    )
    return result


def _ledger(sandbox: Sandbox) -> list[dict[str, Any]]:
    document = json.loads(
        (sandbox.root / "predictions/forecasts.json").read_text(encoding="utf-8")
    )
    return list(document["forecasts"])


def _issued(sandbox: Sandbox, result: dict[str, Any]) -> list[dict[str, Any]]:
    """The session's full forecast rows, which the result names only in brief."""
    return [row for row in _ledger(sandbox) if row["as_of"] == result["as_of"]]


def _scenario(**overrides: Any) -> dict[str, Any]:
    return {
        "ticker": "MU",
        "horizon_days": 1,
        "scenario_return_pct": 2,
        "rationale": "Assume a 2% rebound if the cited result sustains demand; price can fall if it does not.",
        "evidence_ids": ["movers-2026-09-30-MU"],
        **overrides,
    }


def _sheet_rows(path: Path, number: int) -> list[list[object]]:
    """A worksheet's cells by row: text, a number, or None for an empty cell."""
    with ZipFile(path) as archive:
        sheet = fromstring(archive.read(f"xl/worksheets/sheet{number}.xml"))
    rows: list[list[object]] = []
    for row in sheet.findall("s:sheetData/s:row", _NS):
        values: list[object] = []
        for cell in row.findall("s:c", _NS):
            text = cell.find("s:is/s:t", _NS)
            number_node = cell.find("s:v", _NS)
            if text is not None:
                values.append(text.text)
            elif number_node is not None and number_node.text is not None:
                values.append(float(number_node.text))
            else:
                values.append(None)
        rows.append(values)
    return rows


def _movers(sandbox: Sandbox) -> None:
    (sandbox.root / "raw/movers-2026-09-30.json").write_text(
        json.dumps([{"id": "movers-2026-09-30-MU", "ticker": "MU", "date": "2026-09-30"}]),
        encoding="utf-8",
    )


async def test_default_generates_five_horizons_with_honest_baselines_and_excel(
    sandbox: Sandbox,
) -> None:
    _prices(sandbox, _RECORDED[:3])
    tool = TrackForecastsTool(clock=lambda: datetime(2026, 9, 30, 22, tzinfo=UTC))
    assert tool.risk is RiskLevel.MEDIUM
    result = json.loads(await tool.execute(tool.prepare({}, sandbox), sandbox))
    assert result["appended"] == 5
    assert result["pending"] == 5
    assert [row["horizon_days"] for row in _issued(sandbox, result)] == list(FORECAST_HORIZONS)
    assert all(row["predicted_close"] == 102 for row in _issued(sandbox, result))
    assert all(row["confidence"] is None for row in _issued(sandbox, result))
    assert all(row["method"] == "random_walk_baseline" for row in _issued(sandbox, result))
    assert all(row["actual_close"] is None for row in _issued(sandbox, result))
    assert (
        _issued(sandbox, result)[0]["interval_low"]
        < 102
        < _issued(sandbox, result)[0]["interval_high"]
    )
    assert (
        _issued(sandbox, result)[4]["interval_high"]
        > _issued(sandbox, result)[0]["interval_high"]
    )
    assert result["written"] == ["predictions/forecasts.json", "predictions/2026-09.xlsx"]
    with ZipFile(sandbox.root / "predictions/2026-09.xlsx") as archive:
        # Parse every XML part, validate the sheet linkage, and inspect data.
        for filename in archive.namelist():
            fromstring(archive.read(filename))
        workbook = fromstring(archive.read("xl/workbook.xml"))
        names = [node.get("name") for node in workbook.findall("s:sheets/s:sheet", _NS)]
        assert names == ["2026-09-30", "All forecasts"]
        worksheet = fromstring(archive.read("xl/worksheets/sheet1.xml"))
        # The session sheet: one row per ticker, every horizon side by side.
        assert len(worksheet.findall("s:sheetData/s:row", _NS)) == 2
        texts = [node.text for node in worksheet.findall(".//s:t", _NS)]
        assert "1 day prediction (USD)" in texts and "1 month actual (USD)" in texts
        assert "Random-walk baseline" in texts
        pane = worksheet.find("s:sheetViews/s:sheetView/s:pane", _NS)
        assert pane is not None and pane.get("state") == "frozen"
        details = fromstring(archive.read("xl/worksheets/sheet2.xml"))
        assert len(details.findall("s:sheetData/s:row", _NS)) == 6
        detail_texts = [node.text for node in details.findall(".//s:t", _NS)]
        assert "random_walk_baseline" in detail_texts and "1 month" in detail_texts


async def test_agent_scenario_computes_price_and_preserves_original_on_rerun(
    sandbox: Sandbox,
) -> None:
    _prices(sandbox, _RECORDED[:3])
    _movers(sandbox)
    first = await _run(
        sandbox, "2026-09-30T22:00:00+00:00", forecasts=[_scenario(confidence=0.55)]
    )
    assert first["appended"] == 5
    row = _issued(sandbox, first)[0]
    assert row["baseline_close"] == 102
    assert row["predicted_close"] == 104.04
    assert row["assumption_return_pct"] == 2
    assert row["method"] == "agent_scenario"
    assert row["interval_low"] is None
    assert _issued(sandbox, first)[1]["method"] == "random_walk_baseline"
    ledger_before = (sandbox.root / "predictions/forecasts.json").read_bytes()
    excel_before = (sandbox.root / "predictions/2026-09.xlsx").read_bytes()
    second = await _run(
        sandbox, "2026-09-30T23:00:00+00:00", forecasts=[_scenario(scenario_return_pct=80)]
    )
    assert second["appended"] == 0 and second["preserved"] == 5
    assert second["written"] == []
    assert (sandbox.root / "predictions/forecasts.json").read_bytes() == ledger_before
    assert (sandbox.root / "predictions/2026-09.xlsx").read_bytes() == excel_before
    # A corrected historical source cannot rewrite either the target or base.
    _prices(sandbox, (*_RECORDED[:2], ("2026-09-30", 200), *_RECORDED[3:4]))
    updated = await _run(sandbox, "2026-10-01T22:00:00+00:00", refresh_only=True)
    assert updated["newly_resolved"] == 1
    resolved = _ledger(sandbox)[0]
    assert resolved["baseline_close"] == 102 and resolved["predicted_close"] == 104.04
    assert resolved["actual_close"] == 104
    _prices(sandbox, (*_RECORDED[:3], ("2026-10-01", 999)))
    again = await _run(sandbox, "2026-10-01T23:00:00+00:00", refresh_only=True)
    assert again["newly_resolved"] == 0 and _ledger(sandbox)[0]["actual_close"] == 104


async def test_actuals_count_sessions_skip_weekends_and_update_prior_month(
    sandbox: Sandbox,
) -> None:
    _prices(sandbox, _RECORDED[:3])
    await _run(sandbox, "2026-09-30T22:00:00+00:00")
    september_before = (sandbox.root / "predictions/2026-09.xlsx").read_bytes()
    _prices(sandbox, _RECORDED[:5])
    october = await _run(sandbox, "2026-10-02T22:00:00+00:00")
    assert october["newly_resolved"] == 2 and october["appended"] == 5
    assert october["workbooks"] == ["predictions/2026-09.xlsx", "predictions/2026-10.xlsx"]
    assert (sandbox.root / "predictions/2026-09.xlsx").read_bytes() != september_before
    september = [row for row in _ledger(sandbox) if row["as_of"] == "2026-09-30"]
    assert [row["actual_date"] for row in september] == [
        "2026-10-01",
        "2026-10-02",
        None,
        None,
        None,
    ]
    _prices(sandbox, _RECORDED[:6])
    monday = await _run(sandbox, "2026-10-05T22:00:00+00:00", refresh_only=True)
    assert monday["newly_resolved"] == 2
    september = [row for row in _ledger(sandbox) if row["as_of"] == "2026-09-30"]
    assert september[2]["actual_date"] == "2026-10-05"
    _prices(sandbox, _RECORDED)
    complete = await _run(sandbox, "2026-10-30T22:00:00+00:00", refresh_only=True)
    september = [row for row in _ledger(sandbox) if row["as_of"] == "2026-09-30"]
    assert [row["actual_date"] for row in september] == [
        "2026-10-01",
        "2026-10-02",
        "2026-10-05",
        "2026-10-07",
        "2026-10-29",
    ]
    assert september[4]["actual_close"] == 124 and september[4]["status"] == "resolved"
    assert "predictions/2026-09.xlsx" in complete["written"]
    again = await _run(sandbox, "2026-10-30T23:00:00+00:00", refresh_only=True)
    assert again["newly_resolved"] == 0 and again["written"] == []


async def test_incomplete_current_session_is_excluded_from_actuals_and_targets(
    sandbox: Sandbox,
) -> None:
    _prices(sandbox, _RECORDED[:5])
    friday = await _run(sandbox, "2026-10-02T22:00:00+00:00")
    assert friday["as_of"] == "2026-10-02"
    _prices(sandbox, _RECORDED[:6])
    during = await _run(sandbox, "2026-10-05T18:00:00+00:00")
    assert during["newly_resolved"] == 0 and during["appended"] == 0
    assert "trading now" in during["not_issued"]
    assert during["as_of"] == "2026-10-02"
    after = await _run(sandbox, "2026-10-05T22:00:00+00:00", refresh_only=True)
    assert after["newly_resolved"] == 1
    assert _ledger(sandbox)[0]["actual_date"] == "2026-10-05"


@pytest.mark.parametrize(
    "arguments",
    [
        {"as_of": "2026-09-31"},
        {"symbols": ["../../outside"]},
        {"symbols": []},
        {"symbols": ["MU"] * 51},
        {"refresh_only": "true"},
        {"forecasts": [_scenario(horizon_days=7)]},
        {"forecasts": [_scenario(horizon_days=True)]},
        {"forecasts": [_scenario(scenario_return_pct="NaN")]},
        {"forecasts": [_scenario(scenario_return_pct=-100)]},
        {"forecasts": [_scenario(predicted_close=100)]},
        {"forecasts": [_scenario(evidence_ids=[])]},
        {"forecasts": [_scenario(confidence=1.5)]},
        {"forecasts": [_scenario(rationale="")]},
        {"forecasts": [_scenario(), _scenario()]},
        {"refresh_only": True, "forecasts": [_scenario()]},
    ],
)
def test_invalid_arguments_have_no_side_effects(
    sandbox: Sandbox, arguments: dict[str, Any]
) -> None:
    with pytest.raises(ToolArgumentError):
        TrackForecastsTool().prepare(arguments, sandbox)
    assert not (sandbox.root / "predictions").exists()


async def test_evidence_must_be_saved_and_available_at_issuance_and_bad_inputs_do_not_corrupt(
    sandbox: Sandbox,
) -> None:
    _prices(sandbox, _RECORDED[:3])
    _movers(sandbox)
    raw = sandbox.root / "raw"
    # Post-close headlines are usable on next morning's run, before issuing.
    (raw / "news-2026-10-01.jsonl").write_text(
        json.dumps({"id": "news-valid", "published": "2026-09-30T23:00:00Z"})
        + "\n"
        + json.dumps({"id": "news-future", "published": "2026-10-02T23:00:00Z"}),
        encoding="utf-8",
    )
    valid = await _run(
        sandbox, "2026-10-01T02:00:00+00:00", forecasts=[_scenario(evidence_ids=["news-valid"])]
    )
    assert _issued(sandbox, valid)[0]["method"] == "agent_scenario"
    before = (sandbox.root / "predictions/forecasts.json").read_bytes()
    excel = (sandbox.root / "predictions/2026-09.xlsx").read_bytes()
    _prices(sandbox, _RECORDED[:4])
    for evidence_id in ("news-future", "missing-id"):
        with pytest.raises(ToolExecutionError, match="unavailable"):
            await _run(
                sandbox,
                "2026-10-01T22:00:00+00:00",
                forecasts=[_scenario(evidence_ids=[evidence_id])],
            )
        assert (sandbox.root / "predictions/forecasts.json").read_bytes() == before
        assert (sandbox.root / "predictions/2026-09.xlsx").read_bytes() == excel


async def test_cited_report_facts_and_screener_rows_count_from_when_they_were_fetched(
    sandbox: Sandbox,
) -> None:
    # The analysts cite these ids: a fact has no publication time of its own,
    # so it is available from when its document was fetched.
    _prices(sandbox, _RECORDED[:3])
    filings = sandbox.root / "raw/filings"
    filings.mkdir(parents=True)
    fact = "financials-MU-2026-08-31-quarterlyTotalRevenue"
    (filings / "MU.json").write_text(
        json.dumps(
            {
                "ticker": "MU",
                "fetched_at": "2026-09-30T22:30:00+00:00",
                "financials": [{"id": fact, "period_end": "2026-08-31", "published": None}],
                "filings": [],
            }
        ),
        encoding="utf-8",
    )
    market = sandbox.root / "raw/market"
    market.mkdir(parents=True)
    screener = "screener-2026-09-30-day_gainers-MU"
    (market / "screeners-2026-09-30.json").write_text(
        json.dumps(
            [{"name": "day_gainers", "quotes": [{"id": screener, "date": "2026-09-30"}]}]
        ),
        encoding="utf-8",
    )

    result = await _run(
        sandbox,
        "2026-10-01T02:00:00+00:00",
        forecasts=[_scenario(evidence_ids=[fact, screener])],
    )

    assert _issued(sandbox, result)[0]["method"] == "agent_scenario"
    assert _issued(sandbox, result)[0]["evidence_ids"] == [fact, screener]


async def test_report_facts_fetched_after_issuance_are_refused(sandbox: Sandbox) -> None:
    _prices(sandbox, _RECORDED[:3])
    filings = sandbox.root / "raw/filings"
    filings.mkdir(parents=True)
    fact = "financials-MU-2026-08-31-quarterlyTotalRevenue"
    (filings / "MU.json").write_text(
        json.dumps(
            {
                "ticker": "MU",
                "fetched_at": "2026-10-01T03:00:00+00:00",
                "financials": [{"id": fact, "period_end": "2026-08-31", "published": None}],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ToolExecutionError, match="unavailable"):
        await _run(
            sandbox, "2026-10-01T02:00:00+00:00", forecasts=[_scenario(evidence_ids=[fact])]
        )


async def test_historical_submission_cannot_use_later_prices(sandbox: Sandbox) -> None:
    _prices(sandbox, _RECORDED[:4])
    _movers(sandbox)
    with pytest.raises(ToolExecutionError, match="cannot be backfilled"):
        await _run(
            sandbox, "2026-10-01T22:00:00+00:00", as_of="2026-09-30", forecasts=[_scenario()]
        )
    assert not (sandbox.root / "predictions").exists()


async def test_missing_old_baseline_leaves_actual_pending(sandbox: Sandbox) -> None:
    _prices(sandbox, _RECORDED[:3])
    await _run(sandbox, "2026-09-30T22:00:00+00:00")
    _prices(sandbox, _RECORDED[3:])
    result = await _run(sandbox, "2026-10-30T22:00:00+00:00", refresh_only=True)
    assert result["newly_resolved"] == 0 and result["pending"] == 5
    assert len(result["unresolved"]) == 5


async def test_corrupt_ledger_is_refused_without_replacing_workbook(sandbox: Sandbox) -> None:
    _prices(sandbox, _RECORDED[:3])
    await _run(sandbox, "2026-09-30T22:00:00+00:00")
    ledger = sandbox.root / "predictions/forecasts.json"
    excel = (sandbox.root / "predictions/2026-09.xlsx").read_bytes()
    ledger.write_text('{"version":1,"forecasts":[{"ticker":"MU"}]}', encoding="utf-8")
    with pytest.raises(ToolExecutionError, match="ledger is invalid"):
        await _run(sandbox, "2026-09-30T22:00:00+00:00", refresh_only=True)
    assert (sandbox.root / "predictions/2026-09.xlsx").read_bytes() == excel


async def test_xlsx_treats_rationale_as_text_and_adds_one_sheet_per_day(
    sandbox: Sandbox,
) -> None:
    _prices(sandbox, _RECORDED[:4])
    _movers(sandbox)
    rationale = '=HYPERLINK("https://example.invalid", "<Headline>&")'
    await _run(
        sandbox,
        "2026-10-01T22:00:00+00:00",
        forecasts=[_scenario(evidence_ids=["prices-2026-10-01-MU"], rationale=rationale)],
    )
    _prices(sandbox, _RECORDED[:5])
    await _run(sandbox, "2026-10-02T22:00:00+00:00")
    with ZipFile(BytesIO((sandbox.root / "predictions/2026-10.xlsx").read_bytes())) as archive:
        workbook = fromstring(archive.read("xl/workbook.xml"))
        assert [node.get("name") for node in workbook.findall("s:sheets/s:sheet", _NS)] == [
            "2026-10-01",
            "2026-10-02",
            "All forecasts",
        ]
        sheet = fromstring(archive.read("xl/worksheets/sheet1.xml"))
        assert f"1 day: {rationale}" in [node.text for node in sheet.findall(".//s:t", _NS)]
        details = fromstring(archive.read("xl/worksheets/sheet3.xml"))
        assert rationale in [node.text for node in details.findall(".//s:t", _NS)]
        for number in (1, 2, 3):
            part = fromstring(archive.read(f"xl/worksheets/sheet{number}.xml"))
            assert part.findall(".//s:f", _NS) == []


def test_forecasts_resolve_paths_before_approval(sandbox: Sandbox, tmp_path: Path) -> None:
    outside = tmp_path.parent / "external-forecasts"
    outside.mkdir(exist_ok=True)
    (sandbox.root / "predictions").symlink_to(outside, target_is_directory=True)
    with pytest.raises(SandboxViolationError):
        TrackForecastsTool().prepare({}, sandbox)


async def test_refresh_uses_pending_tickers_even_if_summary_is_missing(
    sandbox: Sandbox,
) -> None:
    _prices(sandbox, _RECORDED[:3])
    await _run(sandbox, "2026-09-30T22:00:00+00:00")
    _prices(sandbox, _RECORDED[:4])
    (sandbox.root / "raw/prices/summary.csv").unlink()
    result = await _run(sandbox, "2026-10-01T22:00:00+00:00", refresh_only=True)
    assert result["newly_resolved"] == 1 and result["as_of"] == "2026-10-01"


async def test_response_is_bounded_but_ledger_and_workbook_keep_all_tickers(
    sandbox: Sandbox,
) -> None:
    symbols = [f"STOCK{index}" for index in range(21)]
    for symbol in symbols:
        _prices(sandbox, _RECORDED[:3], symbol)
    result = await _run(sandbox, "2026-09-30T22:00:00+00:00", symbols=symbols)
    assert result["appended"] == 105 and result["current_forecasts"] == 105
    assert result["scenarios"] == [] and result["truncated"] is False
    assert result["baselines"] == {"forecasts": 105, "tickers": sorted(symbols)}
    assert len(_ledger(sandbox)) == 105
    workbook = sandbox.root / "predictions/2026-09.xlsx"
    assert len(_sheet_rows(workbook, 1)) == 22
    assert len(_sheet_rows(workbook, 2)) == 106


async def test_the_result_names_the_sessions_forecasts_in_brief(sandbox: Sandbox) -> None:
    """2026-10-14: the result listed 100 of the session's 130 forecasts in full,
    about 19,000 tokens that the decision re-sent at every later step. A
    baseline repeats the last close, so the result counts those; the analysts'
    and agents' own forecasts come in brief. The ledger keeps every field."""
    _prices(sandbox, _RECORDED[:3])
    _movers(sandbox)

    result = await _run(
        sandbox, "2026-09-30T22:00:00+00:00", forecasts=[_scenario(confidence=0.55)]
    )

    assert "forecasts" not in result
    assert result["baselines"] == {"forecasts": 4, "tickers": ["MU"]}
    assert result["scenarios"] == [
        {
            "forecast_id": "2026-09-30-MU-1",
            "ticker": "MU",
            "horizon_days": 1,
            "method": "agent_scenario",
            "baseline_close": 102,
            "predicted_close": 104.04,
            "assumption_return_pct": 2,
            "interval_low": None,
            "interval_high": None,
            "confidence": 0.55,
            "evidence_ids": ["movers-2026-09-30-MU"],
        }
    ]
    assert result["truncated"] is False
    (full,) = [row for row in _ledger(sandbox) if row["method"] == "agent_scenario"]
    assert full["rationale"].startswith("Assume a 2% rebound")


async def test_partial_scenarios_still_forecast_every_active_summary_ticker(
    sandbox: Sandbox,
) -> None:
    _prices(sandbox, _RECORDED[:3], "MU")
    _prices(sandbox, _RECORDED[:3], "ORCL")
    (sandbox.root / "raw/prices/summary.csv").write_text(
        "ticker,date,close,currency\nMU,2026-09-30,102,USD\nORCL,2026-09-30,102,USD\n",
        encoding="utf-8",
    )
    _movers(sandbox)
    result = await _run(sandbox, "2026-09-30T22:00:00+00:00", forecasts=[_scenario()])
    assert result["appended"] == 10 and result["current_forecasts"] == 10
    assert {row["ticker"] for row in _issued(sandbox, result)} == {"MU", "ORCL"}
    scenarios = [row for row in _issued(sandbox, result) if row["method"] == "agent_scenario"]
    assert len(scenarios) == 1 and scenarios[0]["ticker"] == "MU"
    assert all(
        row["method"] == "random_walk_baseline"
        for row in _issued(sandbox, result)
        if row["ticker"] == "ORCL"
    )


async def test_session_sheet_puts_each_horizons_prediction_beside_its_actual(
    sandbox: Sandbox,
) -> None:
    # What the person asked for: a row per stock, each horizon's prediction,
    # and the actual close beside it once that session has traded.
    _prices(sandbox, _RECORDED[:3])
    _movers(sandbox)
    await _run(sandbox, "2026-09-30T22:00:00+00:00", forecasts=[_scenario()])
    _prices(sandbox, _RECORDED[:5])
    await _run(sandbox, "2026-10-02T22:00:00+00:00", refresh_only=True)

    rows = _sheet_rows(sandbox.root / "predictions/2026-09.xlsx", 1)
    header, mu = rows
    assert header[:8] == [
        "Ticker",
        "Baseline close (USD)",
        "1 day prediction (USD)",
        "1 day actual (USD)",
        "1 day error %",
        "2 days prediction (USD)",
        "2 days actual (USD)",
        "2 days error %",
    ]
    assert header[-2:] == ["Method", "Notes"]
    # 102 baseline; a 2% scenario for one day; actuals 104 and 105 so far.
    assert mu[:8] == ["MU", 102.0, 104.04, 104.0, 0.038462, 102.0, 105.0, -2.857143]
    assert mu[8:11] == [102.0, None, None]
    assert mu[-2] == "Agent scenario for 1 day; random-walk baseline for the rest"
    assert str(mu[-1]).startswith("1 day: Assume a 2% rebound")


def _thesis(agent: str, horizon: int, band: str, **overrides: Any) -> str:
    row = {
        "pred_id": f"{agent}-{horizon}",
        "as_of": "2026-09-30T16:00:00-04:00",
        "agent": agent,
        "ticker": "MU",
        "horizon_days": horizon,
        "direction": "up" if agent == "bull" else "down",
        "magnitude_band": band,
        "confidence": 0.56,
        "thesis": "Memory pricing guidance points higher for the quarter.",
        "evidence_ids": ["movers-2026-09-30-MU"],
        "invalidation": "Closes below 98.00",
        "base_rate_note": "Typical one-day move is about 2%.",
        **overrides,
    }
    return json.dumps(row)


def _theses(sandbox: Sandbox, bull: list[str], bear: list[str]) -> None:
    folder = sandbox.root / "theses"
    folder.mkdir(exist_ok=True)
    (folder / "bull-2026-09-30.jsonl").write_text("\n".join(bull), encoding="utf-8")
    (folder / "bear-2026-09-30.jsonl").write_text("\n".join(bear), encoding="utf-8")


async def test_the_sessions_theses_become_analyst_forecasts_from_their_bands(
    sandbox: Sandbox,
) -> None:
    """2026-10-13: no thesis set expected_return_pct, so every forecast in the
    friend's workbook was the unchanged close. A thesis's direction and band
    are a forecast; the tool turns them into one, and the person can see how."""
    _prices(sandbox, _RECORDED[:3])
    _movers(sandbox)
    _theses(
        sandbox,
        bull=[_thesis("bull", 21, "5%+")],
        bear=[
            _thesis("bear", 1, "1-3%"),
            "not json",
            _thesis("bear", 2, "1-3%", direction="up"),
        ],
    )

    result = await _run(sandbox, "2026-10-01T02:00:00+00:00")

    rows = {row["horizon_days"]: row for row in _issued(sandbox, result)}
    one_day, month = rows[1], rows[21]
    assert one_day["method"] == "analyst_thesis" and month["method"] == "analyst_thesis"
    # Down 1-3%: the band's midpoint, 2%, with the band as the range.
    assert one_day["predicted_close"] == 99.96
    assert (one_day["interval_low"], one_day["interval_high"]) == (98.94, 100.98)
    assert one_day["assumption_return_pct"] == -2 and one_day["confidence"] == 0.56
    assert one_day["evidence_ids"] == ["movers-2026-09-30-MU"]
    assert one_day["rationale"].startswith("Bear thesis: down 1-3% over 1 session")
    # Up at least 5%: the least the analyst claimed, open above.
    assert month["predicted_close"] == 107.1 and month["interval_high"] is None
    assert rows[3]["method"] == rows[5]["method"] == "random_walk_baseline"
    # A row that says the wrong direction for its file is reported, not used.
    assert rows[2]["method"] == "random_walk_baseline"
    assert result["analyst_forecasts"] == 2
    assert len(result["thesis_problems"]) == 2
    _, mu = _sheet_rows(sandbox.root / "predictions/2026-09.xlsx", 1)
    assert mu[-2] == "Analyst thesis for 1 day, 1 month; random-walk baseline for the rest"
    assert str(mu[-1]).startswith("1 day: Bear thesis: down 1-3% over 1 session")


async def test_bull_and_bear_disagreeing_leave_the_benchmark_and_say_so(
    sandbox: Sandbox,
) -> None:
    _prices(sandbox, _RECORDED[:3])
    _movers(sandbox)
    _theses(sandbox, bull=[_thesis("bull", 1, "1-3%")], bear=[_thesis("bear", 1, "0-1%")])

    result = await _run(sandbox, "2026-10-01T02:00:00+00:00")

    one_day = next(row for row in _issued(sandbox, result) if row["horizon_days"] == 1)
    assert one_day["method"] == "random_walk_baseline"
    assert "disagreed" in one_day["rationale"]
    assert result["thesis_conflicts"] == [{"ticker": "MU", "horizon_days": 1}]


async def test_a_thesis_whose_evidence_is_missing_falls_back_to_the_benchmark(
    sandbox: Sandbox,
) -> None:
    _prices(sandbox, _RECORDED[:3])
    _theses(sandbox, bull=[_thesis("bull", 1, "1-3%", evidence_ids=["invented-id"])], bear=[])

    result = await _run(sandbox, "2026-10-01T02:00:00+00:00")

    one_day = next(row for row in _issued(sandbox, result) if row["horizon_days"] == 1)
    assert one_day["method"] == "random_walk_baseline"
    assert any("invented-id" in item["reason"] for item in result["skipped"])


async def test_a_thesis_ticker_outside_the_summary_is_still_forecast(sandbox: Sandbox) -> None:
    _prices(sandbox, _RECORDED[:3], "MU")
    _prices(sandbox, _RECORDED[:3], "ORCL")  # the summary now names ORCL only
    _movers(sandbox)
    _theses(sandbox, bull=[_thesis("bull", 1, "1-3%")], bear=[])

    result = await _run(sandbox, "2026-10-01T02:00:00+00:00")

    assert {row["ticker"] for row in _issued(sandbox, result)} == {"MU", "ORCL"}


async def test_an_analysts_own_return_is_used_only_inside_its_band(sandbox: Sandbox) -> None:
    _prices(sandbox, _RECORDED[:3])
    _movers(sandbox)
    _theses(
        sandbox,
        bull=[
            _thesis("bull", 1, "1-3%", expected_return_pct=2.5),
            _thesis("bull", 2, "1-3%", expected_return_pct=7),
        ],
        bear=[],
    )

    result = await _run(sandbox, "2026-10-01T02:00:00+00:00")

    rows = {row["horizon_days"]: row for row in _issued(sandbox, result)}
    assert rows[1]["assumption_return_pct"] == 2.5 and rows[1]["predicted_close"] == 104.55
    assert "the analyst assumes +2.5%" in rows[1]["rationale"]
    # A figure outside the thesis's own band gives way to the band's midpoint.
    assert rows[2]["assumption_return_pct"] == 2 and rows[2]["predicted_close"] == 104.04


async def test_while_the_market_trades_actuals_fill_but_no_forecast_is_issued(
    sandbox: Sandbox,
) -> None:
    """2026-10-13: a Run now at 13:47 New York forecast Monday's close from
    Friday's, citing Monday's own midday headline. A forecast issued while
    its first session trades has already seen part of what it predicts."""
    _prices(sandbox, _RECORDED[:3])
    await _run(sandbox, "2026-09-30T22:00:00+00:00")
    _prices(sandbox, _RECORDED[:4])  # Thursday 2026-10-01 has closed.
    _movers(sandbox)
    _theses(sandbox, bull=[_thesis("bull", 1, "1-3%")], bear=[])

    # Friday 2026-10-02 at 11:00 in New York: Friday's session is under way.
    result = await _run(sandbox, "2026-10-02T15:00:00+00:00")

    assert result["appended"] == 0 and result["newly_resolved"] == 1
    assert result["not_issued"].startswith("The US market is trading now")
    assert {row["as_of"] for row in _ledger(sandbox)} == {"2026-09-30"}
    with pytest.raises(ToolExecutionError, match="trading now"):
        await _run(sandbox, "2026-10-02T15:00:00+00:00", forecasts=[_scenario()])
    _prices(sandbox, _RECORDED[:5])  # After Friday's close, with its prices saved.
    after_close = await _run(sandbox, "2026-10-02T21:00:00+00:00")
    assert after_close["as_of"] == "2026-10-02" and after_close["appended"] == 5
    assert after_close["not_issued"] is None
