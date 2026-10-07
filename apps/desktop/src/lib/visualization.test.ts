import { describe, expect, it } from "vitest";

import {
  DASHBOARD_SCHEMA,
  VISUALIZATION_SCHEMA,
  blankVisualization,
  dashboardJson,
  defaultVisualization,
  fileKind,
  parseDashboardSpec,
  parseDataFile,
  parseVisualizationSpec,
  prepareChart,
  type VisualizationSpec,
  uniquePath,
  visualizationJson,
} from "./visualization";

describe("agent files Knowledge can draw", () => {
  it("knows a file's kind by its name", () => {
    expect(fileKind("visualizations/pipeline.dashboard.json")).toBe("dashboard");
    expect(fileKind("visualizations/daily-change.viz.json")).toBe("chart");
    expect(fileKind("visualizations/flow.MMD")).toBe("diagram");
    expect(fileKind("visualizations/flow.mermaid")).toBe("diagram");
    expect(fileKind("raw/prices/summary.csv")).toBe("data");
    expect(fileKind("theses/bull-2026-10-06.jsonl")).toBe("data");
    expect(fileKind("config/watchlist.json")).toBe("data");
    expect(fileKind("notes/readme.txt")).toBe("text");
  });

  it("names a new file after the ones already there, whatever their case", () => {
    const taken = ["visualizations/Sales.viz.json", "visualizations/sales-2.viz.json", "visualizations/flow.mmd"];
    expect(uniquePath("visualizations/sales.viz.json", taken)).toBe("visualizations/sales-3.viz.json");
    expect(uniquePath("visualizations/flow.mmd", taken)).toBe("visualizations/flow-2.mmd");
    expect(uniquePath("visualizations/new.dashboard.json", taken)).toBe("visualizations/new.dashboard.json");
    expect(uniquePath("notes", ["notes"])).toBe("notes-2");
  });

  it("keeps a chart without data a valid chart file", () => {
    expect(parseVisualizationSpec(visualizationJson(blankVisualization("Chart")))).toMatchObject({ source: "", chart: "table" });
  });
});

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

  it("reads a flat settings object as one row per field, so each figure gets its own bar", () => {
    /* config/limits.json came out as a single row, and the first chart used
       one of its numbers as the category: one bar group labelled "10". */
    const data = parseDataFile(
      "config/limits.json",
      JSON.stringify({ max_position_pct: 10, max_sector_pct: 30, max_daily_loss_pct: 3 }),
    );

    expect(data.columns).toEqual([
      { name: "field", kind: "text" },
      { name: "value", kind: "number" },
    ]);
    const spec = defaultVisualization("config/limits.json", data);
    expect(spec).toMatchObject({ chart: "bar", x: "field", y: ["value"] });
    expect(prepareChart(data, spec).labels).toEqual(["max_position_pct", "max_sector_pct", "max_daily_loss_pct"]);
  });

  it("flattens nested settings into dotted fields, and shows text values as a table", () => {
    const data = parseDataFile(
      "config/sources.json",
      JSON.stringify({ news: { google: { url_template: "https://news.google.com/rss", auth: "none" } } }),
    );

    expect(data.rows).toEqual([
      { field: "news.google.url_template", value: "https://news.google.com/rss" },
      { field: "news.google.auth", value: "none" },
    ]);
    expect(defaultVisualization("config/sources.json", data).chart).toBe("table");
    expect(parseDataFile("empty.json", "{}").rows).toEqual([]);
  });

  it("reads an object keyed by name as one row per key", () => {
    const data = parseDataFile(
      "quotes.json",
      JSON.stringify({
        AAPL: { last: 190.5, volume: 100, range_52w: [150, 200] },
        MSFT: { last: 410, volume: 80, range_52w: [350, 450] },
      }),
    );

    expect(data.rows).toEqual([
      { key: "AAPL", last: 190.5, volume: 100, range_52w: "[150,200]" },
      { key: "MSFT", last: 410, volume: 80, range_52w: "[350,450]" },
    ]);
    expect(defaultVisualization("quotes.json", data)).toMatchObject({ chart: "bar", x: "key", y: ["last", "volume"] });
  });

  it("charts the pipeline's rows by a short label, not by an ID or a timestamp they all share", () => {
    const movers = parseDataFile(
      "raw/movers-2026-09-29.json",
      JSON.stringify([
        { ticker: "AAPL", as_of: "2026-09-29T20:00:00Z", source: "stooq.com", last: 190, prev_close: 188 },
        { ticker: "MSFT", as_of: "2026-09-29T20:00:00Z", source: "stooq.com", last: 410, prev_close: 415 },
      ]),
    );
    expect(defaultVisualization("raw/movers-2026-09-29.json", movers)).toMatchObject({
      chart: "bar",
      x: "ticker",
      y: ["last", "prev_close"],
    });

    const theses = parseDataFile(
      "theses/bull-2026-09-29.jsonl",
      [
        { pred_id: "5b0c8f5e-6a0e-4a53-9a55-5c6f8f1e2d11", as_of: "2026-09-29T21:00:00Z", ticker: "AAPL", confidence: 0.55 },
        { pred_id: "8c1d9e6f-7b1f-4b64-8b66-6d7f9f2e3e22", as_of: "2026-09-29T21:00:00Z", ticker: "MSFT", confidence: 0.6 },
      ]
        .map((row) => JSON.stringify(row))
        .join("\n"),
    );
    expect(defaultVisualization("theses/bull-2026-09-29.jsonl", theses).x).toBe("ticker");
  });

  it("averages a first chart whose category repeats, and counts the rows a plain chart leaves out", () => {
    /* Two AAPL theses drew as one bar: the second row was dropped without a word. */
    const theses = parseDataFile(
      "theses.csv",
      "ticker,horizon_days,confidence\nAAPL,1,0.52\nAAPL,5,0.58\nNVDA,3,0.55\nNVDA,7,0.61\nTSM,5,0.5\n",
    );
    const spec = defaultVisualization("theses.csv", theses);
    expect(spec.aggregate).toBe("average");
    const averaged = prepareChart(theses, spec);
    const confidence = averaged.series.find((series) => series.name === "confidence");
    expect(confidence?.points.map((point) => Number(point.value.toFixed(4)))).toEqual([0.55, 0.58, 0.5]);
    expect(averaged).toMatchObject({ sourceRows: 5, repeated: 0 });

    expect(prepareChart(theses, { ...spec, aggregate: "none" }).repeated).toBe(2);
    const movers = parseDataFile("movers.csv", "ticker,last\nAAPL,1\nMSFT,2\n");
    expect(defaultVisualization("movers.csv", movers).aggregate).toBe("none");
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
