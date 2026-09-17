import type {
  KnowledgeGraph,
  KnowledgeIndex,
  KnowledgeNote,
  KnowledgeSearch,
  MemoryIndex,
  MemoryItem,
  SpaceResponse,
} from "@agentspace/schemas";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../lib/api";

import { KnowledgeView } from "./KnowledgeView";

vi.mock("../lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof api>()),
  listKnowledge: vi.fn(),
  getKnowledgeNote: vi.fn(),
  saveKnowledgeNote: vi.fn(),
  deleteKnowledgeNote: vi.fn(),
  searchKnowledge: vi.fn(),
  getKnowledgeGraph: vi.fn(),
  moveKnowledgeNote: vi.fn(),
  importKnowledge: vi.fn(),
  listMemories: vi.fn(),
  updateMemory: vi.fn(),
  mergeMemories: vi.fn(),
  pinKnowledgeNote: vi.fn(),
  evaluateKnowledge: vi.fn(),
}));

const mocked = vi.mocked(api);

const space: SpaceResponse = {
  id: "space-lab",
  name: "Lab",
  description: "",
  provider: null,
  model: null,
  auto_approve: null,
  max_steps_per_agent: null,
  max_agents_per_run: null,
  max_run_seconds: null,
  archived: false,
  created_at: "2026-09-15T00:00:00Z",
  updated_at: "2026-09-15T00:00:00Z",
  folder: "/data/spaces/space-lab",
  is_default: false,
};

const note: KnowledgeNote = {
  path: "decisions/storage.md",
  title: "Storage decision",
  excerpt: "Use SQLite WAL.",
  tags: ["architecture"],
  properties: { status: "accepted", tags: "architecture" },
  links: ["research/sqlite.md"],
  backlinks: ["index.md"],
  unresolved_links: ["missing note"],
  pinned: false,
  updated_at: "2026-09-15T00:00:00Z",
  content: "---\ntags: [architecture]\nstatus: accepted\n---\n# Storage decision\n\nUse **SQLite WAL**. See [[research/sqlite]].",
};

const orphan: KnowledgeNote = {
  path: "scratch/orphan.md",
  title: "Orphan",
  excerpt: "Nobody links here.",
  tags: ["scratch"],
  properties: {},
  links: [],
  backlinks: [],
  unresolved_links: [],
  pinned: true,
  updated_at: "2026-09-15T00:00:00Z",
  content: "# Orphan\n\nNobody links here.",
};

const index: KnowledgeIndex = {
  notes: [note, orphan],
  stats: {
    note_count: 2,
    link_count: 1,
    tag_count: 2,
    chunk_count: 2,
    orphan_count: 1,
    unresolved_link_count: 1,
  },
  index_status: {
    indexed_at: "2026-09-15T00:00:00Z",
    scanned_files: 1,
    changed_files: 1,
    reused_files: 0,
    truncated: false,
    duration_ms: 1,
  },
};

const graph: KnowledgeGraph = {
  nodes: [{ path: note.path, title: note.title, tags: note.tags ?? [] }],
  edges: [],
};

const memoryIndex: MemoryIndex = {
  items: [],
  proposed: 0,
  approved: 0,
  archived: 0,
};

beforeEach(() => {
  mocked.listKnowledge.mockResolvedValue(index);
  mocked.getKnowledgeNote.mockResolvedValue(note);
  mocked.saveKnowledgeNote.mockImplementation((_spaceId, path, content) =>
    Promise.resolve({ ...note, path, content }),
  );
  mocked.deleteKnowledgeNote.mockResolvedValue(undefined);
  mocked.searchKnowledge.mockResolvedValue({ query: "sqlite", hits: [] });
  mocked.getKnowledgeGraph.mockResolvedValue(graph);
  mocked.moveKnowledgeNote.mockImplementation((_spaceId, _source, target) =>
    Promise.resolve({
      note: { ...note, path: target },
      updated_links: 2,
      backup_path: ".agentspace/backups/move",
    }),
  );
  mocked.importKnowledge.mockResolvedValue({
    created: 1,
    updated: 0,
    skipped: 0,
    backup_path: null,
  });
  mocked.listMemories.mockResolvedValue(memoryIndex);
  mocked.updateMemory.mockRejectedValue(new Error("not configured"));
  mocked.mergeMemories.mockRejectedValue(new Error("not configured"));
  mocked.pinKnowledgeNote.mockImplementation((_spaceId, path, pinned) =>
    Promise.resolve({ ...note, path, pinned }),
  );
  mocked.evaluateKnowledge.mockResolvedValue({
    results: [],
    mean_reciprocal_rank: 1,
    mean_recall_at_k: 1,
    limit: 5,
  });
});

