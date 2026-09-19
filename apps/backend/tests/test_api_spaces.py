"""The spaces API, and every endpoint that grew a `space_id` with it."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from fastapi.testclient import TestClient

from agentspace.main import create_app
from agentspace.store.spaces import DEFAULT_SPACE_ID

if TYPE_CHECKING:
    from collections.abc import Iterator

    from agentspace.config import AppPaths
    from agentspace.secrets import SecretStore


@pytest.fixture
def client(app_paths: AppPaths, secrets: SecretStore) -> Iterator[TestClient]:
    with TestClient(create_app(app_paths, secrets=secrets)) as test_client:
        yield test_client


def _create(client: TestClient, name: str, **extra: object) -> dict[str, Any]:
    response = client.post("/spaces", json={"name": name, **extra})
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


# --- the space itself -----------------------------------------------------------


def test_a_fresh_install_has_one_space_with_the_shipped_roster(client: TestClient) -> None:
    spaces = client.get("/spaces").json()
    assert [space["name"] for space in spaces] == ["Main"]
    assert spaces[0]["id"] == DEFAULT_SPACE_ID
    assert spaces[0]["is_default"] is True
    assert spaces[0]["folder"].endswith(DEFAULT_SPACE_ID)

    roster = client.get("/agents", params={"space_id": DEFAULT_SPACE_ID}).json()
    assert [agent["name"] for agent in roster] == [
        "bear-architect",
        "bull-architect",
        "decision",
        "event-calendar",
        "market-movers",
        "news-scanner",
        "portfolio-review",
        "research-librarian",
        "review-analyst",
        "risk-manager",
    ]
    assert all(agent["space_id"] == DEFAULT_SPACE_ID for agent in roster)


def test_a_new_space_starts_with_copies_of_the_starter_roles_by_default(
    client: TestClient,
) -> None:
    lab = _create(client, "Lab")

    roster = client.get("/agents", params={"space_id": lab["id"]}).json()
    assert [agent["name"] for agent in roster] == ["researcher", "reviewer", "writer"]
    # Copies: new ids, deletable.
    assert all(agent["is_builtin"] is False for agent in roster)
    assert client.delete(f"/agents/{roster[0]['id']}").status_code == 204
    # And the default space's built-ins are untouched.
    originals = client.get("/agents", params={"space_id": DEFAULT_SPACE_ID}).json()
    assert len(originals) == 10


def test_a_space_may_start_empty_or_as_a_copy_of_another(client: TestClient) -> None:
    empty = _create(client, "Empty", seed="empty")
    assert client.get("/agents", params={"space_id": empty["id"]}).json() == []

    client.post(
        "/agents",
        json={"space_id": empty["id"], "name": "poet", "role": "r", "system_prompt": "p"},
    )
    copied = _create(client, "Copy", seed={"copy_from": empty["id"]})
    names = [a["name"] for a in client.get("/agents", params={"space_id": copied["id"]}).json()]
    assert names == ["poet"]

    bad = client.post("/spaces", json={"name": "Nope", "seed": {"copy_from": "ghost"}})
    assert bad.status_code == 400
    assert bad.json()["detail"]["field"] == "seed"


def test_seeding_an_existing_space_adds_the_roles_it_lacks(client: TestClient) -> None:
    empty = _create(client, "Empty", seed="empty")
    added = client.post(f"/spaces/{empty['id']}/seed")
    assert added.status_code == 201
    assert [a["name"] for a in added.json()] == ["researcher", "writer", "reviewer"]
    # Pressing it again adds nothing and breaks nothing.
    assert client.post(f"/spaces/{empty['id']}/seed").json() == []


def test_a_space_narrows_the_per_tool_answers_and_can_inherit_again(client: TestClient) -> None:
    lab = _create(client, "Lab")
    assert lab["tool_policies"] is None

    set_ = client.patch(f"/spaces/{lab['id']}", json={"tool_policies": {"http_get": "deny"}})
    assert set_.status_code == 200, set_.text
    assert set_.json()["tool_policies"] == {"http_get": "deny"}

    bad = client.patch(f"/spaces/{lab['id']}", json={"tool_policies": {"teleport": "deny"}})
    assert bad.status_code == 400
    assert bad.json()["detail"]["field"] == "tool_policies"

    back = client.patch(f"/spaces/{lab['id']}", json={"tool_policies": None})
    assert back.json()["tool_policies"] is None


def test_a_rule_can_be_set_and_set_back_to_inherit(client: TestClient) -> None:
    lab = _create(client, "Lab")

    updated = client.patch(
        f"/spaces/{lab['id']}", json={"max_run_seconds": 1200, "model": "gpt-5"}
    )
    assert updated.status_code == 200
    assert updated.json()["max_run_seconds"] == 1200
    assert updated.json()["model"] == "gpt-5"

    # Sent as null: back to inheriting, distinguishable from not sent.
    inherited = client.patch(f"/spaces/{lab['id']}", json={"max_run_seconds": None})
    assert inherited.json()["max_run_seconds"] is None
    assert inherited.json()["model"] == "gpt-5"


def test_a_space_always_names_its_model(client: TestClient) -> None:
    """Settings picks the provider; the model is the space's. A space made
    without one starts on the provider's default, a model set to null lands
    there again, and a change of provider brings that provider's default."""
    lab = _create(client, "Lab")
    assert lab["provider"] is None
    assert lab["model"] == "claude-opus-5"

    own = _create(client, "Own", provider="openai", model="gpt-5.4")
    assert (own["provider"], own["model"]) == ("openai", "gpt-5.4")

    moved = client.patch(f"/spaces/{lab['id']}", json={"provider": "openai"})
    assert moved.json()["model"] == "gpt-5.5"

    reset = client.patch(f"/spaces/{lab['id']}", json={"model": None})
    assert reset.json()["model"] == "gpt-5.5"

    back = client.patch(f"/spaces/{lab['id']}", json={"provider": None})
    assert (back.json()["provider"], back.json()["model"]) == (None, "claude-opus-5")

    # Ollama's model is typed, so a space moved there keeps what it had until then.
    typed = client.patch(
        f"/spaces/{lab['id']}", json={"provider": "ollama", "model": "qwen3:4b"}
    )
    assert typed.json()["model"] == "qwen3:4b"


