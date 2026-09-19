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


def test_a_folder_can_be_deleted_with_a_copy_kept_first(client: TestClient) -> None:
    """A folder goes with everything in it, after every file it held is copied
    under `.agentspace/backups/`; the root and hidden folders are refused."""
    prefix = f"/spaces/{DEFAULT_SPACE_ID}/knowledge"
    for path, content in (
        ("scratch/one.md", "# One\n\nSee [[keep/two]]."),
        ("scratch/deeper/three.md", "# Three"),
        ("keep/two.md", "# Two\n\nSee [[scratch/one]]."),
    ):
        assert (
            client.put(f"{prefix}/note", json={"path": path, "content": content}).status_code
            == 200
        )
    state = client.app.state  # type: ignore[attr-defined]
    folder = state.spaces.folder_for(DEFAULT_SPACE_ID)
    (folder / "scratch" / "config.json").write_text('{"tickers": ["AAPL"]}', encoding="utf-8")

    deleted = client.delete(f"{prefix}/folder", params={"path": "scratch/"})
    assert deleted.status_code == 200, deleted.text
    body = deleted.json()
    assert (body["path"], body["deleted_files"]) == ("scratch", 3)
    assert not (folder / "scratch").exists()
    backup = folder / body["backup_path"]
    assert (backup / "scratch" / "one.md").read_text(encoding="utf-8").startswith("# One")
    assert (backup / "scratch" / "config.json").is_file()

    remaining = [note["path"] for note in client.get(prefix).json()["notes"]]
    assert remaining == ["keep/two.md"]
    two = client.get(f"{prefix}/note", params={"path": "keep/two.md"}).json()
    assert two["unresolved_links"] == ["scratch/one"]

    assert client.delete(f"{prefix}/folder", params={"path": "scratch"}).status_code == 404
    for refused in ("", ".", ".obsidian", "../", ".agentspace/backups"):
        assert client.delete(f"{prefix}/folder", params={"path": refused}).status_code == 400, (
            refused
        )


def test_plain_text_files_can_be_listed_written_read_and_deleted(client: TestClient) -> None:
    """The configuration and data the agents read live beside the notes as
    plain text; the Files view edits them, JSON checked before it is saved,
    and a delete keeps a copy first. Notes, hidden files and binaries stay
    out of this list."""
    prefix = f"/spaces/{DEFAULT_SPACE_ID}/knowledge"
    state = client.app.state  # type: ignore[attr-defined]
    folder = state.spaces.folder_for(DEFAULT_SPACE_ID)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "notes.md").write_text("# A note", encoding="utf-8")
    (folder / ".obsidian").mkdir(exist_ok=True)
    (folder / ".obsidian" / "app.json").write_text("{}", encoding="utf-8")
    (folder / "chart.png").write_bytes(b"\x89PNG")

    written = client.put(
        f"{prefix}/file",
        json={
            "path": "config/watchlist.json",
            "content": '{"watchlist": [{"ticker": "AAPL"}]}',
        },
    )
    assert written.status_code == 200, written.text
    assert written.json()["path"] == "config/watchlist.json"
    assert (
        (folder / "config" / "watchlist.json")
        .read_text(encoding="utf-8")
        .startswith('{"watchlist"')
    )

    broken = client.put(
        f"{prefix}/file", json={"path": "config/sources.json", "content": "{not json"}
    )
    assert broken.status_code == 400
    assert "not valid JSON" in broken.json()["detail"]["message"]

    for path in ("notes.md", "../escape.json", ".obsidian/app.json", "chart.png"):
        refused = client.put(f"{prefix}/file", json={"path": path, "content": "x"})
        assert refused.status_code == 400, path

    listed = client.get(f"{prefix}/files").json()["files"]
    assert [entry["path"] for entry in listed] == ["config/watchlist.json"]

    read = client.get(f"{prefix}/file", params={"path": "config/watchlist.json"}).json()
    assert read["content"] == '{"watchlist": [{"ticker": "AAPL"}]}'
    assert (
        client.get(f"{prefix}/file", params={"path": "config/missing.json"}).status_code == 404
    )

    assert (
        client.delete(f"{prefix}/file", params={"path": "config/watchlist.json"}).status_code
        == 204
    )
    assert not (folder / "config" / "watchlist.json").exists()
    backups = list(
        (folder / ".agentspace" / "backups").glob("*-delete-file-*/config/watchlist.json")
    )
    assert len(backups) == 1


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


def test_memories_merge_and_any_note_can_be_pinned(client: TestClient) -> None:
    prefix = f"/spaces/{DEFAULT_SPACE_ID}/knowledge"
    for run_id, outcome in (("a", "Use SQLite."), ("b", "Skip the cache.")):
        client.put(
            f"{prefix}/note",
            json={
                "path": f"memory/runs/{run_id}.md",
                "content": (
                    f"---\ntype: run-memory\nrun_id: {run_id}\nstatus: proposed\n---\n"
                    f"# Memory {run_id}\n\n## Goal\n\nDecide\n\n## Outcome\n\n{outcome}\n"
                    "\n## Sources\n\n- [[research/storage]]\n"
                ),
            },
        )

    merged = client.post(
        f"{prefix}/memories/merge",
        json={"paths": ["memory/runs/a.md", "memory/runs/b.md"], "title": "Storage"},
    )
    pinned = client.patch(f"{prefix}/pin", json={"path": "memory/runs/a.md", "pinned": True})
    refused = client.post(
        f"{prefix}/memories/merge", json={"paths": ["memory/runs/a.md", "memory/runs/a.md"]}
    )
    missing = client.post(
        f"{prefix}/memories/merge", json={"paths": ["memory/runs/a.md", "ghost.md"]}
    )

    assert merged.status_code == 200, merged.text
    assert merged.json()["memory"]["citations"] == ["[[research/storage]]"]
    assert merged.json()["archived_paths"] == ["memory/runs/a.md", "memory/runs/b.md"]
    assert client.get(f"{prefix}/memories").json()["archived"] == 2
    assert pinned.status_code == 200
    assert pinned.json()["pinned"] is True
    assert refused.status_code == 409
    assert missing.status_code == 404
