import { describe, expect, it } from "vitest";

import {
  DASHBOARD_SCHEMA,
  VISUALIZATION_SCHEMA,
  dashboardJson,
  defaultVisualization,
  parseDashboardSpec,
  parseDataFile,
  parseVisualizationSpec,
  prepareChart,
  type VisualizationSpec,
  visualizationJson,
} from "./visualization";

describe("visualization data", () => {
  it("parses quoted CSV, infers columns and prepares multiple series", () => {
    const data = parseDataFile(
      "sales.csv",
      'day,revenue,cost,note\n2026-09-01,"1,200",800,"launch, east"\n2026-09-02,1500,900,steady\n',
    );

    expect(data.columns).toEqual([
      { name: "day", kind: "date" },
      { name: "revenue", kind: "number" },
      { name: "cost", kind: "number" },
      { name: "note", kind: "text" },
    ]);
    const spec = { ...defaultVisualization("sales.csv", data), y: ["cost"] };
    const chart = prepareChart(data, spec);
    expect(chart.labels).toEqual(["2026-09-01", "2026-09-02"]);
    expect(chart.series[0]?.points.map((point) => point.value)).toEqual([800, 900]);
  });

  it("uses the sole array in a JSON object and groups a named series", () => {
    const data = parseDataFile(
      "sales.json",
      JSON.stringify({ rows: [
        { month: "Jan", region: "East", sales: 2 },
        { month: "Jan", region: "East", sales: 3 },
        { month: "Jan", region: "West", sales: 7 },
      ] }),
    );
    const spec: VisualizationSpec = {
      $schema: VISUALIZATION_SCHEMA,
      title: "Sales",
      source: "sales.json",
      chart: "bar",
      x: "month",
      y: ["sales"],
      series: "region",
      aggregate: "sum",
      sort: "source",
      limit: 100,
    };

    const chart = prepareChart(data, spec);
    expect(chart.series.map((series) => [series.name, series.points[0]?.value])).toEqual([
      ["East", 5],
      ["West", 7],
    ]);
  });

  it("finds a table nested in an API-shaped JSON document", () => {
    const data = parseDataFile("response.json", JSON.stringify({ data: { result: { items: [{ x: "A", value: 3 }] } } }));
    expect(data.rows).toEqual([{ x: "A", value: 3 }]);
  });

  it("parses JSON lines and refuses malformed saved contracts", () => {
    const data = parseDataFile("events.jsonl", '{"kind":"read","count":2}\n{"kind":"write","count":1}\n');
    expect(data.rows).toHaveLength(2);
    expect(() => parseVisualizationSpec('{"title":"missing schema"}')).toThrow(/not an AgentBase visualization/);
    expect(() => parseDashboardSpec(JSON.stringify({ $schema: DASHBOARD_SCHEMA, columns: 4 }))).toThrow(/not an AgentBase dashboard/);
  });

  it("accepts the versioned dashboard contract", () => {
    expect(parseDashboardSpec(JSON.stringify({
      $schema: DASHBOARD_SCHEMA,
      title: "Operations",
      visualizations: ["visualizations/spend.viz.json"],
      columns: 2,
    })).title).toBe("Operations");
  });

  it("loads legacy saved contracts and serializes them as AgentBase", () => {
    const visualization = parseVisualizationSpec(JSON.stringify({
      $schema: "agentspace://visualization/v1",
      title: "Sales",
      source: "sales.csv",
      chart: "bar",
      x: "month",
      y: ["revenue"],
      series: null,
      aggregate: "none",
      sort: "source",
      limit: 100,
    }));
    const dashboard = parseDashboardSpec(JSON.stringify({
      $schema: "agentspace://dashboard/v1",
      title: "Operations",
      visualizations: ["visualizations/sales.viz.json"],
      columns: 2,
    }));

    expect(visualization.$schema).toBe(VISUALIZATION_SCHEMA);
    expect(dashboard.$schema).toBe(DASHBOARD_SCHEMA);
    expect(visualizationJson(visualization)).toContain(VISUALIZATION_SCHEMA);
    expect(dashboardJson(dashboard)).toContain(DASHBOARD_SCHEMA);
    expect(visualizationJson(visualization)).not.toContain("agentspace://visualization");
    expect(dashboardJson(dashboard)).not.toContain("agentspace://dashboard");
  });
});
