import type {
  KnowledgeGraph,
  KnowledgeIndex,
  KnowledgeNote,
  KnowledgeSearch,
  MemoryIndex,
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
  updated_at: "2026-09-15T00:00:00Z",
  content: "---\ntags: [architecture]\nstatus: accepted\n---\n# Storage decision\n\nUse **SQLite WAL**. See [[research/sqlite]].",
};

const index: KnowledgeIndex = {
  notes: [note],
  stats: { note_count: 1, link_count: 1, tag_count: 1, chunk_count: 1 },
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
    expect(screen.getByText("#architecture")).toBeTruthy();
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
});