describe("knowledge vault", () => {
  it("opens a Markdown note with properties, links and backlinks", async () => {
    const user = userEvent.setup();
    render(<KnowledgeView space={space} />);

    await user.click(await screen.findByRole("button", { name: /Storage decision/ }));

    expect(await screen.findByLabelText("Markdown source")).toHaveProperty("value", note.content);
    expect(screen.getByText("#architecture", { selector: ".knowledge__tag" })).toBeTruthy();
    expect(screen.getByText("status").parentElement?.textContent).toContain("accepted");
    expect(screen.getByRole("button", { name: /index\.md/ })).toBeTruthy();
  });

  it("saves edited Markdown and refreshes the live vault index", async () => {
    const user = userEvent.setup();
    render(<KnowledgeView space={space} />);
    await user.click(await screen.findByRole("button", { name: /Storage decision/ }));

    const editor = await screen.findByLabelText("Markdown source");
    await user.clear(editor);
    await user.type(editor, "# Changed");
    await user.click(screen.getByRole("button", { name: "Save note" }));

    await waitFor(() => {
      expect(mocked.saveKnowledgeNote).toHaveBeenCalledWith(
        "space-lab",
        "decisions/storage.md",
        "# Changed",
      );
    });
    expect(mocked.listKnowledge).toHaveBeenCalledTimes(2);
  });

  it("searches retrieval chunks and opens the cited note", async () => {
    const user = userEvent.setup();
    const result: KnowledgeSearch = {
      query: "sqlite",
      hits: [
        {
          path: note.path,
          title: note.title,
          heading: "Storage decision",
          excerpt: "Use SQLite WAL.",
          citation: "[[decisions/storage#Storage decision]]",
          score: 0.75,
          tags: ["architecture"],
        },
      ],
    };
    mocked.searchKnowledge.mockResolvedValue(result);
    render(<KnowledgeView space={space} />);

    await user.type(screen.getByLabelText("Search knowledge"), "sqlite");
    await user.click(screen.getByRole("button", { name: "Search" }));

    expect(await screen.findByText("[[decisions/storage#Storage decision]]")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: /Use SQLite WAL/ }));
    expect(mocked.getKnowledgeNote).toHaveBeenCalledWith("space-lab", note.path);
  });

  it("creates a safe Markdown note from the window", async () => {
    const user = userEvent.setup();
    render(<KnowledgeView space={space} />);

    await user.click(await screen.findByRole("button", { name: "New note" }));
    await user.clear(screen.getByLabelText("Note path"));
    await user.type(screen.getByLabelText("Note path"), "research/new.md");
    await user.type(screen.getByLabelText("Markdown source"), "# New research");
    await user.click(screen.getByRole("button", { name: "Save note" }));

    expect(mocked.saveKnowledgeNote).toHaveBeenCalledWith(
      "space-lab",
      "research/new.md",
      expect.stringContaining("# New research"),
    );
  });

  it("requires confirmation before deleting a note", async () => {
    const user = userEvent.setup();
    render(<KnowledgeView space={space} />);

    await user.click(await screen.findByRole("button", { name: /Storage decision/ }));
    await user.click(screen.getByRole("button", { name: "Delete note…" }));

    expect(mocked.deleteKnowledgeNote).not.toHaveBeenCalled();
    expect(screen.getByText(`Delete ${note.path}?`)).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Delete" }));

    expect(mocked.deleteKnowledgeNote).toHaveBeenCalledWith("space-lab", note.path);
  });

  it("shows unresolved links and filters the browser to orphans or a tag", async () => {
    const user = userEvent.setup();
    render(<KnowledgeView space={space} />);
    await screen.findByRole("button", { name: /Storage decision/ });

    expect(screen.getByText(/1 orphan · 1 unresolved link/)).toBeTruthy();
    await user.selectOptions(screen.getByLabelText("Show notes"), "orphans");
    expect(screen.queryByRole("button", { name: /Storage decision/ })).toBeNull();
    expect(screen.getByRole("button", { name: /Orphan/ })).toBeTruthy();

    await user.selectOptions(screen.getByLabelText("Show notes"), "all");
    await user.click(screen.getByRole("button", { name: /#architecture/ }));
    expect(screen.queryByRole("button", { name: /Orphan/ })).toBeNull();

    await user.click(screen.getByRole("button", { name: /Storage decision/ }));
    expect((await screen.findByTitle("No note has this name yet")).textContent).toContain("missing note");
  });

  it("pins the open note through the pin endpoint", async () => {
    const user = userEvent.setup();
    render(<KnowledgeView space={space} />);
    await user.click(await screen.findByRole("button", { name: /Storage decision/ }));

    await user.click(screen.getByRole("button", { name: "Pin note" }));

    expect(mocked.pinKnowledgeNote).toHaveBeenCalledWith("space-lab", note.path, true);
    expect(await screen.findByRole("button", { name: "Unpin note" })).toBeTruthy();
  });

  it("starts today's daily note under daily/ with a dated title", async () => {
    const user = userEvent.setup();
    render(<KnowledgeView space={space} />);
    await screen.findByRole("button", { name: /Storage decision/ });

    await user.click(screen.getByRole("button", { name: "Daily note" }));

    const date = new Date().toISOString().slice(0, 10);
    expect(screen.getByLabelText<HTMLInputElement>("Note path").value).toBe(`daily/${date}.md`);
    expect(screen.getByLabelText<HTMLTextAreaElement>("Markdown source").value).toContain(`# ${date}`);
  });

  it("shows a memory's provenance and merges a selection into one note", async () => {
    const user = userEvent.setup();
    const onOpenRun = vi.fn();
    const cacheMemory: MemoryItem = {
      path: "memory/inbox/abc.md",
      run_id: null,
      source: "agent",
      title: "Cache is unnecessary",
      goal: "",
      outcome: "No cache.",
      status: "approved",
      pinned: false,
      confidence: "high",
      tags: [],
      citations: [],
      merged_from: [],
      merged_into: null,
      created_at: "2026-09-16T00:00:00Z",
      updated_at: "2026-09-16T00:00:00Z",
    };
    const items: MemoryIndex = {
      items: [
        {
          path: "memory/runs/run-1.md",
          run_id: "run-1",
          source: "run",
          title: "Run memory: pick storage",
          goal: "pick storage",
          outcome: "SQLite.",
          status: "proposed",
          pinned: false,
          confidence: "agent-generated",
          tags: ["run-summary"],
          citations: ["[[decisions/storage#Storage decision]]"],
          merged_from: [],
          merged_into: null,
          created_at: "2026-09-16T00:00:00Z",
          updated_at: "2026-09-16T00:00:00Z",
        },
        cacheMemory,
      ],
      proposed: 1,
      approved: 1,
      archived: 0,
    };
    mocked.listMemories.mockResolvedValue(items);
    mocked.mergeMemories.mockResolvedValue({
      memory: { ...cacheMemory, path: "memory/merged/new.md", title: "Storage" },
      archived_paths: ["memory/runs/run-1.md", "memory/inbox/abc.md"],
      backup_path: ".agentspace/backups/merge",
    });
    render(<KnowledgeView space={space} onOpenRun={onOpenRun} />);

    await user.click(await screen.findByRole("tab", { name: /Memory inbox/ }));
    expect(await screen.findByText(/from a run · created/)).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Open run" }));
    expect(onOpenRun).toHaveBeenCalledWith("run-1");
    await user.click(screen.getByRole("button", { name: "[[decisions/storage#Storage decision]]" }));
    expect(mocked.getKnowledgeNote).toHaveBeenCalledWith("space-lab", "decisions/storage.md");

    await user.click(screen.getByRole("checkbox", { name: /Select Run memory/ }));
    await user.click(screen.getByRole("checkbox", { name: /Select Cache is unnecessary/ }));
    await user.type(screen.getByLabelText("Merged memory title"), "Storage");
    await user.click(screen.getByRole("button", { name: "Merge 2 selected" }));

    expect(mocked.mergeMemories).toHaveBeenCalledWith(
      "space-lab",
      ["memory/runs/run-1.md", "memory/inbox/abc.md"],
      "Storage",
    );
    expect(await screen.findByText(/Merged 2 memories into memory\/merged\/new\.md/)).toBeTruthy();
  });
});
