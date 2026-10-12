"""The market watch over HTTP (Phase 18): alerts, seen, status and switch."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import anyio
import pytest
from fastapi.testclient import TestClient

from agentbase.main import create_app
from agentbase.orchestrator.monitor import MONITOR_PATH
from agentbase.secrets import SecretStore
from agentbase.store.alerts import AlertStore, NewAlert
from agentbase.store.spaces import DEFAULT_SPACE_ID

if TYPE_CHECKING:
    from collections.abc import Iterator

    from agentbase.config import AppPaths


@pytest.fixture
def client(app_paths: AppPaths) -> Iterator[TestClient]:
    with TestClient(create_app(app_paths, secrets=SecretStore())) as test_client:
        yield test_client


def _alert(symbol: str, change: float) -> NewAlert:
    return NewAlert(
        symbol=symbol,
        name=None,
        instrument="stock",
        kind="move",
        direction="down" if change < 0 else "up",
        change_pct=change,
        level_pct=5,
        price=94.5,
        reference_price=100.0,
        reference="previous_close",
        window_minutes=None,
        session="regular",
        market_date="2026-10-13",
        quoted_at="2026-10-13T15:00:00+00:00",
    )


def _record(client: TestClient, *alerts: NewAlert) -> None:
    store: AlertStore = client.app.state.alerts  # type: ignore[attr-defined]

    async def record() -> None:
        await store.record_batch(
            DEFAULT_SPACE_ID,
            list(alerts),
            status="off",
            explanation_path=None,
            now=datetime(2026, 10, 13, 15, tzinfo=UTC),
        )

    anyio.run(record)


def test_alerts_list_newest_first_and_are_marked_seen(client: TestClient) -> None:
    assert client.get("/alerts").json() == {"alerts": [], "unseen": 0}
    _record(client, _alert("MU", -5.5), _alert("AVGO", 6.1))

    body = client.get("/alerts", params={"space_id": DEFAULT_SPACE_ID}).json()
    assert body["unseen"] == 2
    assert {alert["symbol"] for alert in body["alerts"]} == {"MU", "AVGO"}
    assert body["alerts"][0]["explanation_status"] == "off"
    assert client.get("/alerts", params={"space_id": "elsewhere"}).json()["unseen"] == 0

    marked = client.post("/alerts/seen", json={"space_id": DEFAULT_SPACE_ID})
    assert marked.json() == {"marked": 2}
    assert client.get("/alerts").json()["unseen"] == 0
    assert all(alert["seen_at"] for alert in client.get("/alerts").json()["alerts"])


def test_a_watch_is_off_until_switched_on_and_its_file_is_the_record(
    client: TestClient, app_paths: AppPaths
) -> None:
    url = f"/spaces/{DEFAULT_SPACE_ID}/monitor"
    status = client.get(url).json()
    assert status["enabled"] is False and status["error"] is None

    switched = client.put(url, json={"enabled": True})
    assert switched.status_code == 200, switched.text
    assert switched.json()["enabled"] is True
    path = app_paths.spaces_dir / DEFAULT_SPACE_ID / MONITOR_PATH
    assert json.loads(path.read_text(encoding="utf-8"))["enabled"] is True

    assert client.put(url, json={"enabled": False}).json()["enabled"] is False


def test_a_broken_file_is_reported_and_left_alone(
    client: TestClient, app_paths: AppPaths
) -> None:
    path = app_paths.spaces_dir / DEFAULT_SPACE_ID / MONITOR_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{broken", encoding="utf-8")
    url = f"/spaces/{DEFAULT_SPACE_ID}/monitor"

    assert "not valid JSON" in client.get(url).json()["error"]
    refused = client.put(url, json={"enabled": True})
    assert refused.status_code == 422
    assert "left alone" in refused.json()["detail"]["message"]
    assert path.read_text(encoding="utf-8") == "{broken"
    assert client.put("/spaces/nope/monitor", json={"enabled": True}).status_code == 404


def test_the_alert_channel_must_be_a_discord_id_and_blank_clears_it(client: TestClient) -> None:
    refused = client.patch("/settings", json={"discord_alert_channel_id": "#alerts"})
    assert refused.status_code == 400
    assert "Copy Channel ID" in refused.text

    saved = client.patch("/settings", json={"discord_alert_channel_id": "123456789012345678"})
    assert saved.json()["settings"]["discord_alert_channel_id"] == "123456789012345678"
    cleared = client.patch("/settings", json={"discord_alert_channel_id": ""})
    assert cleared.json()["settings"]["discord_alert_channel_id"] is None
    assert client.get("/settings").json()["settings"]["alert_desktop_notifications"] is True
