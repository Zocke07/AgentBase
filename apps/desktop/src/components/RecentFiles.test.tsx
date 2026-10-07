import type { NoteSummary } from "@agentbase/schemas";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../lib/api";

import { RecentFiles } from "./RecentFiles";

vi.mock("../lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof api>()),
  listFiles: vi.fn(),
}));

const mocked = vi.mocked(api);

function noteAt(path: string, title: string, updated: string): NoteSummary {
  return { path, title, excerpt: "", tags: [], properties: {}, links: [], backlinks: [], unresolved_links: [], pinned: false, updated_at: updated };
}

const NOW = new Date("2026-10-07T12:00:00Z");

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
  mocked.listFiles.mockResolvedValue({
    files: [
      { path: "theses/bull-2026-10-06.jsonl", size: 0, updated_at: "2026-10-07T11:09:12Z" },
      { path: "config/watchlist.json", size: 138, updated_at: "2026-09-30T08:00:00Z" },
    ],
  });
});

afterEach(() => {
  vi.useRealTimers();
});

describe("RecentFiles", () => {
  it("puts notes and agent files together, newest first, and leaves run memories out", async () => {
    const notes = [
      noteAt("decisions/2026-10-06.md", "DECISION TABLE", "2026-10-07T11:12:06Z"),
      noteAt("memory/runs/run-1.md", "Run memory: Decide", "2026-10-07T11:12:29Z"),
      noteAt("portfolio/review-2026-10-06.md", "Portfolio review", "2026-10-06T23:08:00Z"),
    ];
    render(<RecentFiles spaceId="space-lab" notes={notes} onOpenNote={vi.fn()} onOpenFile={vi.fn()} />);

    const list = await screen.findByTestId("recent-files");
    await waitFor(() => {
      expect(within(list).getAllByRole("button").map((row) => row.dataset.path)).toEqual([
        "decisions/2026-10-06.md",
        "theses/bull-2026-10-06.jsonl",
        "portfolio/review-2026-10-06.md",
        "config/watchlist.json",
      ]);
    });
    expect(list.textContent).toContain("DECISION TABLE");
    expect(list.textContent).not.toContain("Run memory");
  });

  it("opens a note as a note and a data file as an agent file", async () => {
    const onOpenNote = vi.fn();
    const onOpenFile = vi.fn();
    render(
      <RecentFiles
        spaceId="space-lab"
        notes={[noteAt("decisions/2026-10-06.md", "DECISION TABLE", "2026-10-07T11:12:06Z")]}
        onOpenNote={onOpenNote}
        onOpenFile={onOpenFile}
      />,
    );

    const list = await screen.findByTestId("recent-files");
    await userEvent.click(within(list).getByRole("button", { name: /2026-10-06\.md/ }));
    expect(onOpenNote).toHaveBeenCalledWith("decisions/2026-10-06.md");
    await userEvent.click(await within(list).findByRole("button", { name: /bull-2026-10-06\.jsonl/ }));
    expect(onOpenFile).toHaveBeenCalledWith("theses/bull-2026-10-06.jsonl");
  });
});
