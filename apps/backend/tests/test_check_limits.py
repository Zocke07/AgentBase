"""The deterministic hard-rule checker over portfolio and thesis fixtures."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentbase.tools.base import ToolArgumentError, ToolExecutionError
from agentbase.tools.builtin.limits import CheckLimitsTool
from agentbase.tools.catalogue import RiskLevel
from agentbase.tools.sandbox import Sandbox

pytestmark = pytest.mark.anyio


@pytest.fixture
def sandbox(tmp_path: Path) -> Sandbox:
    root = tmp_path / "workspace"
    root.mkdir()
    return Sandbox(root)


def _write(sandbox: Sandbox, path: str, content: str) -> None:
    target = sandbox.root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8", newline="")


def _inputs(sandbox: Sandbox, *, day_change_pct: int | float = -2.25) -> None:
    _write(
        sandbox,
        "portfolio/computed.json",
        json.dumps(
            {
                "as_of": "2026-09-30",
                "day_change_pct": day_change_pct,
                "positions": [
                    {"ticker": "AAPL", "weight_pct": 12, "sector": "Technology"},
                    {"ticker": "JNJ", "weight_pct": 25, "sector": "Healthcare"},
                ],
                "concentration": {"sector_weights": {"Healthcare": 25, "Technology": 28}},
            }
        )
        + "\n",
    )
    _write(
        sandbox,
        "config/limits.json",
        '{"max_position_pct":10,"max_sector_pct":30,"max_daily_loss_pct":3}\n',
    )
    _write(
        sandbox,
        "config/watchlist.json",
        json.dumps(
            {
                "watchlist": [
                    {"ticker": "AAPL", "sector": "Technology"},
                    {"ticker": "MSFT", "sector": "Technology"},
                ]
            }
        )
        + "\n",
    )
    _write(
        sandbox,
        "theses/bull-2026-09-30.jsonl",
        '{"pred_id":"bull-aapl","ticker":"AAPL"}\n{"pred_id":"bull-msft","ticker":"MSFT"}\n',
    )
    _write(
        sandbox,
        "theses/bear-2026-09-30.jsonl",
        '{"pred_id":"bear-msft","ticker":"MSFT"}\n',
    )


async def test_sourced_discovery_sector_can_be_checked_without_rewriting_watchlist(
    sandbox: Sandbox,
) -> None:
    _inputs(sandbox)
    _write(
        sandbox,
        "raw/market/universe.json",
        json.dumps(
            {
                "universe": [
                    {"ticker": "CRWV", "sector": "Technology", "origins": ["day_gainers"]},
                    {"ticker": "AAPL", "sector": "Untrusted conflicting sector"},
                ]
            }
        ),
    )
    _write(sandbox, "theses/bull-2026-09-30.jsonl", '{"ticker":"CRWV"}\n')
    tool = CheckLimitsTool()
    result = json.loads(
        await tool.execute(tool.prepare({"date": "2026-09-30"}, sandbox), sandbox)
    )
    rows = {row["ticker"]: row for row in result["items"]}
    assert rows["CRWV"]["sector"] == "Technology"
    assert rows["CRWV"]["checks"][1]["headroom_pct"] == 2
    assert rows["AAPL"]["sector"] == "Technology"
    assert "CRWV" not in (sandbox.root / "config/watchlist.json").read_text(encoding="utf-8")


async def test_check_limits_writes_exact_checks_and_headroom(sandbox: Sandbox) -> None:
    _inputs(sandbox)
    tool = CheckLimitsTool()

    prepared = tool.prepare({"date": "2026-09-30"}, sandbox)
    assert prepared.summary == "check portfolio and thesis limits for 2026-09-30"
    assert tool.risk is RiskLevel.MEDIUM
    assert not (sandbox.root / "risk/rule-checks-2026-09-30.json").exists()

    result = json.loads(await tool.execute(prepared, sandbox))

    # Reported for the run view, never written into the checks file.
    assert result.pop("written") == ["risk/rule-checks-2026-09-30.json"]
    assert result == {
        "date": "2026-09-30",
        "portfolio_as_of": "2026-09-30",
        "limits": {
            "max_position_pct": 10,
            "max_sector_pct": 30,
            "max_daily_loss_pct": 3,
        },
        "items": [
            {
                "ticker": "AAPL",
                "sector": "Technology",
                "held": True,
                "sources": ["portfolio", "bull"],
                "checks": [
                    {
                        "rule": "max_position_pct",
                        "status": "FAIL",
                        "value": 12,
                        "threshold": 10,
                        "headroom_pct": -2,
                    },
                    {
                        "rule": "max_sector_pct",
                        "status": "PASS",
                        "value": 28,
                        "threshold": 30,
                        "headroom_pct": 2,
                    },
                    {
                        "rule": "max_daily_loss_pct",
                        "status": "PASS",
                        "value": 2.25,
                        "threshold": 3,
                        "headroom_pct": 0.75,
                    },
                ],
            },
            {
                "ticker": "JNJ",
                "sector": "Healthcare",
                "held": True,
                "sources": ["portfolio"],
                "checks": [
                    {
                        "rule": "max_position_pct",
                        "status": "FAIL",
                        "value": 25,
                        "threshold": 10,
                        "headroom_pct": -15,
                    },
                    {
                        "rule": "max_sector_pct",
                        "status": "PASS",
                        "value": 25,
                        "threshold": 30,
                        "headroom_pct": 5,
                    },
                    {
                        "rule": "max_daily_loss_pct",
                        "status": "PASS",
                        "value": 2.25,
                        "threshold": 3,
                        "headroom_pct": 0.75,
                    },
                ],
            },
            {
                "ticker": "MSFT",
                "sector": "Technology",
                "held": False,
                "sources": ["bull", "bear"],
                "checks": [
                    {
                        "rule": "max_position_pct",
                        "status": "PASS",
                        "value": 0,
                        "threshold": 10,
                        "headroom_pct": 10,
                    },
                    {
                        "rule": "max_sector_pct",
                        "status": "PASS",
                        "value": 28,
                        "threshold": 30,
                        "headroom_pct": 2,
                    },
                    {
                        "rule": "max_daily_loss_pct",
                        "status": "PASS",
                        "value": 2.25,
                        "threshold": 3,
                        "headroom_pct": 0.75,
                    },
                ],
            },
        ],
    }
    assert (
        json.loads(
            (sandbox.root / "risk/rule-checks-2026-09-30.json").read_text(encoding="utf-8")
        )
        == result
    )


async def test_check_limits_uses_loss_magnitude_and_marks_every_item_failed(
    sandbox: Sandbox,
) -> None:
    _inputs(sandbox, day_change_pct=-4.125)
    tool = CheckLimitsTool()

    result = json.loads(
        await tool.execute(tool.prepare({"date": "2026-09-30"}, sandbox), sandbox)
    )

    daily = [
        check
        for item in result["items"]
        for check in item["checks"]
        if check["rule"] == "max_daily_loss_pct"
    ]
    assert (
        daily
        == [
            {
                "rule": "max_daily_loss_pct",
                "status": "FAIL",
                "value": 4.125,
                "threshold": 3,
                "headroom_pct": -1.125,
            }
        ]
        * 3
    )


@pytest.mark.parametrize(
    ("watchlist", "message"),
    (
        (
            '{"watchlist":[{"ticker":"AAPL","sector":"Technology"},{"ticker":"MSFT"}]}',
            "needs a non-empty sector for MSFT",
        ),
        (
            '{"watchlist":[{"ticker":"AAPL","sector":"Technology"}]}',
            "thesis ticker MSFT is not in config/watchlist.json",
        ),
        (
            '{"watchlist":[{"ticker":"AAPL","sector":"Consumer"},'
            '{"ticker":"MSFT","sector":"Technology"}]}',
            "AAPL.*Consumer.*Technology",
        ),
    ),
)
async def test_check_limits_requires_configured_consistent_sectors(
    sandbox: Sandbox,
    watchlist: str,
    message: str,
) -> None:
    _inputs(sandbox)
    _write(sandbox, "config/watchlist.json", watchlist)
    tool = CheckLimitsTool()

    with pytest.raises(ToolExecutionError, match=message):
        await tool.execute(tool.prepare({"date": "2026-09-30"}, sandbox), sandbox)

    assert not (sandbox.root / "risk/rule-checks-2026-09-30.json").exists()


async def test_check_limits_names_missing_and_malformed_thesis_inputs(
    sandbox: Sandbox,
) -> None:
    _inputs(sandbox)
    bull = sandbox.root / "theses/bull-2026-09-30.jsonl"
    bull.unlink()
    tool = CheckLimitsTool()

    with pytest.raises(ToolExecutionError, match=r"bull-2026-09-30\.jsonl.*missing"):
        await tool.execute(tool.prepare({"date": "2026-09-30"}, sandbox), sandbox)

    _write(sandbox, "theses/bull-2026-09-30.jsonl", "not json\n")
    with pytest.raises(ToolExecutionError, match=r"bull-2026-09-30\.jsonl line 1"):
        await tool.execute(tool.prepare({"date": "2026-09-30"}, sandbox), sandbox)


def test_check_limits_validates_and_resolves_its_date(sandbox: Sandbox) -> None:
    tool = CheckLimitsTool()

    with pytest.raises(ToolArgumentError, match="YYYY-MM-DD"):
        tool.prepare({"date": "30 September 2026"}, sandbox)
    with pytest.raises(ToolArgumentError, match="requires a 'date'"):
        tool.prepare({}, sandbox)

    prepared = tool.prepare({"date": "2026-09-30"}, sandbox)
    assert prepared.payload["output_path"] == (
        sandbox.root / "risk/rule-checks-2026-09-30.json"
    )


async def test_held_stock_does_not_need_to_be_repeated_in_the_watchlist(
    sandbox: Sandbox,
) -> None:
    _inputs(sandbox)
    _write(sandbox, "theses/bull-2026-09-30.jsonl", '{"ticker":"JNJ"}\n')
    _write(
        sandbox, "raw/market/universe.json", '{"universe":[{"ticker":"JNJ","sector":"Other"}]}'
    )
    tool = CheckLimitsTool()
    result = json.loads(
        await tool.execute(tool.prepare({"date": "2026-09-30"}, sandbox), sandbox)
    )
    rows = {row["ticker"]: row for row in result["items"]}
    assert rows["JNJ"]["sector"] == "Healthcare"
    assert rows["JNJ"]["sources"] == ["portfolio", "bull"]
