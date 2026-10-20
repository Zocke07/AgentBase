"""The deterministic portfolio calculator, entirely against local fixtures."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agentbase.tools.base import ToolArgumentError, ToolExecutionError
from agentbase.tools.builtin.limits import CheckLimitsTool
from agentbase.tools.builtin.portfolio import ComputePortfolioTool
from agentbase.tools.catalogue import RiskLevel
from agentbase.tools.sandbox import Sandbox

pytestmark = pytest.mark.anyio


@pytest.fixture
def sandbox(tmp_path: Path) -> Sandbox:
    root = tmp_path / "workspace"
    root.mkdir()
    return Sandbox(root)


def _write(
    sandbox: Sandbox,
    path: str,
    content: str,
    *,
    modified: str | None = None,
) -> Path:
    target = sandbox.root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8", newline="")
    if modified is not None:
        stamp = datetime.fromisoformat(modified).replace(tzinfo=UTC).timestamp()
        os.utime(target, (stamp, stamp))
    return target


def _limits(sandbox: Sandbox) -> None:
    _write(
        sandbox,
        "config/limits.json",
        '{"max_position_pct":10,"max_sector_pct":30,"max_daily_loss_pct":3}\n',
    )


async def test_compute_portfolio_writes_exact_book_weights_and_limit_crossings(
    sandbox: Sandbox,
) -> None:
    _write(
        sandbox,
        "portfolio/positions.csv",
        (
            "ticker,shares,cost_per_share,opened,sector,currency\n"
            "CASH,1000,,,Cash,USD\n"
            "AAPL,10,100,2026-09-20,Technology,USD\n"
            "MSFT,5,200,2026-09-10,Technology,USD\n"
            "JNJ,2,150,2026-08-01,Healthcare,USD\n"
        ),
        modified="2026-09-28T12:00:00",
    )
    _write(
        sandbox,
        "raw/prices/summary.csv",
        (
            "ticker,date,close,prev_close,currency\n"
            "AAPL,2026-09-30,120,118,USD\n"
            "JNJ,2026-09-30,140,142,USD\n"
            "MSFT,2026-09-30,220,225,USD\n"
        ),
    )
    _limits(sandbox)
    tool = ComputePortfolioTool()

    prepared = tool.prepare({"as_of": "2026-09-30"}, sandbox)
    assert prepared.summary == (
        "compute the portfolio from portfolio/positions.csv and the saved prices"
    )
    assert tool.risk is RiskLevel.MEDIUM
    assert not (sandbox.root / "portfolio/computed.json").exists()
    assert not (sandbox.root / "portfolio/weights.csv").exists()

    result = json.loads(await tool.execute(prepared, sandbox))

    # The run view lists these; the computed file itself does not carry them.
    assert result["written"] == ["portfolio/computed.json", "portfolio/weights.csv"]
    computed = (sandbox.root / "portfolio/computed.json").read_text(encoding="utf-8")
    assert "written" not in json.loads(computed)
    assert result["as_of"] == "2026-09-30"
    assert result["positions_date"] == "2026-09-28"
    assert result["stale"] is False
    assert result["price_dates"] == {
        "AAPL": "2026-09-30",
        "JNJ": "2026-09-30",
        "MSFT": "2026-09-30",
    }
    assert result["currency"] == "USD"
    assert result["total_value"] == 3580
    assert result["cash"] == 1000
    assert result["invested"] == 2580
    assert result["day_change"] == -9
    assert result["day_change_pct"] == -0.2508
    assert result["unrealised"] == 280
    assert result["unrealised_pct"] == 12.1739
    assert result["realised"] is None
    assert result["period_pnl"] is None
    assert "transaction history" in result["realised_reason"]
    assert "transaction history" in result["period_pnl_reason"]

    assert [row["ticker"] for row in result["positions"]] == ["AAPL", "JNJ", "MSFT"]
    assert result["positions"][0] == {
        "ticker": "AAPL",
        "shares": 10,
        "weight_pct": 33.5196,
        "cost_per_share": 100,
        "close": 120,
        "value": 1200,
        "unrealised": 200,
        "unrealised_pct": 20,
        "days_held": 10,
        "sector": "Technology",
    }
    assert result["concentration"] == {
        "largest_weight_pct": 33.5196,
        "top3_weight_pct": 72.067,
        "sector_weights": {"Healthcare": 7.8212, "Technology": 64.2458},
        "limit_crossings": [
            {
                "rule": "max_position_pct",
                "subject": "AAPL",
                "value": 33.5196,
                "threshold": 10,
            },
            {
                "rule": "max_position_pct",
                "subject": "MSFT",
                "value": 30.7263,
                "threshold": 10,
            },
            {
                "rule": "max_sector_pct",
                "subject": "Technology",
                "value": 64.2458,
                "threshold": 30,
            },
        ],
    }

    saved = json.loads((sandbox.root / "portfolio/computed.json").read_text(encoding="utf-8"))
    assert saved == {key: value for key, value in result.items() if key != "written"}
    assert (sandbox.root / "portfolio/weights.csv").read_text(
        encoding="utf-8"
    ).splitlines() == [
        "ticker,weight_pct,value,sector,currency",
        "AAPL,33.5196,1200.00,Technology,USD",
        "CASH,27.9330,1000.00,Cash,USD",
        "JNJ,7.8212,280.00,Healthcare,USD",
        "MSFT,30.7263,1100.00,Technology,USD",
    ]


async def test_compute_portfolio_supports_the_zero_cash_only_starter(
    sandbox: Sandbox,
) -> None:
    _write(
        sandbox,
        "portfolio/positions.csv",
        "ticker,shares,cost_per_share,opened,sector,currency\nCASH,0,,,Cash,USD\n",
        modified="2026-09-30T08:00:00",
    )
    _limits(sandbox)

    result = json.loads(
        await ComputePortfolioTool().execute(
            ComputePortfolioTool().prepare({}, sandbox), sandbox
        )
    )

    assert result["as_of"] == "2026-09-30"
    assert result["currency"] == "USD"
    assert result["total_value"] == 0
    assert result["positions"] == []
    assert result["price_dates"] == {}
    assert result["day_change_pct"] is None
    assert result["unrealised_pct"] is None
    assert result["concentration"]["limit_crossings"] == []


async def test_unknown_purchase_cost_and_date_still_value_and_check_holdings(
    sandbox: Sandbox,
) -> None:
    _write(
        sandbox,
        "portfolio/positions.csv",
        (
            "ticker,shares,cost_per_share,opened,sector,currency\n"
            "CASH,2500,,,Cash,USD\n"
            "MU,1,,,Technology,USD\n"
            "MSFT,1,200,2026-09-01,Technology,USD\n"
        ),
    )
    _write(
        sandbox,
        "raw/prices/summary.csv",
        (
            "ticker,date,close,prev_close,currency\n"
            "MU,2026-09-30,150,145,USD\n"
            "MSFT,2026-09-30,450,440,USD\n"
        ),
    )
    _limits(sandbox)
    tool = ComputePortfolioTool()
    result = json.loads(await tool.execute(tool.prepare({}, sandbox), sandbox))
    assert result["total_value"] == 3100
    assert result["day_change"] == 15
    assert result["unrealised"] is None
    assert "Purchase cost is unknown" in result["unrealised_reason"]
    positions = {row["ticker"]: row for row in result["positions"]}
    assert positions["MU"]["cost_per_share"] is None
    assert positions["MU"]["days_held"] is None
    assert positions["MU"]["unrealised"] is None
    assert positions["MSFT"]["unrealised"] == 250
    assert result["concentration"]["limit_crossings"][0]["subject"] == "MSFT"


async def test_a_cash_only_book_is_computed_for_the_newest_saved_session(
    sandbox: Sandbox,
) -> None:
    """With nothing held, no price fixed the date, so it was the day positions.csv
    was saved. check_limits then refused every later session's theses: the
    2026-10-07 chain stopped on "computed.json is for ..., not thesis date"."""
    _write(
        sandbox,
        "portfolio/positions.csv",
        "ticker,shares,cost_per_share,opened,sector,currency\nCASH,0,,,Cash,USD\n",
        modified="2026-10-01T11:15:00",
    )
    _write(
        sandbox,
        "raw/prices/summary.csv",
        "ticker,date,open,high,low,close,volume,prev_close,change_pct,"
        "avg_volume_20d,rel_volume,microcap,rank,currency\n"
        "AAPL,2026-10-06,332.00,334.38,330.62,333.63,30425700,332.89,0.2223,"
        "41975560,0.7248,False,1,USD\n",
    )
    _write(
        sandbox,
        "config/watchlist.json",
        '{"watchlist":[{"ticker":"AAPL","sector":"Information Technology"}]}\n',
    )
    _write(sandbox, "theses/bull-2026-10-06.jsonl", "")
    _write(sandbox, "theses/bear-2026-10-06.jsonl", "")
    _limits(sandbox)

    tool = ComputePortfolioTool()
    result = json.loads(await tool.execute(tool.prepare({}, sandbox), sandbox))
    assert result["as_of"] == "2026-10-06"
    assert result["positions_date"] == "2026-10-01"
    assert result["stale"] is True
    assert result["price_dates"] == {}

    checks = CheckLimitsTool()
    checked = json.loads(
        await checks.execute(checks.prepare({"date": "2026-10-06"}, sandbox), sandbox)
    )
    assert checked["portfolio_as_of"] == "2026-10-06"


async def test_compute_portfolio_marks_stale_positions_and_daily_loss_crossings(
    sandbox: Sandbox,
) -> None:
    _write(
        sandbox,
        "portfolio/positions.csv",
        (
            "ticker,shares,cost_per_share,opened,sector,currency\n"
            "AAPL,1,100,2026-09-01,Technology,USD\n"
        ),
        modified="2026-09-20T08:00:00",
    )
    _write(
        sandbox,
        "raw/prices/summary.csv",
        "ticker,date,close,prev_close,currency\nAAPL,2026-09-30,90,100,USD\n",
    )
    _write(
        sandbox,
        "config/limits.json",
        '{"max_position_pct":100,"max_sector_pct":100,"max_daily_loss_pct":3}\n',
    )
    tool = ComputePortfolioTool()

    result = json.loads(await tool.execute(tool.prepare({}, sandbox), sandbox))

    assert result["stale"] is True
    assert result["day_change_pct"] == -10
    assert result["concentration"]["limit_crossings"] == [
        {
            "rule": "max_daily_loss_pct",
            "subject": "portfolio",
            "value": -10,
            "threshold": 3,
        }
    ]


async def test_compute_portfolio_uses_the_current_iso_currency_list(
    sandbox: Sandbox,
) -> None:
    positions = sandbox.root / "portfolio/positions.csv"
    _write(
        sandbox,
        "portfolio/positions.csv",
        "ticker,shares,cost_per_share,opened,sector,currency\nCASH,0,,,Cash,XCG\n",
    )
    _limits(sandbox)
    tool = ComputePortfolioTool()

    current = json.loads(await tool.execute(tool.prepare({}, sandbox), sandbox))
    assert current["currency"] == "XCG"

    positions.write_text(
        "ticker,shares,cost_per_share,opened,sector,currency\nCASH,0,,,Cash,BGN\n",
        encoding="utf-8",
        newline="",
    )
    with pytest.raises(ToolExecutionError, match="current uppercase ISO 4217"):
        await tool.execute(tool.prepare({}, sandbox), sandbox)


@pytest.mark.parametrize(
    ("positions", "message"),
    (
        (
            "ticker,shares,cost_per_share,opened,sector\nCASH,0,,,Cash\n",
            "required 'currency' column",
        ),
        (
            "ticker,shares,cost_per_share,opened,sector,currency\nCASH,0,,,Cash,usd\n",
            "uppercase ISO 4217",
        ),
        (
            "ticker,shares,cost_per_share,opened,sector,currency\nCASH,0,,,Cash,ZZZ\n",
            "current uppercase ISO 4217",
        ),
        (
            "ticker,shares,cost_per_share,opened,sector,currency\nCASH,1e100,,,Cash,USD\n",
            "supported range",
        ),
        (
            "ticker,shares,cost_per_share,opened,sector,currency\n"
            "CASH,0,,,Cash,USD\nAAPL,1,100,2026-09-01,Technology,TWD\n",
            "TWD and USD",
        ),
        (
            "ticker,shares,cost_per_share,opened,sector,currency\n"
            "AAPL,1,100,2026-09-01,Technology,USD\n"
            "AAPL,2,100,2026-09-02,Technology,USD\n",
            "duplicate ticker AAPL",
        ),
    ),
)
async def test_compute_portfolio_rejects_invalid_positions_with_actionable_errors(
    sandbox: Sandbox,
    positions: str,
    message: str,
) -> None:
    _write(sandbox, "portfolio/positions.csv", positions)
    _limits(sandbox)
    tool = ComputePortfolioTool()

    with pytest.raises(ToolExecutionError, match=message):
        await tool.execute(tool.prepare({"as_of": "2026-09-30"}, sandbox), sandbox)

    assert not (sandbox.root / "portfolio/computed.json").exists()
    assert not (sandbox.root / "portfolio/weights.csv").exists()


async def test_compute_portfolio_names_missing_prices_and_currency_mismatch(
    sandbox: Sandbox,
) -> None:
    _write(
        sandbox,
        "portfolio/positions.csv",
        (
            "ticker,shares,cost_per_share,opened,sector,currency\n"
            "AAPL,1,100,2026-09-01,Technology,USD\n"
        ),
    )
    _limits(sandbox)
    tool = ComputePortfolioTool()
    prepared = tool.prepare({"as_of": "2026-09-30"}, sandbox)

    with pytest.raises(ToolExecutionError, match=r"raw/prices/summary\.csv.*read_prices"):
        await tool.execute(prepared, sandbox)

    _write(
        sandbox,
        "raw/prices/summary.csv",
        "ticker,date,close,prev_close,currency\nAAPL,2026-09-30,120,118,TWD\n",
    )
    with pytest.raises(ToolExecutionError, match="TWD and USD"):
        await tool.execute(prepared, sandbox)


def test_compute_portfolio_validates_its_optional_date(sandbox: Sandbox) -> None:
    tool = ComputePortfolioTool()

    with pytest.raises(ToolArgumentError, match="YYYY-MM-DD"):
        tool.prepare({"as_of": "30 September 2026"}, sandbox)


@pytest.mark.parametrize(
    "positions",
    [None, "", "ticker,shares,cost_per_share,opened,sector,currency\n"],
    ids=["missing", "blank", "header-only"],
)
async def test_an_empty_portfolio_is_an_empty_book_not_a_failure(
    sandbox: Sandbox, positions: str | None
) -> None:
    """A tool error here stopped the whole daily chain before any thesis."""
    if positions is not None:
        _write(sandbox, "portfolio/positions.csv", positions)
    _write(
        sandbox,
        "raw/prices/summary.csv",
        "ticker,date,open,high,low,close,volume,prev_close,change_pct,"
        "avg_volume_20d,rel_volume,microcap,rank,currency\n"
        "AAPL,2026-10-06,332.00,334.38,330.62,333.63,30425700,332.89,0.2223,"
        "41975560,0.7248,False,1,USD\n",
    )
    _write(
        sandbox,
        "config/watchlist.json",
        '{"watchlist":[{"ticker":"AAPL","sector":"Information Technology"}]}\n',
    )
    _write(sandbox, "theses/bull-2026-10-06.jsonl", "")
    _write(sandbox, "theses/bear-2026-10-06.jsonl", "")
    _limits(sandbox)

    tool = ComputePortfolioTool()
    result = json.loads(await tool.execute(tool.prepare({}, sandbox), sandbox))
    assert result["empty_book"] is True
    assert "records no holdings or cash" in result["note"]
    assert result["as_of"] == "2026-10-06"
    assert result["currency"] == "USD"
    assert result["total_value"] == 0
    assert result["positions"] == []

    checks = CheckLimitsTool()
    checked = json.loads(
        await checks.execute(checks.prepare({"date": "2026-10-06"}, sandbox), sandbox)
    )
    assert checked["items"] == []


def _history(sandbox: Sandbox, ticker: str, closes: dict[str, str]) -> None:
    rows = "".join(f"{day},0,0,0,{close},1\n" for day, close in closes.items())
    _write(sandbox, f"raw/prices/{ticker}.csv", "date,open,high,low,close,volume\n" + rows)


def _book_after_a_gap(sandbox: Sandbox) -> None:
    """Valued for 13 October, then nothing until 19 October."""
    _write(
        sandbox,
        "portfolio/positions.csv",
        "ticker,shares,cost_per_share,opened,sector,currency\n"
        "CASH,1000,,,Cash,USD\n"
        "MU,1,,,Technology,USD\n"
        "NOW,2,,,Technology,USD\n"
        "AVGO,1,,,Technology,USD\n",
    )
    days = ("2026-10-13", "2026-10-14", "2026-10-15", "2026-10-16", "2026-10-19")
    _history(
        sandbox,
        "MU",
        dict(zip(days, ("953.19", "914.13", "931.24", "878.84", "904.90"), strict=True)),
    )
    _history(
        sandbox,
        "NOW",
        dict(zip(days, ("138.61", "135.10", "140.02", "141.97", "145.36"), strict=True)),
    )
    # A holding bought after the last report has no close to compare with.
    _history(sandbox, "AVGO", {"2026-10-16": "328.75", "2026-10-19": "334.59"})
    _write(
        sandbox,
        "raw/prices/summary.csv",
        "ticker,date,close,prev_close,currency\n"
        "AVGO,2026-10-19,334.59,328.75,USD\n"
        "MU,2026-10-19,904.90,878.84,USD\n"
        "NOW,2026-10-19,145.36,141.97,USD\n",
    )
    _limits(sandbox)
    _write(
        sandbox,
        "portfolio/computed.json",
        json.dumps({"as_of": "2026-10-13", "total_value": 2565.00}),
    )


async def test_the_book_reports_what_changed_and_what_went_unreported_since_the_last_report(
    sandbox: Sandbox,
) -> None:
    """2026-10-20: AgentBase was closed for three mornings. The book now names
    the sessions that got no report, and how it moved since the last one."""
    _book_after_a_gap(sandbox)
    tool = ComputePortfolioTool()

    result = json.loads(await tool.execute(tool.prepare({}, sandbox), sandbox))

    assert result["as_of"] == "2026-10-19"
    assert result["since_previous"] == {
        "session": "2026-10-13",
        "skipped_sessions": ["2026-10-14", "2026-10-15", "2026-10-16"],
        "total_value": 2565.00,
        "value_change": -34.79,
        "value_change_pct": -1.3563,
        "price_change_pct": {"AVGO": None, "MU": -5.0661, "NOW": 4.8698},
    }
    saved = json.loads((sandbox.root / "portfolio/computed.json").read_text(encoding="utf-8"))
    assert saved["since_previous"] == result["since_previous"]

    # Valuing the same session again still compares with 13 October.
    again = json.loads(await tool.execute(tool.prepare({}, sandbox), sandbox))
    assert again["since_previous"] == result["since_previous"]


@pytest.mark.parametrize("previous", [None, "not json", '{"as_of": "someday"}', "[]"])
async def test_without_a_readable_earlier_report_there_is_nothing_to_compare(
    sandbox: Sandbox, previous: str | None
) -> None:
    _book_after_a_gap(sandbox)
    computed = sandbox.root / "portfolio/computed.json"
    if previous is None:
        computed.unlink()
    else:
        computed.write_text(previous, encoding="utf-8")
    tool = ComputePortfolioTool()

    result = json.loads(await tool.execute(tool.prepare({}, sandbox), sandbox))

    assert result["since_previous"] is None
    assert result["total_value"] == 2530.21
