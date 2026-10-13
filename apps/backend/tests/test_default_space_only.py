"""What was built for the default space's investment pipeline stays there.

At the maintainer's request (2026-10-13), the personal stock-data editor, the
market watch and the seven pipeline tools belong to the default space. Every
other space's agents use the general tools.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from fastapi.testclient import TestClient

from agentbase.main import create_app
from agentbase.store.spaces import DEFAULT_SPACE_ID
from agentbase.tools.catalogue import CATALOGUE, is_default_space_only

if TYPE_CHECKING:
    from collections.abc import Iterator

    from agentbase.config import AppPaths
    from agentbase.secrets import SecretStore

PIPELINE_TOOLS = {
    "read_market",
    "read_company_reports",
    "read_prices",
    "compute_portfolio",
    "check_limits",
    "score_predictions",
    "track_forecasts",
}


@pytest.fixture
def client(app_paths: AppPaths, secrets: SecretStore) -> Iterator[TestClient]:
    with TestClient(create_app(app_paths, secrets=secrets)) as test_client:
        yield test_client


def _space(client: TestClient, name: str = "Lab") -> str:
    response = client.post("/spaces", json={"name": name, "seed": "empty"})
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def _agent(client: TestClient, space_id: str, tools: list[str], name: str = "scout") -> Any:
    return client.post(
        "/agents",
        json={
            "space_id": space_id,
            "name": name,
            "role": "r",
            "system_prompt": "p",
            "allowed_tools": tools,
        },
    )


def _main_agent(client: TestClient, name: str) -> dict[str, Any]:
    roster = client.get("/agents", params={"space_id": DEFAULT_SPACE_ID}).json()
    found: dict[str, Any] = next(agent for agent in roster if agent["name"] == name)
    return found


def test_the_pipeline_tools_are_the_default_spaces_alone() -> None:
    assert {
        tool.name for tool in CATALOGUE if is_default_space_only(tool.name)
    } == PIPELINE_TOOLS


def test_another_space_is_offered_the_general_tools_only(client: TestClient) -> None:
    lab = _space(client)
    everything = {tool["name"] for tool in client.get("/tools").json()}
    in_main = {
        tool["name"]
        for tool in client.get("/tools", params={"space_id": DEFAULT_SPACE_ID}).json()
    }
    in_lab = {tool["name"] for tool in client.get("/tools", params={"space_id": lab}).json()}

    assert in_main == everything
    assert everything >= PIPELINE_TOOLS
    assert in_lab == everything - PIPELINE_TOOLS
    assert {"read_file", "write_file", "http_get", "read_feed", "run_shell"} <= in_lab


def test_an_agent_in_another_space_cannot_be_given_a_pipeline_tool(client: TestClient) -> None:
    lab = _space(client)

    refused = _agent(client, lab, ["read_file", "read_prices"])
    assert refused.status_code == 400
    detail = refused.json()["detail"]
    assert detail["field"] == "allowed_tools"
    assert "read_prices" in detail["message"]
    assert "Main" in detail["message"]

    scout = _agent(client, lab, ["read_file"]).json()
    added = client.patch(
        f"/agents/{scout['id']}", json={"allowed_tools": ["read_file", "track_forecasts"]}
    )
    assert added.status_code == 400
    assert added.json()["detail"]["field"] == "allowed_tools"
    assert client.get(f"/agents/{scout['id']}").json()["allowed_tools"] == ["read_file"]

    # The default space's own agents may have them.
    assert _agent(client, DEFAULT_SPACE_ID, ["read_prices"], name="prices").status_code == 201


def test_an_agent_using_a_pipeline_tool_stays_in_the_default_space(client: TestClient) -> None:
    lab = _space(client)
    movers = _main_agent(client, "market-movers")

    for response in (
        client.patch(f"/agents/{movers['id']}", json={"space_id": lab}),
        client.post(f"/agents/{movers['id']}/copy", json={"space_id": lab}),
    ):
        assert response.status_code == 400
        detail = response.json()["detail"]
        assert detail["field"] == "space_id"
        assert "market-movers" in detail["message"]
        assert "read_prices" in detail["message"]
    assert client.get("/agents", params={"space_id": lab}).json() == []
    assert _main_agent(client, "market-movers")["space_id"] == DEFAULT_SPACE_ID

    # One with general tools only may still be copied out.
    poet = _agent(client, DEFAULT_SPACE_ID, ["read_file", "write_file"], name="poet").json()
    copied = client.post(f"/agents/{poet['id']}/copy", json={"space_id": lab})
    assert copied.status_code == 201
    assert copied.json()["allowed_tools"] == ["read_file", "write_file"]


def test_a_new_space_cannot_start_with_copies_of_the_pipeline(client: TestClient) -> None:
    before = client.get("/spaces").json()

    refused = client.post(
        "/spaces", json={"name": "Clone", "seed": {"copy_from": DEFAULT_SPACE_ID}}
    )

    assert refused.status_code == 400
    assert refused.json()["detail"]["field"] == "seed"
    assert "Main" in refused.json()["detail"]["message"]
    # Refused before the space was made, so there is nothing half-built.
    assert client.get("/spaces").json() == before


def test_personal_stock_data_belongs_to_the_default_space(
    client: TestClient, app_paths: AppPaths
) -> None:
    lab = _space(client)
    main = client.get(f"/spaces/{DEFAULT_SPACE_ID}/portfolio")
    assert main.status_code == 200

    read = client.get(f"/spaces/{lab}/portfolio")
    saved = client.put(f"/spaces/{lab}/portfolio", json=main.json())

    for response in (read, saved):
        assert response.status_code == 404
        assert "Main" in response.text
    assert not (app_paths.spaces_dir / lab / "portfolio").exists()


def test_the_market_watch_belongs_to_the_default_space(
    client: TestClient, app_paths: AppPaths
) -> None:
    lab = _space(client)
    assert client.get(f"/spaces/{DEFAULT_SPACE_ID}/monitor").status_code == 200

    read = client.get(f"/spaces/{lab}/monitor")
    switched = client.put(f"/spaces/{lab}/monitor", json={"enabled": True})

    for response in (read, switched):
        assert response.status_code == 404
        assert "Main" in response.json()["detail"]["message"]
    assert not (app_paths.spaces_dir / lab / "config").exists()
