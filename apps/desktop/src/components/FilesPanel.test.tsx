import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../lib/api";

import { FilesPanel, type OpenFile } from "./FilesPanel";

vi.mock("../lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof api>()),
  listFiles: vi.fn(),
  getFile: vi.fn(),
  writeFile: vi.fn(),
  deleteFile: vi.fn(),
}));

const mocked = vi.mocked(api);

beforeEach(() => {
  mocked.listFiles.mockResolvedValue({
    files: [{ path: "config/watchlist.json", size: 120, updated_at: "2026-09-19T00:00:00Z" }],
  });
  mocked.getFile.mockResolvedValue({
    path: "config/watchlist.json",
    size: 120,
    updated_at: "2026-09-19T00:00:00Z",
    content: '{"watchlist": []}',
  });
  mocked.writeFile.mockImplementation((_space, path, content) =>
    Promise.resolve({ path, size: content.length, updated_at: "2026-09-19T00:00:01Z", content }),
  );
  mocked.deleteFile.mockResolvedValue(undefined);
});

/** Both halves at once, the way the Knowledge view mounts them, sharing the open file. */
function Both({ onChanged }: { onChanged?: () => void }) {
  const [open, setOpen] = useState<OpenFile | null>(null);
  return (
    <>
      <FilesPanel spaceId="space-lab" part="list" open={open} onOpen={setOpen} />
      <FilesPanel spaceId="space-lab" part="editor" open={open} onOpen={setOpen} onChanged={onChanged} />
    </>
  );
}

describe("data files", () => {
  it("lists the files, opens one, and saves an edit", async () => {
    const user = userEvent.setup();
    const onChanged = vi.fn();
    render(<Both onChanged={onChanged} />);

    await user.click(await screen.findByRole("button", { name: /config\/watchlist\.json/ }));
    const text = await screen.findByLabelText("File contents");
    await waitFor(() => {
      expect((text as HTMLTextAreaElement).value).toBe('{"watchlist": []}');
    });

    fireEvent.change(text, { target: { value: '{"watchlist": [{"ticker": "AAPL"}]}' } });
    await user.click(screen.getByRole("button", { name: "Save file" }));

    await waitFor(() => {
      expect(mocked.writeFile).toHaveBeenCalledWith("space-lab", "config/watchlist.json", '{"watchlist": [{"ticker": "AAPL"}]}');
    });
    expect(onChanged).toHaveBeenCalled();
  });

  it("refuses to save JSON that does not parse, before asking the sidecar", async () => {
    const user = userEvent.setup();
    render(<Both />);
    await user.click(await screen.findByRole("button", { name: /config\/watchlist\.json/ }));
    const text = await screen.findByLabelText("File contents");
    await waitFor(() => {
      expect((text as HTMLTextAreaElement).value).toBe('{"watchlist": []}');
    });

    fireEvent.change(text, { target: { value: "{not json" } });
    await user.click(screen.getByRole("button", { name: "Save file" }));

    expect(screen.getByRole("alert").textContent).toContain("Not valid JSON");
    expect(mocked.writeFile).not.toHaveBeenCalled();
  });

  it("starts a new file from a template, and deletes one after a second click", async () => {
    const user = userEvent.setup();
    mocked.listFiles.mockResolvedValue({ files: [] });
    render(<Both />);

    await user.click(await screen.findByRole("button", { name: "config/sources.json" }));
    expect(screen.getByLabelText<HTMLInputElement>("File path").value).toBe("config/sources.json");
    expect(screen.getByLabelText<HTMLTextAreaElement>("File contents").value).toContain("google_news_rss");
    await user.click(screen.getByRole("button", { name: "Save file" }));
    await waitFor(() => {
      expect(mocked.writeFile).toHaveBeenCalledWith("space-lab", "config/sources.json", expect.stringContaining("stooq"));
    });

    // Saved: the editor now holds an existing file, which can be deleted.
    await user.click(await screen.findByRole("button", { name: "Delete…" }));
    expect(mocked.deleteFile).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Delete" }));
    await waitFor(() => {
      expect(mocked.deleteFile).toHaveBeenCalledWith("space-lab", "config/sources.json");
    });
    expect(await screen.findByText(/Pick a file on the left/)).toBeDefined();
  });
});
