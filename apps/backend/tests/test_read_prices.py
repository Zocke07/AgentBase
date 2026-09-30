"""The deterministic Yahoo chart reader, entirely against recorded responses."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import httpx2
import pytest

from agentbase.tools.base import ToolArgumentError
from agentbase.tools.builtin.prices import MAX_PRICE_BYTES, ReadPricesTool
from agentbase.tools.catalogue import RiskLevel
from agentbase.tools.sandbox import Sandbox

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

pytestmark = pytest.mark.anyio

_FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def sandbox(tmp_path: Path) -> Sandbox:
    root = tmp_path / "workspace"
    root.mkdir()
    return Sandbox(root)


def _resolver(monkeypatch: pytest.MonkeyPatch) -> None:
    import socket

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_a, **_k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("98.137.11.163", 0))],
    )


def _recorded(name: str) -> bytes:
    return (_FIXTURES / name).read_bytes()


def _client() -> tuple[httpx2.AsyncClient, list[httpx2.Request]]:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        symbol = request.url.path.split("/")[-1]
        fixtures = {
            "AAPL": "yahoo_aapl_1y.json",
            "2330.TW": "yahoo_2330_tw_1y.json",
        }
        if symbol not in fixtures:
            return httpx2.Response(404, text="not found")
        return httpx2.Response(200, content=_recorded(fixtures[symbol]))

    return httpx2.AsyncClient(transport=httpx2.MockTransport(handler)), seen


async def test_read_prices_writes_bounded_history_movers_and_stable_summary(
    sandbox: Sandbox, monkeypatch: pytest.MonkeyPatch
) -> None:
    _resolver(monkeypatch)
    client, seen = _client()
    tool = ReadPricesTool(client)

    prepared = tool.prepare({"symbols": ["aapl", "2330.tw", "AAPL"]}, sandbox)
    assert prepared.payload["host"] == "query1.finance.yahoo.com"
    assert prepared.summary == "read one year of daily prices for AAPL and 2330.TW"
    assert tool.risk is RiskLevel.MEDIUM

    result = json.loads(await tool.execute(prepared, sandbox))
    assert result["as_of"] == "2026-09-30"
    assert result["new_session"] is True
    assert result["failures"] == []
    assert [row["ticker"] for row in result["summary"]] == ["2330.TW", "AAPL"]
    assert result["movers_path"] == "raw/movers-2026-09-30.json"

    aapl = (sandbox.root / "raw/prices/AAPL.csv").read_text(encoding="utf-8").splitlines()
    assert len(aapl) == 252
    assert aapl[0] == "date,open,high,low,close,volume"
    assert aapl[-1] == "2026-09-29,336.97,337.09,328.70,329.40,38427200"

    summary = (sandbox.root / "raw/prices/summary.csv").read_text(encoding="utf-8").splitlines()
    assert summary[0].startswith("ticker,date,open,high,low,close,volume,prev_close")
    assert len(summary) == 3

    movers = json.loads(
        (sandbox.root / "raw/movers-2026-09-30.json").read_text(encoding="utf-8")
    )
    assert [row["ticker"] for row in movers] == ["2330.TW", "AAPL"]
    assert movers[0]["rank"] == 1 and movers[1]["rank"] == 2
    assert all(row["source"] == "query1.finance.yahoo.com" for row in movers)
    assert all(row["microcap"] is False for row in movers)
    assert all("change_pct" in row and "rel_volume" in row for row in movers)

    assert len(seen) == 2
    assert all(request.url.host == "98.137.11.163" for request in seen)
    assert all(request.headers["host"] == "query1.finance.yahoo.com" for request in seen)
    assert all(
        request.extensions["sni_hostname"] == "query1.finance.yahoo.com" for request in seen
    )
    assert all(
        dict(request.url.params) == {"range": "1y", "interval": "1d"} for request in seen
    )

    second = json.loads(await tool.execute(prepared, sandbox))
    assert second["new_session"] is False
    await client.aclose()


async def test_read_prices_reports_one_symbol_failure_and_keeps_the_others(
    sandbox: Sandbox, monkeypatch: pytest.MonkeyPatch
) -> None:
    _resolver(monkeypatch)
    client, _ = _client()
    tool = ReadPricesTool(client)

    result = json.loads(
        await tool.execute(tool.prepare({"symbols": ["AAPL", "MISSING"]}, sandbox), sandbox)
    )

    assert [row["ticker"] for row in result["summary"]] == ["AAPL"]
    assert result["failures"] == [{"ticker": "MISSING", "error": "returned HTTP 404"}]
    assert (sandbox.root / "raw/prices/AAPL.csv").exists()
    assert not (sandbox.root / "raw/prices/MISSING.csv").exists()
    await client.aclose()


def test_read_prices_validates_and_bounds_its_symbols(sandbox: Sandbox) -> None:
    tool = ReadPricesTool()

    cases: tuple[dict[str, object], ...] = (
        {},
        {"symbols": []},
        {"symbols": ["AAPL"] * 51},
        {"symbols": ["../AAPL"]},
        {"symbols": [1]},
    )
    for arguments in cases:
        with pytest.raises(ToolArgumentError):
            tool.prepare(arguments, sandbox)


async def test_read_prices_enforces_the_per_symbol_response_limit(
    sandbox: Sandbox, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Chunks(httpx2.AsyncByteStream):
        async def __aiter__(self) -> AsyncIterator[bytes]:
            yield b"x" * MAX_PRICE_BYTES
            yield b"x"

    _resolver(monkeypatch)
    client = httpx2.AsyncClient(
        transport=httpx2.MockTransport(lambda _request: httpx2.Response(200, stream=Chunks()))
    )
    tool = ReadPricesTool(client)

    result = json.loads(
        await tool.execute(tool.prepare({"symbols": ["AAPL"]}, sandbox), sandbox)
    )

    assert result["summary"] == []
    assert "response limit" in result["failures"][0]["error"]
    assert not (sandbox.root / "raw/prices/AAPL.csv").exists()
    await client.aclose()
