"""Market-wide discovery and real-source failure handling, without live requests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import httpx2
import pytest

from agentbase.tools.base import ToolArgumentError
from agentbase.tools.builtin.market import MAX_MARKET_BYTES, ReadMarketTool
from agentbase.tools.sandbox import Sandbox, SandboxViolationError, UrlNotAllowedError

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

pytestmark = pytest.mark.anyio


@pytest.fixture
def sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Sandbox:
    import socket

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_a, **_k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("98.137.11.163", 0))],
    )
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "portfolio").mkdir()
    (root / "portfolio/positions.csv").write_text(
        "ticker,shares,cost_per_share,opened,sector,currency\n"
        "MSFT,1,0,2026-10-01,Technology,USD\nCASH,2500,1,2026-10-01,Cash,USD\n",
        encoding="utf-8",
    )
    (root / "config").mkdir()
    (root / "config/watchlist.json").write_text(
        json.dumps({"watchlist": [{"ticker": "MU", "name": "Micron", "sector": "Technology"}]}),
        encoding="utf-8",
    )
    return Sandbox(root)


def _clock() -> datetime:
    return datetime(2026, 10, 12, 21, 0, tzinfo=UTC)


def _feed(*items: tuple[str, str, str]) -> bytes:
    entries = "".join(
        f"<item><title>{title}</title><link>{url}</link><description>{summary}</description>"
        "<pubDate>Mon, 12 Oct 2026 20:00:00 +0000</pubDate></item>"
        for title, url, summary in items
    )
    return f"<rss><channel><title>Yahoo Finance</title>{entries}</channel></rss>".encode()


async def test_read_market_discovers_market_wide_candidates_and_preserves_holdings(
    sandbox: Sandbox,
) -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        params = dict(request.url.params)
        if "scrIds" in params:
            symbol = {"day_gainers": "GAIN", "day_losers": "LOSE", "most_actives": "MU"}[
                params["scrIds"]
            ]
            return httpx2.Response(
                200,
                json={
                    "finance": {
                        "result": [
                            {
                                "quotes": [
                                    {
                                        "symbol": symbol,
                                        "quoteType": "EQUITY",
                                        "region": "US",
                                        "currency": "USD",
                                        "regularMarketVolume": 100000,
                                        "regularMarketPrice": 50.2,
                                        "regularMarketChangePercent": 4.5,
                                        "regularMarketTime": int(_clock().timestamp()),
                                    }
                                ]
                            }
                        ]
                    }
                },
            )
        if "quotesCount" in params:
            symbol = params["q"]
            return httpx2.Response(
                200,
                json={
                    "quotes": [
                        {
                            "symbol": symbol,
                            "quoteType": "EQUITY",
                            "longname": "Microsoft Corporation" if symbol == "MSFT" else symbol,
                            "sector": "Technology",
                            "industry": "Software - Infrastructure",
                        }
                    ]
                },
            )
        if params["s"] == "^GSPC,^IXIC,^DJI":
            return httpx2.Response(
                200,
                content=_feed(
                    (
                        "Palantir (PLTR) wins contract",
                        "https://finance.yahoo.com/pltr",
                        "Contract was signed.",
                    ),
                    (
                        "Unknown (FAKE) reports",
                        "https://finance.yahoo.com/fake",
                        "An unknown issuer.",
                    ),
                ),
            )
        return httpx2.Response(
            200,
            content=_feed(
                (
                    "Microsoft reports revenue",
                    "https://finance.yahoo.com/msft",
                    "Microsoft Corporation reports revenue.",
                ),
                (
                    "Palantir (PLTR) wins contract",
                    "https://finance.yahoo.com/pltr",
                    "Contract was signed.",
                ),
            ),
        )

    # One headline hint receives an exact-symbol mismatch and is rejected.
    def exact_handler(request: httpx2.Request) -> httpx2.Response:
        if dict(request.url.params).get("q") == "FAKE":
            seen.append(request)
            return httpx2.Response(
                200, json={"quotes": [{"symbol": "FAKE2", "quoteType": "EQUITY"}]}
            )
        return handler(request)

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(exact_handler)) as client:
        tool = ReadMarketTool(client, _clock)
        prepared = tool.prepare({}, sandbox)
        assert prepared.payload["hosts"] == [
            "query1.finance.yahoo.com",
            "feeds.finance.yahoo.com",
        ]
        assert not (sandbox.root / "raw").exists()  # prepare has no writes.
        result = json.loads(await tool.execute(prepared, sandbox))

    assert result["symbols"] == ["GAIN", "LOSE", "MSFT", "MU", "PLTR"]
    by_symbol = {row["ticker"]: row for row in result["universe"]}
    assert by_symbol["MSFT"]["origins"] == ["holding"]
    assert by_symbol["MU"]["origins"] == ["watchlist", "most_actives"]
    assert by_symbol["PLTR"]["origins"] == ["headline"]
    assert by_symbol["GAIN"]["sector"] == "Technology"
    assert by_symbol["GAIN"]["industry"] == "Software - Infrastructure"
    assert result["written"] == [
        "raw/market/universe.json",
        "raw/market/screeners-2026-10-12.json",
        "raw/news-2026-10-12.jsonl",
    ]
    rows = [
        json.loads(line)
        for line in (sandbox.root / result["news_path"]).read_text().splitlines()
    ]
    assert len(rows) == 3  # Same headline appearing in two feeds is written once.
    microsoft = next(row for row in rows if row["title"].startswith("Microsoft"))
    assert microsoft["tickers"] == ["MSFT"]
    assert all(row["collected_from"] == "feeds.finance.yahoo.com" for row in rows)
    assert all(request.url.host == "98.137.11.163" for request in seen)
    assert all(request.headers["host"] in prepared.payload["hosts"] for request in seen)
    assert all(
        request.extensions["sni_hostname"] == request.headers["host"] for request in seen
    )
    assert all(request.headers["user-agent"].startswith("AgentBase/") for request in seen)


async def test_missing_sources_report_warnings_and_still_watch_holdings(
    sandbox: Sandbox,
) -> None:
    async with httpx2.AsyncClient(
        transport=httpx2.MockTransport(lambda _request: httpx2.Response(429))
    ) as client:
        tool = ReadMarketTool(client, _clock)
        result = json.loads(await tool.execute(tool.prepare({}, sandbox), sandbox))
    assert result["symbols"] == ["MSFT", "MU"]
    assert len(result["screeners"]) == 3
    assert all(row["status"] == "unavailable" for row in result["screeners"])
    assert result["news_count"] == 0
    assert any("No Yahoo headlines" in warning for warning in result["warnings"])
    assert all(row["quotes"] == [] for row in result["screeners"])
    assert (sandbox.root / result["news_path"]).read_text() == ""


async def test_news_matching_preserves_configured_company_name_and_aliases(
    sandbox: Sandbox,
) -> None:
    (sandbox.root / "config/watchlist.json").write_text(
        json.dumps(
            {
                "watchlist": [
                    {
                        "ticker": "MU",
                        "company_name": "Micron Technology, Inc.",
                        "aliases": ["Micron"],
                        "sector": "Technology",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.headers["host"] == "feeds.finance.yahoo.com":
            return httpx2.Response(
                200,
                content=_feed(
                    (
                        "Micron introduces a chip",
                        "https://finance.yahoo.com/chip",
                        "New product announced.",
                    ),
                    (
                        "Micronically unrelated story",
                        "https://finance.yahoo.com/other",
                        "Different word.",
                    ),
                ),
            )
        return httpx2.Response(429)

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as client:
        tool = ReadMarketTool(client, _clock)
        result = json.loads(await tool.execute(tool.prepare({}, sandbox), sandbox))
    micron = next(row for row in result["universe"] if row["ticker"] == "MU")
    assert micron["company_name"] == "Micron Technology, Inc."
    assert micron["aliases"] == ["Micron"]
    rows = [
        json.loads(line)
        for line in (sandbox.root / result["news_path"]).read_text().splitlines()
    ]
    assert rows[0]["tickers"] == ["MU"]
    assert rows[1]["tickers"] == []


async def test_invalid_holdings_do_not_hide_valid_watchlist_or_requested_symbols(
    sandbox: Sandbox,
) -> None:
    (sandbox.root / "portfolio/positions.csv").write_bytes(b"\xff")
    async with httpx2.AsyncClient(
        transport=httpx2.MockTransport(lambda _request: httpx2.Response(429))
    ) as client:
        tool = ReadMarketTool(client, _clock)
        result = json.loads(
            await tool.execute(tool.prepare({"symbols": ["ORCL"]}, sandbox), sandbox)
        )
    assert result["symbols"] == ["MU", "ORCL"]
    assert any("held stocks could not be read" in warning for warning in result["warnings"])


async def test_market_response_limit_is_enforced(sandbox: Sandbox) -> None:
    class Chunks(httpx2.AsyncByteStream):
        async def __aiter__(self) -> AsyncIterator[bytes]:
            yield b"x" * MAX_MARKET_BYTES
            yield b"x"

    async with httpx2.AsyncClient(
        transport=httpx2.MockTransport(lambda _request: httpx2.Response(200, stream=Chunks()))
    ) as client:
        tool = ReadMarketTool(client, _clock)
        result = json.loads(await tool.execute(tool.prepare({}, sandbox), sandbox))
    assert result["symbols"] == ["MSFT", "MU"]
    assert any("response limit" in warning for warning in result["warnings"])


def test_market_preparation_rejects_bad_tickers_limits_and_escaped_outputs(
    sandbox: Sandbox, tmp_path: Path
) -> None:
    tool = ReadMarketTool(clock=_clock)
    for arguments in (
        {"symbols": ["../MSFT"]},
        {"symbols": [2]},
        {"limit_per_list": True},
        {"limit_per_list": 11},
        {"symbols": ["MU"] * 51},
    ):
        with pytest.raises(ToolArgumentError):
            tool.prepare(arguments, sandbox)
    outside = tmp_path / "outside"
    outside.mkdir()
    (sandbox.root / "raw").symlink_to(outside, target_is_directory=True)
    with pytest.raises(SandboxViolationError):
        tool.prepare({}, sandbox)


def test_market_uses_configured_limit_with_explicit_argument_override(sandbox: Sandbox) -> None:
    path = sandbox.root / "config/sources.json"
    path.write_text(json.dumps({"market": {"limit_per_list": 3}}), encoding="utf-8")
    tool = ReadMarketTool(clock=_clock)
    prepared = tool.prepare({}, sandbox)
    assert prepared.payload["limit"] == 3
    assert all(
        dict(httpx2.URL(request["url"]).params)["count"] == "3"
        for request in prepared.payload["screeners"].values()
    )
    assert tool.prepare({"limit_per_list": 1}, sandbox).payload["limit"] == 1
    path.write_text(json.dumps({"market": {"limit_per_list": 11}}), encoding="utf-8")
    with pytest.raises(ToolArgumentError, match="between 1 and 10"):
        tool.prepare({}, sandbox)


def test_every_market_host_is_checked_before_approval(
    sandbox: Sandbox, monkeypatch: pytest.MonkeyPatch
) -> None:
    import socket

    def resolver(
        host: str, *_args: object, **_kwargs: object
    ) -> list[tuple[int, int, int, str, tuple[str, int]]]:
        address = "127.0.0.1" if host == "feeds.finance.yahoo.com" else "98.137.11.163"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 0))]

    monkeypatch.setattr(socket, "getaddrinfo", resolver)
    with pytest.raises(UrlNotAllowedError):
        ReadMarketTool(clock=_clock).prepare({}, sandbox)
