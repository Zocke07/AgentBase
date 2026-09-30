import type { MemoryIndex, MemoryItem } from "@agentbase/schemas";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { MemoryInbox } from "./MemoryInbox";

const proposed: MemoryItem = {
  path: "memory/runs/run-1.md",
  run_id: "run-1",
  source: "run",
  title: "Run memory: choose storage",
  goal: "Choose storage",
  outcome: "SQLite kept the deployment simple.",
  status: "proposed",
  pinned: false,
  confidence: "agent-generated",
  tags: ["run-summary"],
  citations: [],
  merged_from: [],
  merged_into: null,
  created_at: "2026-09-30T10:00:00Z",
  updated_at: "2026-09-30T10:00:00Z",
};

const kept: MemoryItem = {
  ...proposed,
  path: "memory/inbox/kept.md",
  run_id: null,
  source: "agent",
  title: "Keep SQLite",
  status: "approved",
};

const dismissed: MemoryItem = {
  ...proposed,
  path: "memory/inbox/dismissed.md",
  run_id: null,
  source: "agent",
  title: "Discard Redis",
  status: "archived",
};

const memories: MemoryIndex = {
  items: [proposed, kept, dismissed],
  proposed: 1,
  approved: 1,
  archived: 1,
};

function props() {
  return {
    memories,
    busy: false,
    forgetAsked: null,
    selection: [],
    mergeTitle: "",
    onOpen: vi.fn(),
    onOpenRun: vi.fn(),
    onCurate: vi.fn(),
    onAskForget: vi.fn(),
    onForget: vi.fn(),
    onToggleSelect: vi.fn(),
    onMergeTitle: vi.fn(),
    onMerge: vi.fn(),
  };
}

describe("MemoryInbox", () => {
  it("starts as a plain-language review queue with one clear decision", async () => {
    const callbacks = props();
    render(<MemoryInbox {...callbacks} />);

    expect(screen.getByText(/Keep useful summaries so later runs can find them/)).toBeTruthy();
    expect(screen.getByText(proposed.title)).toBeTruthy();
    expect(screen.queryByText(kept.title)).toBeNull();
    expect(screen.queryByText(dismissed.title)).toBeNull();
    expect(screen.queryByRole("checkbox")).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "Keep for future runs" }));
    expect(callbacks.onCurate).toHaveBeenCalledWith(proposed, { status: "approved" });

    await userEvent.click(screen.getByRole("button", { name: "Kept 1" }));
    expect(screen.getByText(kept.title)).toBeTruthy();
    expect(screen.queryByText(proposed.title)).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(callbacks.onCurate).toHaveBeenCalledWith(kept, { status: "archived" });
  });

  it("keeps organization and destructive actions out of the primary flow", async () => {
    const callbacks = props();
    render(<MemoryInbox {...callbacks} />);

    const more = screen.getByText("More actions").closest("details");
    expect(more?.open).toBe(false);
    await userEvent.click(screen.getByText("More actions"));
    expect(more?.open).toBe(true);
    expect(screen.getByRole("button", { name: "Edit full note" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Always include" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Delete permanently…" })).toBeTruthy();

    await userEvent.click(screen.getByText("Organize"));
    await userEvent.click(screen.getByRole("button", { name: "Combine memories" }));
    expect(screen.getByText(kept.title)).toBeTruthy();
    expect(screen.getByText(dismissed.title)).toBeTruthy();
    expect(screen.getAllByRole("checkbox")).toHaveLength(2);
  });
});
