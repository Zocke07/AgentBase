import type { SpaceResponse } from "@agentspace/schemas";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../lib/api";
import { VISUALIZATION_SCHEMA } from "../lib/visualization";

import { VisualizationView } from "./VisualizationView";

vi.mock("../lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof api>()),
  listFiles: vi.fn(),
  getFile: vi.fn(),
  writeFile: vi.fn(),
}));

vi.mock("mermaid", () => ({
  default: {
    initialize: vi.fn(),
    render: vi.fn().mockResolvedValue({ svg: '<svg xmlns="http://www.w3.org/2000/svg"><text>diagram</text></svg>' }),
  },
}));

const mocked = vi.mocked(api);
const space: SpaceResponse = {
  id: "space-lab",
  name: "Lab",
  description: "",
  provider: null,
  model: "model",
  created_at: "2026-09-24T00:00:00Z",
  updated_at: "2026-09-24T00:00:00Z",
  folder: "/spaces/lab",
  is_default: false,
};

const files = [
  { path: "data/sales.csv", size: 60, updated_at: "2026-09-24T00:00:00Z" },
  { path: "visualizations/sales.viz.json", size: 200, updated_at: "2026-09-24T00:00:00Z" },
];

beforeEach(() => {
  mocked.listFiles.mockResolvedValue({ files });
  mocked.getFile.mockImplementation((_space, path) => {
    if (path.endsWith(".csv")) {
      return Promise.resolve({ path: "data/sales.csv", size: 60, updated_at: "2026-09-24T00:00:00Z", content: "day,revenue,cost\n2026-09-01,12,8\n2026-09-02,17,9\n" });
    }
    return Promise.resolve({
      path: "visualizations/sales.viz.json",
      size: 200,
      updated_at: "2026-09-24T00:00:00Z",
      content: JSON.stringify({
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
      }),
    });
  });
  mocked.writeFile.mockImplementation((_space, path, content) => Promise.resolve({ path, size: content.length, updated_at: "2026-09-24T00:00:01Z", content }));
});

describe("visualization workspace", () => {
  it("infers a chart from a data file and saves an agent-readable spec", async () => {
    const user = userEvent.setup();
    render(<VisualizationView space={space} active />);

    await user.click(await screen.findByRole("button", { name: "data/sales.csv" }));
    expect(await screen.findByRole("img", { name: /line chart: sales/i })).toBeDefined();
    expect(screen.getAllByText("revenue").length).toBeGreaterThan(0);

    fireEvent.change(screen.getByLabelText("Visualization path"), { target: { value: "visualizations/revenue.viz.json" } });
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => {
      expect(mocked.writeFile).toHaveBeenCalledWith(
        "space-lab",
        "visualizations/revenue.viz.json",
        expect.stringContaining(VISUALIZATION_SCHEMA),
      );
    });
  });

  it("opens a saved chart and creates a Mermaid file", async () => {
    const user = userEvent.setup();
    render(<VisualizationView space={space} active />);

    await user.click(await screen.findByRole("button", { name: "visualizations/sales.viz.json" }));
    expect(await screen.findByRole("img", { name: "line chart: Sales" })).toBeDefined();

    await user.click(screen.getByRole("button", { name: "New diagram" }));
    expect(screen.getByLabelText<HTMLTextAreaElement>("Mermaid source").value).toContain("Supervisor");
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => {
      expect(mocked.writeFile).toHaveBeenCalledWith(
        "space-lab",
        "visualizations/agent-workflow.mmd",
        expect.stringContaining("flowchart LR"),
      );
    });
  });

  it("composes saved charts into a persistent dashboard", async () => {
    const user = userEvent.setup();
    render(<VisualizationView space={space} active />);

    await screen.findByRole("button", { name: "visualizations/sales.viz.json" });
    await user.click(screen.getByRole("button", { name: "New dashboard" }));
    await user.click(screen.getByRole("checkbox", { name: "visualizations/sales.viz.json" }));
    expect(await screen.findByRole("img", { name: "line chart: Sales" })).toBeDefined();
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => {
      expect(mocked.writeFile).toHaveBeenCalledWith(
        "space-lab",
        "visualizations/dashboard.dashboard.json",
        expect.stringContaining("agentspace://dashboard/v1"),
      );
    });
  });
});
