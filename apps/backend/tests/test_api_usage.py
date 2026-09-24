"""The usage report: the ledger sliced by model, space, day and run."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from agentbase.budget.ledger import current_period
from agentbase.main import create_app
from agentbase.store.spaces import DEFAULT_SPACE_ID

if TYPE_CHECKING:
    from collections.abc import Iterator

    from agentbase.config import AppPaths
    from agentbase.secrets import SecretStore


@pytest.fixture
def client(app_paths: AppPaths, secrets: SecretStore) -> Iterator[TestClient]:
    with TestClient(create_app(app_paths, secrets=secrets)) as test_client:
        yield test_client


def _spend(
    client: TestClient,
    run_id: str | None,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cost: int,
    *,
    period: str | None = None,
    ts: str = "2026-09-18T10:00:00+00:00",
) -> None:
    db = client.app.state.db  # type: ignore[attr-defined]
    with db.write() as connection:
        connection.execute(
            "INSERT INTO spend (run_id, period, provider, model, input_tokens, output_tokens,"
            " cost_micros, ts) VALUES (?, ?, 'anthropic', ?, ?, ?, ?, ?)",
            (run_id, period or current_period(), model, input_tokens, output_tokens, cost, ts),
        )


def test_an_empty_ledger_reports_zeros_for_this_month(client: TestClient) -> None:
    body = client.get("/usage").json()
    assert body["period"] == current_period()
    assert body["periods"] == []
    assert body["totals"] == {
        "calls": 0,
        "runs": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cost_micros": 0,
        "cost_display": "$0.0000",
    }
    assert body["by_model"] == []
    assert body["runs"] == []
    assert body["cap_micros"] == 20_000_000


def test_the_report_slices_the_ledger_and_ranks_runs_by_cost(client: TestClient) -> None:
    lab = client.post("/spaces", json={"name": "Lab"}).json()
    main_run = client.post("/runs", json={"goal": "main goal"}).json()
    lab_run = client.post("/runs", json={"goal": "lab goal", "space_id": lab["id"]}).json()

    _spend(client, main_run["id"], "claude-opus-5", 1000, 100, 5000)
    _spend(
        client, main_run["id"], "claude-opus-5", 3000, 200, 9000, ts="2026-09-19T08:00:00+00:00"
    )
    _spend(client, lab_run["id"], "claude-haiku-4-5", 500, 50, 400)
    # A deleted run keeps its spend with the run cleared.
    _spend(client, None, "claude-haiku-4-5", 200, 20, 100)
    # Last month is another period and stays out of this one.
    _spend(client, main_run["id"], "claude-opus-5", 999, 999, 99999, period="2026-08")

    body = client.get("/usage").json()
    assert body["periods"] == [current_period(), "2026-08"]
    assert body["totals"] == {
        "calls": 4,
        "runs": 2,
        "input_tokens": 4700,
        "output_tokens": 370,
        "cost_micros": 14500,
        "cost_display": "$0.0145",
    }

    models = {bucket["key"]: bucket for bucket in body["by_model"]}
    assert models["anthropic/claude-opus-5"]["calls"] == 2
    assert models["anthropic/claude-opus-5"]["cost_micros"] == 14000
    assert models["anthropic/claude-haiku-4-5"]["input_tokens"] == 700
    assert [bucket["key"] for bucket in body["by_model"]] == [
        "anthropic/claude-opus-5",
        "anthropic/claude-haiku-4-5",
    ]

    spaces = {bucket["label"]: bucket for bucket in body["by_space"]}
    assert spaces["Main"]["cost_micros"] == 14000
    assert spaces["Lab"]["cost_micros"] == 400
    assert spaces["deleted runs"]["cost_micros"] == 100

    assert [bucket["key"] for bucket in body["by_day"]] == ["2026-09-18", "2026-09-19"]
    assert body["by_day"][1]["cost_micros"] == 9000

    runs = body["runs"]
    assert [run["run_id"] for run in runs] == [main_run["id"], lab_run["id"], None]
    top = runs[0]
    assert top["goal"] == "main goal"
    assert top["space_id"] == DEFAULT_SPACE_ID
    assert top["calls"] == 2
    assert top["peak_context"] == 3000
    assert top["mean_context"] == 2000
    assert top["cost_display"] == "$0.0140"


def test_the_report_narrows_to_a_space_and_a_period(client: TestClient) -> None:
    lab = client.post("/spaces", json={"name": "Lab"}).json()
    main_run = client.post("/runs", json={"goal": "main goal"}).json()
    lab_run = client.post("/runs", json={"goal": "lab goal", "space_id": lab["id"]}).json()
    _spend(client, main_run["id"], "claude-opus-5", 1000, 100, 5000)
    _spend(client, lab_run["id"], "claude-haiku-4-5", 500, 50, 400)
    _spend(client, lab_run["id"], "claude-haiku-4-5", 700, 70, 600, period="2026-08")

    narrowed = client.get("/usage", params={"space_id": lab["id"]}).json()
    assert narrowed["space_id"] == lab["id"]
    assert narrowed["totals"]["cost_micros"] == 400
    assert [run["run_id"] for run in narrowed["runs"]] == [lab_run["id"]]

    earlier = client.get("/usage", params={"period": "2026-08", "space_id": lab["id"]}).json()
    assert earlier["period"] == "2026-08"
    assert earlier["totals"]["cost_micros"] == 600

    bad = client.get("/usage", params={"period": "August"})
    assert bad.status_code == 400
    assert bad.json()["detail"]["field"] == "period"
