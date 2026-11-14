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

  it("never gives two series the same colour: six are drawn, and Show data lists the rest", () => {
    const wide = parseDataFile("wide.csv", "month,a,b,c,d,e,f,g\nJan,1,2,3,4,5,6,7\nFeb,2,3,4,5,6,7,8\n");
    const { container } = render(<Chart data={wide} spec={{ ...base, chart: "line", y: ["a", "b", "c", "d", "e", "f", "g"] }} />);
    const strokes = [...container.querySelectorAll("path.viz-chart__line")].map((line) => line.getAttribute("stroke"));
    expect(strokes).toHaveLength(6);
    expect(new Set(strokes).size).toBe(6);
    expect(screen.getByRole("note").textContent).toContain("Show data lists all 7");
  });

  it("folds a pie's smaller slices into Other past six", () => {
    const shares = parseDataFile("shares.csv", "name,value\nA,40\nB,20\nC,10\nD,8\nE,6\nF,5\nG,4\nH,3\n");
    const { container } = render(<Chart data={shares} spec={{ ...base, chart: "pie", x: "name", y: ["value"] }} />);
    const slices = container.querySelectorAll("path.viz-chart__mark");
    expect(slices).toHaveLength(6);
    expect(container.textContent).toContain("Other (3)");
  });

  it("labels the value axis in round steps", () => {
    const limits = parseDataFile("limits.csv", "field,value\nmax_position_pct,10\nmax_sector_pct,30\nmax_daily_loss_pct,3\n");
    const { container } = render(<Chart data={limits} spec={{ ...base, x: "field", y: ["value"] }} />);

    const ticks = [...container.querySelectorAll("text.viz-chart__axis-label")].map((node) => node.textContent);
    expect(ticks).toEqual(expect.arrayContaining(["0", "10", "20", "30"]));
    expect(ticks).not.toContain("7.5");
    expect(ticks).not.toContain("22.5");
  });

  it("keeps bars a readable width when there are few categories", () => {
    /* One category and two series drew two bars each a third of the chart wide. */
    const one = parseDataFile("one.csv", "name,max_sector_pct,max_daily_loss_pct\nlimits,30,3\n");
    const { container } = render(<Chart data={one} spec={{ ...base, x: "name", y: ["max_sector_pct", "max_daily_loss_pct"] }} />);

    const widths = [...container.querySelectorAll("rect.viz-chart__mark")].map((node) => Number(node.getAttribute("width")));
    expect(widths).toHaveLength(2);
    for (const width of widths) expect(width).toBeLessThanOrEqual(56);
  });

  it("names every series in full in the legend, wrapping it rather than cutting names short", () => {
    const names = ["max_position_pct", "max_sector_pct", "max_daily_loss_pct", "max_single_name_pct", "max_gross_exposure_pct"];
    const wide = parseDataFile("wide.csv", `name,${names.join(",")}\nlimits,10,30,3,5,120\n`);
    const { container } = render(<Chart data={wide} spec={{ ...base, x: "name", y: names }} />);

    const legend = [...container.querySelectorAll("text.viz-chart__legend")];
    expect(legend.map((node) => node.textContent)).toEqual(names);
    const rows = new Set(legend.map((node) => node.parentElement?.getAttribute("transform")?.split(",")[1]));
    expect(rows.size).toBeGreaterThan(1);
  });

  it("says how many rows it leaves out when several share a category", () => {
    const repeated = parseDataFile("theses.csv", "ticker,confidence\nAAPL,0.52\nAAPL,0.58\nNVDA,0.55\n");
    const { rerender } = render(<Chart data={repeated} spec={{ ...base, x: "ticker", y: ["confidence"] }} />);

    expect(screen.getByText(/1 row shares its ticker with an earlier row and is not drawn/)).toBeDefined();
    rerender(<Chart data={repeated} spec={{ ...base, x: "ticker", y: ["confidence"], aggregate: "average" }} />);
    expect(screen.queryByText(/is not drawn/)).toBeNull();
    expect(screen.getByText(/2 groups from 3 rows · average · bar/)).toBeDefined();
  });

  it("exports both SVG and prepared CSV", () => {
    render(<Chart data={data} spec={base} />);
    fireEvent.click(screen.getByRole("button", { name: "Export SVG" }));
    fireEvent.click(screen.getByRole("button", { name: "Export CSV" }));
    expect(createdUrls).toBe(2);
    expect(clickedLinks).toBe(2);
  });
});
