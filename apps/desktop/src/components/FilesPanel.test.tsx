import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../lib/api";
import { VISUALIZATION_SCHEMA } from "../lib/visualization";

import { FilesPanel, type OpenFile } from "./FilesPanel";

vi.mock("../lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof api>()),
  listFiles: vi.fn(),
  getFile: vi.fn(),
  writeFile: vi.fn(),
  deleteFile: vi.fn(),
}));

vi.mock("mermaid", () => ({
  default: {
    initialize: vi.fn(),
    render: vi.fn().mockResolvedValue({ svg: '<svg xmlns="http://www.w3.org/2000/svg"><text>diagram</text></svg>' }),
  },
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
  it("groups and filters files while keeping starter templates available", async () => {
    const user = userEvent.setup();
    mocked.listFiles.mockResolvedValue({
      files: [
        { path: "config/watchlist.json", size: 120, updated_at: "2026-09-19T00:00:00Z" },
        { path: "raw/market/prices.json", size: 2048, updated_at: "2026-09-20T00:00:00Z" },
        { path: "README.txt", size: 42, updated_at: "2026-09-18T00:00:00Z" },
      ],
    });
    render(<Both />);

    expect(await screen.findByRole("heading", { name: "config" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "raw" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Space root" })).toBeTruthy();
    // The runs' working data starts folded; the inputs a person keeps stay open.
    expect(screen.getByText("watchlist.json")).toBeTruthy();
    expect(screen.queryByText("prices.json")).toBeNull();
    await user.click(screen.getByRole("button", { name: "raw" }));
    expect(screen.getByText("prices.json")).toBeTruthy();
    expect(screen.getByText("market/ · JSON · 2.0 KB")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "raw" }));
    expect(screen.queryByText("prices.json")).toBeNull();

    // A search shows every match, folded or not.
    await user.type(screen.getByRole("searchbox", { name: "Filter agent files" }), "prices");
    expect(screen.queryByText("watchlist.json")).toBeNull();
    expect(screen.getByText("prices.json")).toBeTruthy();

    await user.selectOptions(screen.getByLabelText("Create from template"), "config/sources.json");
    expect(screen.getByLabelText<HTMLInputElement>("File path").value).toBe("config/sources.json");
  });

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

  it("identifies the open file and makes unsaved state visible", async () => {
    const user = userEvent.setup();
    render(<Both />);
    await user.click(await screen.findByRole("button", { name: /config\/watchlist\.json/ }));
    const text = await screen.findByLabelText("File contents");
    await waitFor(() => {
      expect((text as HTMLTextAreaElement).value).toBe('{"watchlist": []}');
    });

    expect(screen.getByRole("heading", { name: "watchlist.json" })).toBeTruthy();
    expect(screen.getByText("config/ · JSON")).toBeTruthy();
    expect(screen.getByText(/An illustrative six-company research list/)).toBeTruthy();
    expect(screen.getByText(/Every entry needs a ticker and sector/)).toBeTruthy();
    expect(screen.queryByText("Unsaved changes")).toBeNull();

    fireEvent.change(text, { target: { value: '{"watchlist": ["AAPL"]}' } });
    expect(screen.getByText("Unsaved changes")).toBeTruthy();
  });

  it("starts a new file from a template, and deletes one after a second click", async () => {
    const user = userEvent.setup();
    mocked.listFiles.mockResolvedValue({ files: [] });
    render(<Both />);

    await user.selectOptions(await screen.findByLabelText("Create from template"), "config/sources.json");
    expect(screen.getByLabelText<HTMLInputElement>("File path").value).toBe("config/sources.json");
    expect(screen.getByLabelText<HTMLTextAreaElement>("File contents").value).toContain("google_news_rss");
    await user.click(screen.getByRole("button", { name: "Save file" }));
    await waitFor(() => {
      expect(mocked.writeFile).toHaveBeenCalledWith(
        "space-lab",
        "config/sources.json",
        expect.stringContaining("query1.finance.yahoo.com"),
      );
    });

    // Saved: the editor now holds an existing file, which can be deleted.
    await user.click(await screen.findByRole("button", { name: "Delete…" }));
    expect(mocked.deleteFile).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Delete" }));
    await waitFor(() => {
      expect(mocked.deleteFile).toHaveBeenCalledWith("space-lab", "config/sources.json");
    });
    expect(await screen.findByText(/Pick an agent file on the left/)).toBeDefined();
  });
});

describe("charts, dashboards and diagrams", () => {
  const SALES_CSV = "day,revenue,cost\n2026-09-01,12,8\n2026-09-02,17,9\n";
  const SALES_CHART = JSON.stringify({
    $schema: VISUALIZATION_SCHEMA,
    title: "Sales",
    source: "data/sales.csv",
    chart: "line",
    x: "day",
    y: ["revenue"],
    series: null,
    aggregate: "none",
    sort: "source",
    limit: 250,
  });

  beforeEach(() => {
    mocked.listFiles.mockResolvedValue({
      files: [
        { path: "data/sales.csv", size: 60, updated_at: "2026-09-24T00:00:00Z" },
        { path: "visualizations/sales.viz.json", size: 200, updated_at: "2026-09-24T00:00:00Z" },
      ],
    });
    mocked.getFile.mockImplementation((_space, path) =>
      Promise.resolve({
        path,
        size: 60,
        updated_at: "2026-09-24T00:00:00Z",
        content: path.endsWith(".csv") ? SALES_CSV : SALES_CHART,
      }),
    );
  });

  it("draws a data file as a chart and saves it as a chart file an agent can read", async () => {
    const user = userEvent.setup();
    render(<Both />);

    // A saved chart is named for what it is in the list.
    expect(await screen.findByText("Chart · 200 B")).toBeTruthy();
    await user.click(await screen.findByRole("button", { name: /^data\/sales\.csv/ }));
    // A data file opens as text; the chart is one click away.
    await waitFor(() => {
      expect(screen.getByLabelText<HTMLTextAreaElement>("File contents").value).toBe(SALES_CSV);
    });
    await user.click(within(screen.getByRole("group", { name: "Show as" })).getByRole("button", { name: "Chart" }));
    expect(await screen.findByRole("img", { name: /line chart: sales/i })).toBeDefined();

    // The suggested name never replaces a chart the space already has.
    const target = screen.getByLabelText<HTMLInputElement>("Chart file path");
    expect(target.value).toBe("visualizations/sales-2.viz.json");
    fireEvent.change(target, { target: { value: "visualizations/revenue.viz.json" } });
    await user.click(screen.getByRole("button", { name: "Save chart" }));
    await waitFor(() => {
      expect(mocked.writeFile).toHaveBeenCalledWith(
        "space-lab",
        "visualizations/revenue.viz.json",
        expect.stringContaining(VISUALIZATION_SCHEMA),
      );
    });
    // The new chart opens, drawn.
    await waitFor(() => {
      expect(mocked.getFile).toHaveBeenCalledWith("space-lab", "visualizations/revenue.viz.json");
    });
  });

  it("opens a saved chart drawn, its settings editing the file's text", async () => {
    const user = userEvent.setup();
    render(<Both />);

    await user.click(await screen.findByRole("button", { name: /^visualizations\/sales\.viz\.json/ }));
    expect(await screen.findByRole("img", { name: "line chart: Sales" })).toBeDefined();
    expect(screen.queryByText("Unsaved changes")).toBeNull();

    await user.selectOptions(screen.getByLabelText("Chart"), "bar");
    expect(await screen.findByRole("img", { name: "bar chart: Sales" })).toBeDefined();
    expect(screen.getByText("Unsaved changes")).toBeTruthy();
    await user.click(within(screen.getByRole("group", { name: "Show as" })).getByRole("button", { name: "Text" }));
    expect(screen.getByLabelText<HTMLTextAreaElement>("File contents").value).toContain('"chart": "bar"');

    await user.click(screen.getByRole("button", { name: "Save chart" }));
    await waitFor(() => {
      expect(mocked.writeFile).toHaveBeenCalledWith(
        "space-lab",
        "visualizations/sales.viz.json",
        expect.stringContaining('"chart": "bar"'),
      );
    });
  });

  it("composes saved charts into a dashboard started from the template list", async () => {
    const user = userEvent.setup();
    render(<Both />);

    await user.selectOptions(await screen.findByLabelText("Create from template"), "dashboard");
    expect(screen.getByLabelText<HTMLInputElement>("File path").value).toBe("visualizations/dashboard.dashboard.json");
    expect(screen.getByText(/Saved charts side by side/)).toBeTruthy();
    await user.click(screen.getByRole("checkbox", { name: "visualizations/sales.viz.json" }));
    expect(await screen.findByRole("img", { name: "line chart: Sales" })).toBeDefined();

    await user.click(screen.getByRole("button", { name: "Save dashboard" }));
    await waitFor(() => {
      expect(mocked.writeFile).toHaveBeenCalledWith(
        "space-lab",
        "visualizations/dashboard.dashboard.json",
        expect.stringMatching(/agentbase:\/\/dashboard\/v1[\s\S]*visualizations\/sales\.viz\.json/),
      );
    });
  });

  it("starts a chart from the template list, drawn once its data file is chosen", async () => {
    const user = userEvent.setup();
    render(<Both />);

    await user.selectOptions(await screen.findByLabelText("Create from template"), "chart");
    expect(screen.getByText("Choose the data file this chart draws.")).toBeTruthy();
    await user.selectOptions(screen.getByLabelText("Data source"), "data/sales.csv");
    expect(await screen.findByRole("img", { name: "line chart: Chart" })).toBeDefined();
  });

  it("draws a Mermaid file beside its text", async () => {
    const user = userEvent.setup();
    render(<Both />);

    await user.selectOptions(await screen.findByLabelText("Create from template"), "diagram");
    expect(screen.getByLabelText<HTMLTextAreaElement>("Mermaid source").value).toContain("Supervisor");
    await user.click(screen.getByRole("button", { name: "Save diagram" }));
    await waitFor(() => {
      expect(mocked.writeFile).toHaveBeenCalledWith("space-lab", "visualizations/diagram.mmd", expect.stringContaining("flowchart LR"));
    });
  });

  it("says why a chart file it cannot draw is not drawn", async () => {
    const user = userEvent.setup();
    mocked.getFile.mockResolvedValue({
      path: "visualizations/sales.viz.json",
      size: 2,
      updated_at: "2026-09-24T00:00:00Z",
      content: "{}",
    });
    render(<Both />);

    await user.click(await screen.findByRole("button", { name: /^visualizations\/sales\.viz\.json/ }));
    expect((await screen.findByRole("alert")).textContent).toContain("not a chart AgentBase can draw");
  });
});
