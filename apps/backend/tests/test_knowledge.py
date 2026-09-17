"""The per-space Markdown vault and the local retrieval layer over it."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from agentspace.knowledge.store import (
    MAX_NOTES,
    KnowledgeEvaluationCase,
    KnowledgePathError,
    KnowledgeStore,
    MemoryStatus,
    SearchFilters,
    _parse_note,
    _search,
)
from agentspace.store.spaces import DEFAULT_SPACE_ID, SpaceStore

if TYPE_CHECKING:
    from agentspace.config import AppPaths
    from agentspace.store.db import Database

pytestmark = pytest.mark.anyio


@pytest.fixture
def knowledge(db: Database, app_paths: AppPaths) -> KnowledgeStore:
    return KnowledgeStore(SpaceStore(db, app_paths.spaces_dir))


async def test_markdown_is_the_source_for_properties_links_backlinks_and_graph(
    knowledge: KnowledgeStore,
) -> None:
    await knowledge.write_note(
        DEFAULT_SPACE_ID,
        "research/sqlite.md",
        """---
tags:
  - database
status: evergreen
---
# SQLite notes

WAL permits readers during a writer. See [[decisions/storage]].
""",
    )
    await knowledge.write_note(
        DEFAULT_SPACE_ID,
        "decisions/storage.md",
        "# Storage decision\n\nUse SQLite. Related: [[research/sqlite|research]].\n",
    )

    note = await knowledge.get_note(DEFAULT_SPACE_ID, "decisions/storage.md")
    assert note.title == "Storage decision"
    assert note.backlinks == ["research/sqlite.md"]
    assert note.links == ["research/sqlite.md"]

    listed = await knowledge.list_notes(DEFAULT_SPACE_ID)
    sqlite = next(item for item in listed if item.path == "research/sqlite.md")
    assert sqlite.tags == ["database"]
    assert sqlite.properties["status"] == "evergreen"

    graph = await knowledge.graph(DEFAULT_SPACE_ID)
    assert {node.path for node in graph.nodes} == {
        "decisions/storage.md",
        "research/sqlite.md",
    }
    assert {(edge.source, edge.target) for edge in graph.edges} == {
        ("decisions/storage.md", "research/sqlite.md"),
        ("research/sqlite.md", "decisions/storage.md"),
    }


async def test_local_vector_retrieval_returns_chunks_with_a_stable_citation(
    knowledge: KnowledgeStore,
) -> None:
    await knowledge.write_note(
        DEFAULT_SPACE_ID,
        "research/launch.md",
        "# Launch research\n\n## Retention\n\nCustomers stay when onboarding is short and guided.\n",
    )
    await knowledge.write_note(
        DEFAULT_SPACE_ID,
        "recipes/soup.md",
        "# Soup\n\nCarrots and stock make a simple dinner.\n",
    )

    hits = await knowledge.search(DEFAULT_SPACE_ID, "improve customer onboarding retention")

    assert hits[0].path == "research/launch.md"
    assert hits[0].citation == "[[research/launch#Retention]]"
    assert hits[0].score > 0
    assert {hit.path for hit in hits} == {"research/launch.md"}
    context = await knowledge.context_for(
        DEFAULT_SPACE_ID, "improve customer onboarding retention"
    )
    assert "untrusted reference material" in context.lower()
    assert "[[research/launch#Retention]]" in context
    assert "Customers stay" in context


async def test_relative_markdown_links_and_section_headings_are_searchable(
    knowledge: KnowledgeStore,
) -> None:
    await knowledge.write_note(
        DEFAULT_SPACE_ID,
        "research/sqlite.md",
        "# SQLite\n\n## Write-ahead logging\n\nReduces writer contention.",
    )
    await knowledge.write_note(
        DEFAULT_SPACE_ID,
        "decisions/storage.md",
        "# Storage\n\nRead [the research](../research/sqlite.md).",
    )

    decision = await knowledge.get_note(DEFAULT_SPACE_ID, "decisions/storage.md")
    hits = await knowledge.search(DEFAULT_SPACE_ID, "write-ahead logging")

    assert decision.links == ["research/sqlite.md"]
    assert hits[0].citation == "[[research/sqlite#Write-ahead logging]]"


async def test_run_memories_are_markdown_and_are_retrievable(
    knowledge: KnowledgeStore,
) -> None:
    path = await knowledge.save_run_memory(
        DEFAULT_SPACE_ID,
        run_id="run-123",
        goal="Choose a database",
        summary="Use SQLite in WAL mode for the local event log.",
    )

    assert path == "memory/runs/run-123.md"
    memory = await knowledge.get_note(DEFAULT_SPACE_ID, path)
    assert memory.properties["run_id"] == "run-123"
    assert memory.properties["status"] == "proposed"
    assert "agent-memory" in memory.tags
    assert "Use SQLite in WAL mode" in memory.content
    assert await knowledge.search(DEFAULT_SPACE_ID, "database WAL") == []

    approved = await knowledge.update_memory(
        DEFAULT_SPACE_ID, path, status=MemoryStatus.APPROVED, pinned=True
    )
    assert approved.status is MemoryStatus.APPROVED
    assert approved.pinned is True
    assert (await knowledge.search(DEFAULT_SPACE_ID, "database WAL"))[0].path == path

    inbox = await knowledge.memories(DEFAULT_SPACE_ID)
    assert inbox.approved == 1
    assert inbox.proposed == 0
    assert inbox.items[0].run_id == "run-123"


async def test_incremental_index_reuses_unchanged_notes_and_detects_external_edits(
    knowledge: KnowledgeStore,
) -> None:
    root = knowledge.spaces.folder_for(DEFAULT_SPACE_ID)
    root.mkdir(parents=True, exist_ok=True)
    note = root / "external.md"
    note.write_text("# External\n\nFirst version.", encoding="utf-8")

    first = await knowledge.index(DEFAULT_SPACE_ID)
    second = await knowledge.index(DEFAULT_SPACE_ID)
    note.write_text("# External\n\nSecond longer version.", encoding="utf-8")
    third = await knowledge.index(DEFAULT_SPACE_ID)

    assert first.index_status.changed_files == 1
    assert second.index_status.changed_files == 0
    assert second.index_status.reused_files == 1
    assert third.index_status.changed_files == 1
    assert third.notes[0].excerpt.endswith("Second longer version.")


async def test_move_updates_links_and_keeps_a_recoverable_backup(
    knowledge: KnowledgeStore,
) -> None:
    await knowledge.write_note(
        DEFAULT_SPACE_ID, "research/source.md", "# Source\n\nSee [[other]]."
    )
    await knowledge.write_note(DEFAULT_SPACE_ID, "research/other.md", "# Other")
    await knowledge.write_note(
        DEFAULT_SPACE_ID,
        "index.md",
        "# Index\n\nRead [[research/source|source]] and [source](research/source.md).",
    )

    moved = await knowledge.move_note(
        DEFAULT_SPACE_ID, "research/source.md", "decisions/source.md"
    )
    index = await knowledge.get_note(DEFAULT_SPACE_ID, "index.md")

    assert moved.note.path == "decisions/source.md"
    assert moved.updated_links == 3
    assert "[[decisions/source|source]]" in index.content
    assert "decisions/source.md" in index.content
    assert moved.backup_path.startswith(".agentspace/backups/")
    assert (
        not knowledge.spaces.folder_for(DEFAULT_SPACE_ID)
        .joinpath("research/source.md")
        .exists()
    )


async def test_import_skips_or_backs_up_conflicts(
    knowledge: KnowledgeStore,
) -> None:
    await knowledge.write_note(DEFAULT_SPACE_ID, "existing.md", "# Original")

    skipped = await knowledge.import_notes(
        DEFAULT_SPACE_ID,
        [("existing.md", "# Replacement"), ("new.md", "# New")],
    )
    replaced = await knowledge.import_notes(
        DEFAULT_SPACE_ID, [("existing.md", "# Replacement")], overwrite=True
    )

    assert (skipped.created, skipped.skipped) == (1, 1)
    assert replaced.updated == 1
    assert replaced.backup_path is not None
    assert (await knowledge.get_note(DEFAULT_SPACE_ID, "existing.md")).title == "Replacement"


async def test_filters_explanations_and_evaluation_are_auditable(
    knowledge: KnowledgeStore,
) -> None:
    await knowledge.write_note(
        DEFAULT_SPACE_ID,
        "research/retention.md",
        "---\ntype: research\ntags: [growth]\n---\n# Retention\n\nGuided onboarding retains customers.",
    )
    await knowledge.write_note(
        DEFAULT_SPACE_ID, "decisions/retention.md", "# Retention decision\n\nDo less."
    )

    hits = await knowledge.search(
        DEFAULT_SPACE_ID,
        "guided onboarding",
        filters=SearchFilters(folders=["research"], tags=["growth"]),
    )
    evaluation = await knowledge.evaluate(
        DEFAULT_SPACE_ID,
        [
            KnowledgeEvaluationCase(
                question="guided onboarding", expected_paths=["research/retention.md"]
            )
        ],
    )

    assert hits[0].matched_terms == ["guid", "onboard"]
    assert "body: guid, onboard" in hits[0].reasons
    assert hits[0].estimated_tokens > 0
    assert evaluation.mean_reciprocal_rank == 1
    assert evaluation.mean_recall_at_k == 1


def test_hybrid_ranker_accepts_ten_thousand_notes() -> None:
    now = datetime.now(UTC)
    notes = [
        _parse_note(
            f"scale/note-{index:05}.md",
            f"# Note {index}\n\n{'needle evidence' if index == 9_999 else 'ordinary text'}",
            now,
        )
        for index in range(MAX_NOTES)
    ]

    hits = _search(notes, "needle", 5, SearchFilters())

    assert hits[0].path == "scale/note-09999.md"


@pytest.mark.parametrize(
    "path",
    ["../outside.md", ".obsidian/plugins/agent.md", "notes.txt", "/outside.md"],
)
async def test_note_paths_cannot_escape_or_modify_obsidian_configuration(
    knowledge: KnowledgeStore, path: str
) -> None:
    with pytest.raises(KnowledgePathError):
        await knowledge.write_note(DEFAULT_SPACE_ID, path, "no")
