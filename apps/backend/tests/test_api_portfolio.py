"""Personal-data forms save the exact inputs consumed by investment tools."""

from __future__ import annotations

import asyncio
import json
import shutil
from typing import TYPE_CHECKING, Any

import pytest
from fastapi.testclient import TestClient

from agentbase.main import create_app
from agentbase.store.spaces import DEFAULT_SPACE_ID
from agentbase.tools.builtin.portfolio import ComputePortfolioTool
from agentbase.tools.sandbox import Sandbox

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from agentbase.config import AppPaths
    from agentbase.secrets import SecretStore

URL = f"/spaces/{DEFAULT_SPACE_ID}/portfolio"


@pytest.fixture
def client(app_paths: AppPaths, secrets: SecretStore) -> Iterator[TestClient]:
    with TestClient(create_app(app_paths, secrets=secrets)) as opened:
        yield opened


def body(client: TestClient) -> dict[str, Any]:
    loaded = client.get(URL)
    assert loaded.status_code == 200, loaded.text
    result: dict[str, Any] = loaded.json()
    result["portfolio"].update(
        {
            "cash": "2500.125",
            "holdings": [
                {
                    "ticker": "mu",
                    "shares": "1.5",
                    "cost_per_share": None,
                    "opened": None,
                    "sector": "Technology",
                    "company_name": "Micron",
                    "industry": "Semiconductors",
                    "exchange": "US",
                }
            ],
        }
    )
    return result


def test_missing_files_are_an_empty_book_and_get_never_writes(
    client: TestClient, app_paths: AppPaths
) -> None:
    result = client.get(URL)
    assert result.status_code == 200, result.text
    assert result.json()["portfolio"]["holdings"] == []
    assert result.json()["portfolio"]["cash"] == "0"
    assert not (app_paths.spaces_dir / DEFAULT_SPACE_ID / "portfolio/positions.csv").exists()


def test_save_roundtrips_precise_inputs_and_the_real_portfolio_tool_reads_them(
    client: TestClient, app_paths: AppPaths
) -> None:
    saved = client.put(URL, json=body(client))
    assert saved.status_code == 200, saved.text
    assert saved.json() == client.get(URL).json()
    assert saved.json()["portfolio"]["holdings"][0]["ticker"] == "MU"
    assert saved.json()["portfolio"]["watchlist"] == []
    folder = app_paths.spaces_dir / DEFAULT_SPACE_ID
    positions = (folder / "portfolio/positions.csv").read_text()
    assert "2500.125" in positions and "MU,1.5,,,Technology,USD" in positions
    prices = folder / "raw/prices/summary.csv"
    prices.parent.mkdir(parents=True)
    prices.write_text("ticker,date,close,prev_close,currency\nMU,2026-10-12,100,90,USD\n")
    tool = ComputePortfolioTool()
    result = json.loads(
        asyncio.run(tool.execute(tool.prepare({}, Sandbox(folder)), Sandbox(folder)))
    )
    assert result["positions"][0]["value"] == 150
    assert result["positions"][0]["unrealised_pct"] is None


def test_stale_window_cannot_overwrite_newer_data(client: TestClient) -> None:
    stale = body(client)
    assert client.put(URL, json=stale).status_code == 200
    stale["portfolio"]["cash"] = "9000"
    result = client.put(URL, json=stale)
    assert result.status_code == 409
    assert client.get(URL).json()["portfolio"]["cash"] == "2500.125"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("shares", "0"),
        ("shares", "NaN"),
        ("cost_per_share", "0"),
        ("opened", "2026-02-30"),
        ("sector", ""),
        ("ticker", "../outside"),
    ],
)
def test_invalid_holding_never_changes_files(
    client: TestClient, app_paths: AppPaths, field: str, value: str
) -> None:
    data = body(client)
    data["portfolio"]["holdings"][0][field] = value
    assert client.put(URL, json=data).status_code == 422
    assert not (app_paths.spaces_dir / DEFAULT_SPACE_ID / "portfolio/positions.csv").exists()


def test_preserves_aliases_extra_json_keys_and_extra_csv_columns(
    client: TestClient, app_paths: AppPaths
) -> None:
    folder = app_paths.spaces_dir / DEFAULT_SPACE_ID
    (folder / "config").mkdir()
    (folder / "portfolio").mkdir()
    (folder / "portfolio/positions.csv").write_text(
        "ticker,shares,cost_per_share,opened,sector,currency,notes\nMU,1,,,Technology,USD,my note\nCASH,0,,,Cash,USD,\n"
    )
    (folder / "config/watchlist.json").write_text(
        json.dumps(
            {
                "discovery": True,
                "watchlist": [
                    {
                        "ticker": "MU",
                        "sector": "Technology",
                        "aliases": ["Micron Technology"],
                        "custom": 7,
                    }
                ],
            }
        )
    )
    (folder / "config/limits.json").write_text(
        '{"max_position_pct":10,"max_sector_pct":70,"max_daily_loss_pct":3,"custom":"keep"}'
    )
    assert client.put(URL, json=body(client)).status_code == 200
    document = json.loads((folder / "config/watchlist.json").read_text())
    assert document["discovery"] is True
    assert document["watchlist"][0]["aliases"] == ["Micron Technology"]
    assert document["watchlist"][0]["custom"] == 7
    assert json.loads((folder / "config/limits.json").read_text())["custom"] == "keep"
    assert "my note" in (folder / "portfolio/positions.csv").read_text()


