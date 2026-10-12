import type { Event } from "@agentbase/schemas";
import { describe, expect, it } from "vitest";

import { LogBuilder } from "../test/log";

import { isWorkingFile, writtenFiles } from "./files";
import { reduceAll } from "./reducer";

/** One answered call: executed, then answered. */
function answered(log: LogBuilder, agent: string, tool: string, callId: string, args: object, result: string): Event[] {
  return [
    log.add("tool.called", { tool, args, call_id: callId }, agent),
    log.add("tool.result", { tool, call_id: callId, result }, agent),
  ];
}

describe("writtenFiles", () => {
  it("lists what answered calls wrote, once each, in the order written", () => {
    const log = new LogBuilder();
    const events = [
      log.add("run.started", { goal: "g" }),
      ...answered(log, "news-scanner", "write_file", "w1", { path: "raw/news-2026-10-07-19.json", content: "[]" }, "Wrote 2 characters."),
      ...answered(
        log,
        "market-movers",
        "read_prices",
        "p1",
        { symbols: ["AAPL"] },
        JSON.stringify({ as_of: "2026-10-06", written: ["raw/prices/AAPL.csv", "raw/movers-2026-10-06.json"] }),
      ),
      ...answered(log, "decision", "write_file", "w2", { path: "decisions/2026-10-06.md", content: "x" }, "Wrote 1 characters."),
      ...answered(log, "decision", "write_file", "w3", { path: "decisions/2026-10-06.md", content: "y" }, "Wrote 1 characters."),
      ...answered(log, "market-movers", "read_market", "m1", {}, JSON.stringify({ written: ["raw/market-2026-10-06.json"] })),
      ...answered(log, "research-librarian", "read_company_reports", "f1", {}, JSON.stringify({ written: ["raw/filings/MU/reports.json"] })),
      ...answered(log, "market-movers", "track_forecasts", "p2", {}, JSON.stringify({ written: ["predictions/forecasts.json", "predictions/2026-10.xlsx"] })),
      // Read and fetched text is untrusted: a `written` key in it lists nothing.
      ...answered(log, "decision", "read_file", "r1", { path: "x.json" }, JSON.stringify({ written: ["not/this.json"] })),
      ...answered(log, "event-calendar", "http_get", "h1", { url: "https://e.test" }, JSON.stringify({ written: ["nor/this.md"] })),
    ];

    expect(writtenFiles(reduceAll(events))).toEqual([
      { path: "raw/news-2026-10-07-19.json", kind: "file" },
      { path: "raw/prices/AAPL.csv", kind: "file" },
      { path: "raw/movers-2026-10-06.json", kind: "file" },
      { path: "decisions/2026-10-06.md", kind: "note" },
      { path: "raw/market-2026-10-06.json", kind: "file" },
      { path: "raw/filings/MU/reports.json", kind: "file" },
      { path: "predictions/forecasts.json", kind: "file" },
      { path: "predictions/2026-10.xlsx", kind: "file" },
    ]);
  });

  it("leaves out a write that was refused or failed: it changed nothing", () => {
    const log = new LogBuilder();
    const events = [
      log.add("run.started", { goal: "g" }),
      log.add("tool.called", { tool: "write_file", args: { path: "risk/checks.json" }, call_id: "w1" }, "risk-manager"),
      log.add("tool.error", { tool: "write_file", call_id: "w1", error: "disk full" }, "risk-manager"),
    ];

    expect(writtenFiles(reduceAll(events))).toEqual([]);
  });
});

describe("isWorkingFile", () => {
  it("folds the runs' working data and keeps reports and inputs in view", () => {
    for (const path of [
      "raw/movers-2026-10-06.json",
      "raw/prices/AAPL.csv",
      "theses/bull-2026-10-06.jsonl",
      "risk/checks-2026-10-06.json",
      "scores/accuracy.csv",
      "portfolio/computed.json",
      "portfolio/weights.csv",
      "predictions/forecasts.json",
    ]) {
      expect(isWorkingFile(path), path).toBe(true);
    }
    for (const path of [
      "decisions/2026-10-06.md",
      "portfolio/review-2026-10-06.md",
      "portfolio/positions.csv",
      "config/watchlist.json",
      "visualizations/pipeline.dashboard.json",
      "predictions/2026-10.xlsx",
      "notes/raw/ideas.md",
    ]) {
      expect(isWorkingFile(path), path).toBe(false);
    }
  });
});