def test_refusals_name_the_field(client: TestClient) -> None:
    _create(client, "Lab")
    duplicate = client.post("/spaces", json={"name": "lab"})
    assert duplicate.status_code == 400
    assert duplicate.json()["detail"]["field"] == "name"

    lab_id = client.get("/spaces").json()[1]["id"]
    provider = client.patch(f"/spaces/{lab_id}", json={"provider": "nope"})
    assert provider.status_code == 400
    assert provider.json()["detail"]["field"] == "provider"

    assert client.patch(f"/spaces/{lab_id}", json={}).status_code == 400
    assert client.patch(f"/spaces/{lab_id}", json={"colour": "red"}).status_code == 422
    assert client.patch("/spaces/ghost", json={"name": "x"}).status_code == 404


def test_the_default_space_is_protected_and_a_space_with_runs_is_archived_not_deleted(
    client: TestClient,
) -> None:
    assert (
        client.patch(f"/spaces/{DEFAULT_SPACE_ID}", json={"archived": True}).status_code == 409
    )
    assert client.delete(f"/spaces/{DEFAULT_SPACE_ID}").status_code == 409

    lab = _create(client, "Lab")
    client.post("/debug/fake_run", params={"step_ms": 0})  # lands in the default space
    run = client.post("/runs", json={"goal": "in the lab", "space_id": lab["id"]})
    assert run.status_code == 201
    assert run.json()["space_id"] == lab["id"]

    refused = client.delete(f"/spaces/{lab['id']}")
    assert refused.status_code == 409
    assert "Archive it" in refused.json()["detail"]

    archived = client.patch(f"/spaces/{lab['id']}", json={"archived": True})
    assert archived.json()["archived"] is True
    # An archived space starts no runs, and still lists.
    assert client.post("/runs", json={"goal": "x", "space_id": lab["id"]}).status_code == 409
    assert [s["name"] for s in client.get("/spaces").json()] == ["Main", "Lab"]


def test_an_empty_space_can_be_deleted(client: TestClient) -> None:
    lab = _create(client, "Lab")
    assert client.delete(f"/spaces/{lab['id']}").status_code == 204
    assert client.get(f"/spaces/{lab['id']}").status_code == 404


# --- what grew a space_id ---------------------------------------------------------


