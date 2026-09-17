"""The HTTP surface used by the native Knowledge section."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from agentspace.config import ALLOWED_ORIGINS
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


def test_crud_search_and_graph(client: TestClient) -> None:
    prefix = f"/spaces/{DEFAULT_SPACE_ID}/knowledge"
    created = client.put(
        f"{prefix}/note",
        json={
            "path": "ideas/agents.md",
            "content": "# Agent memory\n\nLinked to [[ideas/rag]].",
        },
    )
    assert created.status_code == 200, created.text
    assert created.json()["title"] == "Agent memory"

    client.put(
        f"{prefix}/note",
        json={"path": "ideas/rag.md", "content": "# RAG\n\nRetrieval adds evidence."},
    )
    listing = client.get(prefix)
    assert listing.status_code == 200
    assert listing.json()["stats"]["note_count"] == 2

    found = client.post(f"{prefix}/search", json={"query": "retrieval evidence"})
    assert found.json()["hits"][0]["path"] == "ideas/rag.md"
    assert client.get(f"{prefix}/graph").json()["edges"] == [
        {"source": "ideas/agents.md", "target": "ideas/rag.md"}
    ]

    loaded = client.get(f"{prefix}/note", params={"path": "ideas/agents.md"})
    assert loaded.json()["links"] == ["ideas/rag.md"]
    assert (
        client.delete(f"{prefix}/note", params={"path": "ideas/agents.md"}).status_code == 204
    )
    assert client.get(f"{prefix}/note", params={"path": "ideas/agents.md"}).status_code == 404


def test_missing_space_and_invalid_paths_are_readable_errors(client: TestClient) -> None:
    assert client.get("/spaces/ghost/knowledge").status_code == 404
    rejected = client.put(
        f"/spaces/{DEFAULT_SPACE_ID}/knowledge/note",
        json={"path": "../escape.md", "content": "no"},
    )
    assert rejected.status_code == 400
    assert rejected.json()["detail"]["field"] == "path"


def test_note_write_is_allowed_by_the_webview_cors_policy(client: TestClient) -> None:
    response = client.options(
        f"/spaces/{DEFAULT_SPACE_ID}/knowledge/note",
        headers={
            "Origin": ALLOWED_ORIGINS[0],
            "Access-Control-Request-Method": "PUT",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ALLOWED_ORIGINS[0]
    assert "PUT" in response.headers["access-control-allow-methods"]


def test_memory_curation_move_import_and_evaluation(client: TestClient) -> None:
    prefix = f"/spaces/{DEFAULT_SPACE_ID}/knowledge"
    memory_path = "memory/runs/run-api.md"
    memory = (
        "---\ntype: run-memory\nrun_id: run-api\nstatus: proposed\n"
        "pinned: false\nconfidence: agent-generated\ncreated: 2026-09-15\n---\n"
        "# Run memory\n\n## Goal\n\nChoose storage\n\n## Outcome\n\nUse SQLite WAL.\n"
    )
    assert (
        client.put(f"{prefix}/note", json={"path": memory_path, "content": memory}).status_code
        == 200
    )

    inbox = client.get(f"{prefix}/memories").json()
    assert inbox["proposed"] == 1
    approved = client.patch(
        f"{prefix}/memory",
        json={"path": memory_path, "status": "approved", "pinned": True},
    )
    assert approved.json()["status"] == "approved"
    assert approved.json()["pinned"] is True

    imported = client.post(
        f"{prefix}/import",
        json={
            "files": [
                {"path": "research/sqlite.md", "content": "# SQLite\n\nWAL storage."},
                {"path": "index.md", "content": "# Index\n\n[[research/sqlite]]"},
            ]
        },
    )
    assert imported.json()["created"] == 2
    moved = client.post(
        f"{prefix}/move",
        json={"source": "research/sqlite.md", "target": "decisions/sqlite.md"},
    )
    assert moved.json()["note"]["path"] == "decisions/sqlite.md"
    assert moved.json()["updated_links"] == 1

    evaluated = client.post(
        f"{prefix}/evaluate",
        json={
            "cases": [
                {
                    "question": "WAL storage",
                    "expected_paths": ["decisions/sqlite.md"],
                }
            ]
        },
    )
    assert evaluated.status_code == 200, evaluated.text
    assert evaluated.json()["mean_reciprocal_rank"] == 1