def test_bad_existing_files_are_reported_without_replacement(
    client: TestClient, app_paths: AppPaths
) -> None:
    folder = app_paths.spaces_dir / DEFAULT_SPACE_ID / "config"
    folder.mkdir()
    source = folder / "watchlist.json"
    source.write_text('{"watchlist":broken}')
    assert client.get(URL).status_code == 422
    assert source.read_text() == '{"watchlist":broken}'


def test_symlink_cannot_write_outside_the_space(
    client: TestClient, app_paths: AppPaths, tmp_path: Path
) -> None:
    folder = app_paths.spaces_dir / DEFAULT_SPACE_ID
    outside = tmp_path / "outside"
    outside.mkdir()
    (folder / "config").symlink_to(outside, target_is_directory=True)
    assert client.get(URL).status_code == 400
    assert list(outside.iterdir()) == []


def test_pending_run_prevents_changes(client: TestClient) -> None:
    data = body(client)
    store = client.app.state.store  # type: ignore[attr-defined]
    asyncio.run(store.create_run(goal="Existing run", origin="ui", space_id=DEFAULT_SPACE_ID))
    assert client.put(URL, json=data).status_code == 409


def test_failed_second_write_restores_all_original_files(
    client: TestClient, app_paths: AppPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agentbase.store import portfolio as module

    assert client.put(URL, json=body(client)).status_code == 200
    folder = app_paths.spaces_dir / DEFAULT_SPACE_ID
    names = ("portfolio/positions.csv", "config/watchlist.json", "config/limits.json")
    original = {name: (folder / name).read_bytes() for name in names}
    data = body(client)
    data["portfolio"]["cash"] = "12345"
    replace = module._replace

    def fail_watchlist(path: Path, content: bytes) -> None:
        if path.name == "watchlist.json":
            raise PermissionError("File is open")
        replace(path, content)

    monkeypatch.setattr(module, "_replace", fail_watchlist)

    # Restoration must not truncate a canonical file before copying bytes:
    # a full disk could fail that copy too. Prewritten originals are renamed.
    def no_copy(*_args: Any, **_kwargs: Any) -> None:
        raise OSError("Disk cannot accept copied bytes")

    monkeypatch.setattr(shutil, "copyfile", no_copy)
    assert client.put(URL, json=data).status_code == 500
    assert {name: (folder / name).read_bytes() for name in names} == original
    assert list((folder / ".agentbase/backups").rglob("positions.csv"))


@pytest.mark.parametrize("value", ["0.00001", "10.12345678901234567890123456789"])
def test_limit_precision_survives_save_reload_and_future_saves(
    client: TestClient, value: str
) -> None:
    data = body(client)
    data["portfolio"]["limits"]["max_position_pct"] = value
    saved = client.put(URL, json=data)
    assert saved.status_code == 200, saved.text
    loaded = client.get(URL)
    assert loaded.status_code == 200, loaded.text
    assert loaded.json()["portfolio"]["limits"]["max_position_pct"] == value
    assert client.put(URL, json=loaded.json()).status_code == 200


@pytest.mark.parametrize(
    "kind", ["duplicates", "currency", "negative_cash", "limit", "incomplete"]
)
def test_invalid_portfolio_state_is_not_saved(client: TestClient, kind: str) -> None:
    data = body(client)
    if kind == "duplicates":
        data["portfolio"]["watchlist"] = [{"ticker": "MU", "sector": "Technology"}]
    elif kind == "currency":
        data["portfolio"]["currency"] = "FAKE"
    elif kind == "negative_cash":
        data["portfolio"]["cash"] = "-1"
    elif kind == "limit":
        data["portfolio"]["limits"]["max_sector_pct"] = "101"
    else:
        del data["portfolio"]["holdings"]
    assert client.put(URL, json=data).status_code == 422


def test_other_space_inputs_and_related_sources_are_unchanged(
    client: TestClient, app_paths: AppPaths
) -> None:
    other = client.post("/spaces", json={"name": "Other", "seed": "empty"}).json()["id"]
    # Personal stock data is the default space's alone (2026-10-13).
    assert client.get(f"/spaces/{other}/portfolio").status_code == 404
    source = app_paths.spaces_dir / DEFAULT_SPACE_ID / "config/sources.json"
    source.parent.mkdir(parents=True)
    source.write_text('{"custom":"source"}')
    assert client.put(URL, json=body(client)).status_code == 200
    assert not (app_paths.spaces_dir / other / "portfolio").exists()
    assert not (app_paths.spaces_dir / other / "config").exists()
    assert source.read_text() == '{"custom":"source"}'
    assert client.get("/spaces/nonexistent/portfolio").status_code == 404


def test_mixed_existing_currencies_are_reported(
    client: TestClient, app_paths: AppPaths
) -> None:
    folder = app_paths.spaces_dir / DEFAULT_SPACE_ID / "portfolio"
    folder.mkdir()
    (folder / "positions.csv").write_text(
        "ticker,shares,cost_per_share,opened,sector,currency\nMU,1,,,Technology,USD\nCASH,1000,,,Cash,TWD\n"
    )
    response = client.get(URL)
    assert response.status_code == 422
    assert "more than one currency" in response.text