def test_runs_list_per_space_and_a_run_names_its_space(client: TestClient) -> None:
    lab = _create(client, "Lab")
    client.post("/debug/fake_run", params={"step_ms": 0})
    in_lab = client.post("/runs", json={"goal": "lab work", "space_id": lab["id"]}).json()

    assert [r["goal"] for r in client.get("/runs", params={"space_id": lab["id"]}).json()] == [
        "lab work"
    ]
    assert len(client.get("/runs").json()) == 2
    assert client.get(f"/runs/{in_lab['id']}").json()["space_id"] == lab["id"]
    assert client.post("/runs", json={"goal": "x", "space_id": "ghost"}).status_code == 404


def test_an_agent_can_be_moved_and_copied_between_spaces(client: TestClient) -> None:
    lab = _create(client, "Lab", seed="empty")
    poet = client.post(
        "/agents", json={"name": "poet", "role": "r", "system_prompt": "p"}
    ).json()
    assert poet["space_id"] == DEFAULT_SPACE_ID

    moved = client.patch(f"/agents/{poet['id']}", json={"space_id": lab["id"]})
    assert moved.status_code == 200
    assert moved.json()["space_id"] == lab["id"]
    assert "poet" not in [
        a["name"] for a in client.get("/agents", params={"space_id": DEFAULT_SPACE_ID}).json()
    ]

    copied = client.post(f"/agents/{poet['id']}/copy", json={"space_id": DEFAULT_SPACE_ID})
    assert copied.status_code == 201
    assert copied.json()["id"] != poet["id"]
    assert copied.json()["space_id"] == DEFAULT_SPACE_ID
    # A second copy clashes on the name, in that space.
    clash = client.post(f"/agents/{poet['id']}/copy", json={"space_id": DEFAULT_SPACE_ID})
    assert clash.status_code == 409
    assert clash.json()["detail"]["field"] == "name"

    ghost = client.patch(f"/agents/{poet['id']}", json={"space_id": "ghost"})
    assert ghost.status_code == 400
    assert ghost.json()["detail"]["field"] == "space_id"


def test_the_same_name_may_be_created_in_two_spaces(client: TestClient) -> None:
    lab = _create(client, "Lab", seed="empty")
    first = client.post("/agents", json={"name": "poet", "role": "r", "system_prompt": "p"})
    second = client.post(
        "/agents",
        json={"space_id": lab["id"], "name": "poet", "role": "r", "system_prompt": "p"},
    )
    assert (first.status_code, second.status_code) == (201, 201)
    third = client.post("/agents", json={"name": "poet", "role": "r", "system_prompt": "p"})
    assert third.status_code == 409


def test_the_budget_reports_a_spaces_share_beside_the_app_wide_figures(
    client: TestClient,
) -> None:
    lab = _create(client, "Lab")
    whole = client.get("/budget").json()
    assert whole["space_spent_micros"] is None
    per_space = client.get("/budget", params={"space_id": lab["id"]}).json()
    assert per_space["space_spent_micros"] == 0
    assert per_space["space_spent_display"] == "$0.0000"
    assert per_space["cap_micros"] == whole["cap_micros"]


def test_channel_space_id_must_name_a_live_space(client: TestClient) -> None:
    lab = _create(client, "Lab")
    ok = client.patch("/settings", json={"channel_space_id": lab["id"]})
    assert ok.status_code == 200
    assert ok.json()["settings"]["channel_space_id"] == lab["id"]

    ghost = client.patch("/settings", json={"channel_space_id": "ghost"})
    assert ghost.status_code == 400
    assert ghost.json()["detail"]["field"] == "channel_space_id"

    client.patch(f"/spaces/{lab['id']}", json={"archived": True})
    archived = client.patch("/settings", json={"channel_space_id": lab["id"]})
    assert archived.status_code == 400

    # An empty string is how the default space is chosen again.
    back = client.patch("/settings", json={"channel_space_id": ""})
    assert back.json()["settings"]["channel_space_id"] is None


def test_verify_checks_a_spaces_effective_settings(client: TestClient) -> None:
    """A space that pins a provider is verified as that provider."""
    lab = _create(client, "Lab")
    client.patch(f"/spaces/{lab['id']}", json={"provider": "ollama", "model": "qwen3:4b"})

    whole = client.post("/settings/verify").json()
    in_lab = client.post("/settings/verify", params={"space_id": lab["id"]}).json()

    # No key for the app-wide provider in this test's secrets; the space
    # pinned one that needs none.
    assert whole["ok"] is False
    assert in_lab["ok"] is True
    assert in_lab["provider"] == "ollama"
    assert client.post("/settings/verify", params={"space_id": "ghost"}).status_code == 404
