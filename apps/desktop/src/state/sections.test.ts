import type { NoteSummary, TextFileSummary } from "@agentbase/schemas";
import { describe, expect, it } from "vitest";

import { fileTitle, sectionOf, summaryGroup, summaryItems } from "./sections";

const note = (path: string, title: string, updatedAt = "2026-10-13T06:00:00Z"): NoteSummary => ({
  path,
  title,
  excerpt: "",
  tags: [],
  properties: {},
  links: [],
  backlinks: [],
  unresolved_links: [],
  pinned: false,
  updated_at: updatedAt,
});

const file = (path: string, updatedAt = "2026-10-13T06:00:00Z"): TextFileSummary => ({
  path,
  size: 100,
  updated_at: updatedAt,
});

describe("the two sections", () => {
  it("puts results in User Summary and the raw or technical files in Technical Details", () => {
    // What a person reads.
    expect(summaryGroup("decisions/2026-10-12.md")).toBe("Decisions");
    expect(summaryGroup("portfolio/review-2026-10-12.md")).toBe("Portfolio reviews");
    expect(summaryGroup("scores/review-2026-10.md")).toBe("Weekly reviews");
    expect(summaryGroup("alerts/2026-10-13-1100.md")).toBe("Market alerts");
    expect(summaryGroup("predictions/2026-10.xlsx")).toBe("Forecast workbooks");
    expect(summaryGroup("visualizations/pipeline.dashboard.json")).toBe("Charts and dashboards");
    expect(summaryGroup("visualizations/daily-change.viz.json")).toBe("Charts and dashboards");
    expect(summaryGroup("daily/2026-10-13.md")).toBe("Daily notes");
    expect(summaryGroup("knowledge/companies/micron.md")).toBe("Notes");
    // What the agents work from.
    for (const technical of [
      "raw/movers-2026-10-12.json",
      "raw/news-2026-10-12.jsonl",
      "theses/bull-2026-10-12.jsonl",
      "risk/checks-2026-10-12.json",
      "portfolio/computed.json",
      "portfolio/positions.csv",
      "predictions/forecasts.json",
      "config/watchlist.json",
      "memory/runs/run-1.md",
      "templates/daily.md",
      ".agentbase/backups/x/decisions/2026-10-12.md",
    ]) {
      expect(sectionOf(technical)).toBe("technical");
    }
  });

  it("lists results by group, newest first, with readable titles", () => {
    const items = summaryItems(
      [
        note("decisions/2026-10-09.md", "Decision, Oct 9"),
        note("decisions/2026-10-12.md", "Decision, Oct 12"),
        note("knowledge/companies/micron.md", "Micron"),
        note("memory/runs/run-1.md", "Run summary"),
      ],
      [file("predictions/2026-10.xlsx"), file("raw/movers-2026-10-12.json"), file("visualizations/daily-change.viz.json")],
    );

    expect(items.map((item) => [item.group, item.title])).toEqual([
      ["Decisions", "Decision, Oct 12"],
      ["Decisions", "Decision, Oct 9"],
      ["Forecast workbooks", "Forecasts for October 2026"],
      ["Charts and dashboards", "Daily change"],
      ["Notes", "Micron"],
    ]);
    expect(items[0]).toMatchObject({ kind: "note", date: "2026-10-12" });
    expect(items[2]).toMatchObject({ kind: "file", date: "2026-10" });
  });

  it("gives another space general groups, since the pipeline's stay in the default space", () => {
    expect(summaryGroup("decisions/2026-10-12.md", false)).toBe("Notes");
    expect(summaryGroup("alerts/2026-10-13-1100.md", false)).toBe("Notes");
    expect(summaryGroup("daily/2026-10-13.md", false)).toBe("Daily notes");
    expect(summaryGroup("reports/budget.xlsx", false)).toBe("Workbooks");
    expect(summaryGroup("visualizations/daily-change.viz.json", false)).toBe("Charts and dashboards");
    expect(summaryGroup("raw/movers-2026-10-12.json", false)).toBeNull();

    const items = summaryItems(
      [note("decisions/2026-10-12.md", "Decision, Oct 12"), note("daily/2026-10-13.md", "Oct 13")],
      [file("predictions/2026-10.xlsx")],
      false,
    );
    expect(items.map((item) => [item.group, item.title])).toEqual([
      ["Workbooks", "2026 10"],
      ["Daily notes", "Oct 13"],
      ["Notes", "Decision, Oct 12"],
    ]);
  });

  it("names a file by what it holds", () => {
    expect(fileTitle("predictions/2026-11.xlsx")).toBe("Forecasts for November 2026");
    expect(fileTitle("visualizations/prediction-accuracy.viz.json")).toBe("Prediction accuracy");
    expect(fileTitle("visualizations/pipeline.dashboard.json")).toBe("Pipeline");
    expect(fileTitle("exports/q3_summary.xlsx")).toBe("Q3 summary");
  });
});
