import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { parseDataFile, VISUALIZATION_SCHEMA, type ChartKind, type VisualizationSpec } from "../lib/visualization";

import { Chart } from "./Chart";

const data = parseDataFile("sales.csv", "month,revenue,cost\nJan,10,8\nFeb,14,9\n");
const base: VisualizationSpec = {
  $schema: VISUALIZATION_SCHEMA,
  title: "Sales",
  source: "sales.csv",
  chart: "bar",
  x: "month",
  y: ["revenue", "cost"],
  series: null,
  aggregate: "none",
  sort: "source",
  limit: 100,
};

let createdUrls = 0;
let clickedLinks = 0;

describe("charts", () => {
  beforeEach(() => {
    createdUrls = 0;
    clickedLinks = 0;
    vi.spyOn(URL, "createObjectURL").mockImplementation(() => {
      createdUrls += 1;
      return "blob:test";
    });
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => { clickedLinks += 1; });
  });

  afterEach(() => { vi.restoreAllMocks(); });

  it("draws every graphic chart and retains a readable table", () => {
    const { rerender } = render(<Chart data={data} spec={base} />);
    for (const kind of ["bar", "line", "area", "scatter", "pie", "metric"] satisfies ChartKind[]) {
      rerender(<Chart data={data} spec={{ ...base, chart: kind }} />);
      expect(screen.getByRole("img", { name: new RegExp(`${kind === "metric" ? "metric" : `${kind} chart`}: Sales`, "i") })).toBeDefined();
    }
    fireEvent.click(screen.getByRole("button", { name: "Show data" }));
    expect(screen.getByRole("table")).toBeDefined();
    expect(screen.getByRole("columnheader", { name: "revenue" })).toBeDefined();
  });

  it("exports both SVG and prepared CSV", () => {
    render(<Chart data={data} spec={base} />);
    fireEvent.click(screen.getByRole("button", { name: "Export SVG" }));
    fireEvent.click(screen.getByRole("button", { name: "Export CSV" }));
    expect(createdUrls).toBe(2);
    expect(clickedLinks).toBe(2);
  });
});
