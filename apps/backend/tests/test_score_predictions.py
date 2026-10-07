"""Deterministic prediction scoring over thesis and recorded price files."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from agentbase.tools.base import ToolArgumentError, ToolExecutionError
from agentbase.tools.builtin.scoring import ScorePredictionsTool
from agentbase.tools.catalogue import RiskLevel
from agentbase.tools.sandbox import Sandbox

pytestmark = pytest.mark.anyio


@pytest.fixture
def sandbox(tmp_path: Path) -> Sandbox:
    root = tmp_path / "workspace"
    root.mkdir()
    return Sandbox(root)


def _write(sandbox: Sandbox, path: str, content: str) -> Path:
    target = sandbox.root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8", newline="")
    return target


def _prediction(
    pred_id: str,
    *,
    as_of: str,
    agent: str,
    horizon: int,
    direction: str,
    band: str,
    confidence: float,
) -> dict[str, Any]:
    return {
        "pred_id": pred_id,
        "as_of": as_of,
        "agent": agent,
        "ticker": "AAPL",
        "horizon_days": horizon,
        "direction": direction,
        "magnitude_band": band,
        "confidence": confidence,
        "thesis": "A falsifiable claim grounded in the recorded inputs.",
        "evidence_ids": ["news-1"],
        "invalidation": "A close through the stated invalidation level.",
        "base_rate_note": "The saved base rate for this horizon.",
    }


def _line(document: dict[str, Any]) -> str:
    return json.dumps(document, separators=(",", ":")) + "\n"


def _price_history(sandbox: Sandbox) -> None:
    _write(
        sandbox,
        "raw/prices/AAPL.csv",
        (
            "date,open,high,low,close,volume\n"
            "2026-09-01,100,101,99,100,1000\n"
            "2026-09-02,101,103,100,102,1000\n"
            "2026-09-03,100,101,98,99,1000\n"
            "2026-09-04,100,106,99,105,1000\n"
            "2026-09-07,105,106,104,105,1000\n"
            "2026-09-08,100,101,93,94,1000\n"
            "2026-09-09,100,111,99,110,1000\n"
        ),
    )


def _theses(sandbox: Sandbox) -> None:
    bull_one = _prediction(
        "00000000-0000-4000-8000-000000000001",
        as_of="2026-09-01T22:00:00Z",
        agent="bull",
        horizon=1,
        direction="up",
        band="1-3%",
        confidence=0.70,
    )
    unresolved = _prediction(
        "00000000-0000-4000-8000-000000000002",
        as_of="2026-09-01T22:00:00Z",
        agent="bull",
        horizon=7,
        direction="up",
        band="5%+",
        confidence=0.50,
    )
    malformed = _prediction(
        "00000000-0000-4000-8000-000000000003",
        as_of="2026-09-01T22:00:00Z",
        agent="bull",
        horizon=2,
        direction="up",
        band="1-3%",
        confidence=0.70,
    )
    _write(
        sandbox,
        "theses/bull-2026-09-01.jsonl",
        _line(bull_one) + _line(unresolved) + _line(malformed),
    )
    _write(
        sandbox,
        "theses/bear-2026-09-01.jsonl",
        _line(
            _prediction(
                "00000000-0000-4000-8000-000000000004",
                as_of="2026-09-01T22:00:00Z",
                agent="bear",
                horizon=3,
                direction="down",
                band="5%+",
                confidence=0.80,
            )
        ),
    )
    _write(
        sandbox,
        "theses/bear-2026-09-03.jsonl",
        _line(
            _prediction(
                "00000000-0000-4000-8000-000000000005",
                as_of="2026-09-03T12:00:00Z",
                agent="bear",
                horizon=1,
                direction="down",
                band="5%+",
                confidence=0.60,
            )
        ),
    )
    _write(
        sandbox,
        "theses/bull-2026-09-04.jsonl",
        _line(
            _prediction(
                "00000000-0000-4000-8000-000000000006",
                as_of="2026-09-04T12:00:00Z",
                agent="bull",
                horizon=1,
                direction="up",
                band="0-1%",
                confidence=0.90,
            )
        ),
    )
    _write(
        sandbox,
        "theses/bear-2026-09-07.jsonl",
        _line(
            _prediction(
                "00000000-0000-4000-8000-000000000007",
                as_of="2026-09-07T12:00:00Z",
                agent="bear",
                horizon=1,
                direction="down",
                band="5%+",
                confidence=0.60,
            )
        ),
    )


def _tool() -> ScorePredictionsTool:
    return ScorePredictionsTool(now=lambda: datetime(2026, 10, 1, 3, 4, 5, tzinfo=UTC))


async def test_score_predictions_appends_once_and_writes_hand_checked_outputs(
    sandbox: Sandbox,
) -> None:
    _price_history(sandbox)
    _theses(sandbox)
    tool = _tool()

    prepared = tool.prepare({"month": "2026-09"}, sandbox)
    assert prepared.summary == "score resolved predictions and write the 2026-09 scorecard"
    assert tool.risk is RiskLevel.MEDIUM
    assert not (sandbox.root / "scores/predictions.jsonl").exists()

    result = json.loads(await tool.execute(prepared, sandbox))

    assert result["month"] == "2026-09"
    assert result["appended"] == 5
    assert result["written"] == [
        "scores/predictions.jsonl",
        "scores/accuracy.csv",
        "scores/calibration.csv",
        "scores/scorecard-2026-09.json",
    ]
    assert result["already_scored"] == 0
    assert result["unresolved"] == 1
    assert result["malformed"] == 1
    assert result["malformed_lines"][0]["path"] == "theses/bull-2026-09-01.jsonl"
    assert result["malformed_lines"][0]["line"] == 3
    assert "horizon_days" in result["malformed_lines"][0]["error"]

    ledger_path = sandbox.root / "scores/predictions.jsonl"
    ledger = [json.loads(line) for line in ledger_path.read_text(encoding="utf-8").splitlines()]
    assert len(ledger) == 5
    first = next(row for row in ledger if row["pred_id"].endswith("0001"))
    assert first["entry_date"] == "2026-09-01"
    assert first["entry_close"] == 100
    assert first["exit_date"] == "2026-09-02"
    assert first["exit_close"] == 102
    assert first["return_pct"] == 2
    assert first["hit"] is True
    assert first["band_hit"] is True
    assert first["brier"] == 0.09
    assert first["scored_at"] == "2026-10-01T03:04:05Z"

    unchanged = next(row for row in ledger if row["pred_id"].endswith("0006"))
    assert unchanged["return_pct"] == 0
    assert unchanged["hit"] is False
    assert unchanged["band_hit"] is False
    assert unchanged["brier"] == 0.81

    wrong_direction = next(row for row in ledger if row["pred_id"].endswith("0004"))
    assert wrong_direction["return_pct"] == 5
    assert wrong_direction["hit"] is False
    assert wrong_direction["band_hit"] is False

    assert (sandbox.root / "scores/accuracy.csv").read_text(encoding="utf-8").splitlines() == [
        "agent,horizon_days,predictions,hits,hit_rate,mean_brier,constant_0_5_brier,windows_up_rate",
        "bull,1,2,1,0.5000,0.4500,0.2500,0.5000",
        "bear,1,2,1,0.5000,0.2600,0.2500,0.5000",
        "bear,3,1,0,0.0000,0.6400,0.2500,1.0000",
    ]
    assert (sandbox.root / "scores/calibration.csv").read_text(
        encoding="utf-8"
    ).splitlines() == [
        "agent,confidence_bucket,predictions,hits,mean_confidence,observed_hit_rate,confidence_minus_observed",
        "bull,0.70,1,1,0.7000,1.0000,-0.3000",
        "bull,0.90,1,0,0.9000,0.0000,0.9000",
        "bear,0.60,2,1,0.6000,0.5000,0.1000",
        "bear,0.80,1,0,0.8000,0.0000,0.8000",
    ]

    scorecard = json.loads(
        (sandbox.root / "scores/scorecard-2026-09.json").read_text(encoding="utf-8")
    )
    assert scorecard["month"] == "2026-09"
    assert scorecard["resolved_predictions"] == 5
    assert scorecard["unresolved_predictions"] == 1
    assert scorecard["malformed_thesis_lines"] == 1
    assert scorecard["baselines"] == {
        "constant_0_5_brier": 0.25,
        "windows_up_rate": 0.6,
    }
    assert scorecard["accuracy"][0] == {
        "agent": "bull",
        "horizon_days": 1,
        "predictions": 2,
        "hits": 1,
        "hit_rate": 0.5,
        "mean_brier": 0.45,
        "constant_0_5_brier": 0.25,
        "windows_up_rate": 0.5,
    }

    before = ledger_path.read_bytes()
    second = json.loads(await tool.execute(prepared, sandbox))
    assert second["appended"] == 0
    # Nothing new resolved, so the append-only ledger was not touched.
    assert "scores/predictions.jsonl" not in second["written"]
    assert second["already_scored"] == 5
    assert ledger_path.read_bytes() == before


async def test_score_predictions_uses_utc_date_and_trading_sessions(
    sandbox: Sandbox,
) -> None:
    _price_history(sandbox)
    weekend = _prediction(
        "00000000-0000-4000-8000-000000000008",
        as_of="2026-09-06T23:30:00-04:00",
        agent="bull",
        horizon=1,
        direction="up",
        band="5%+",
        confidence=0.55,
    )
    _write(sandbox, "theses/bull-2026-09-07.jsonl", _line(weekend))

    await _tool().execute(_tool().prepare({"month": "2026-09"}, sandbox), sandbox)

    scored = json.loads((sandbox.root / "scores/predictions.jsonl").read_text(encoding="utf-8"))
    assert scored["entry_date"] == "2026-09-07"
    assert scored["exit_date"] == "2026-09-08"


@pytest.mark.parametrize("month", [None, 202609, "2026-9", "2026-13", "0000-01"])
def test_score_predictions_requires_a_real_month(sandbox: Sandbox, month: object) -> None:
    arguments = {} if month is None else {"month": month}
    with pytest.raises(ToolArgumentError, match="month"):
        _tool().prepare(arguments, sandbox)


async def test_score_predictions_uses_half_open_magnitude_edges(
    sandbox: Sandbox,
) -> None:
    closes = ["100", "101", "102", "103", "104", "105", "104", "100.999"]
    rows = ["date,open,high,low,close,volume"]
    for day, close in enumerate(closes, start=1):
        rows.append(f"2026-09-{day:02d},{close},{close},{close},{close},1000")
    _write(sandbox, "raw/prices/AAPL.csv", "\n".join(rows) + "\n")
    bands = ((1, "1-3%"), (3, "3-5%"), (5, "5%+"), (7, "0-1%"))
    theses = "".join(
        _line(
            _prediction(
                f"00000000-0000-4000-8000-{horizon:012d}",
                as_of="2026-09-01T12:00:00Z",
                agent="bull",
                horizon=horizon,
                direction="up",
                band=band,
                confidence=0.50,
            )
        )
        for horizon, band in bands
    )
    _write(sandbox, "theses/bull-2026-09-01.jsonl", theses)

    await _tool().execute(_tool().prepare({"month": "2026-09"}, sandbox), sandbox)

    ledger = [
        json.loads(line)
        for line in (sandbox.root / "scores/predictions.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert [(row["return_pct"], row["magnitude_band"], row["band_hit"]) for row in ledger] == [
        (1, "1-3%", True),
        (3, "3-5%", True),
        (5, "5%+", True),
        (0.999, "0-1%", True),
    ]


async def test_monthly_scorecard_uses_utc_as_of_while_stable_csv_uses_all_months(
    sandbox: Sandbox,
) -> None:
    _write(
        sandbox,
        "raw/prices/AAPL.csv",
        (
            "date,open,high,low,close,volume\n"
            "2026-08-31,100,100,100,100,1000\n"
            "2026-09-01,102,102,102,102,1000\n"
            "2026-09-02,101,101,101,101,1000\n"
        ),
    )
    _write(
        sandbox,
        "theses/bull-2026-08-31.jsonl",
        _line(
            _prediction(
                "00000000-0000-4000-8000-000000000009",
                as_of="2026-08-31T23:00:00Z",
                agent="bull",
                horizon=1,
                direction="up",
                band="1-3%",
                confidence=0.55,
            )
        ),
    )
    _write(
        sandbox,
        "theses/bear-2026-09-01.jsonl",
        _line(
            _prediction(
                "00000000-0000-4000-8000-000000000010",
                as_of="2026-09-01T23:00:00Z",
                agent="bear",
                horizon=1,
                direction="down",
                band="0-1%",
                confidence=0.55,
            )
        ),
    )

    await _tool().execute(_tool().prepare({"month": "2026-09"}, sandbox), sandbox)

    scorecard = json.loads(
        (sandbox.root / "scores/scorecard-2026-09.json").read_text(encoding="utf-8")
    )
    assert scorecard["resolved_predictions"] == 1
    accuracy = (sandbox.root / "scores/accuracy.csv").read_text(encoding="utf-8")
    assert "bull,1,1,1" in accuracy
    assert "bear,1,1,1" in accuracy


async def test_score_predictions_refuses_a_corrupt_existing_ledger(
    sandbox: Sandbox,
) -> None:
    _price_history(sandbox)
    _theses(sandbox)
    _write(sandbox, "scores/predictions.jsonl", "not json\n")
    tool = _tool()

    with pytest.raises(ToolExecutionError, match=r"predictions\.jsonl.*line 1"):
        await tool.execute(tool.prepare({"month": "2026-09"}, sandbox), sandbox)
