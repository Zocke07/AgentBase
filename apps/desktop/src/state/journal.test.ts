import type { NoteSummary } from "@agentbase/schemas";
import { describe, expect, it } from "vitest";

import { dayHeading, journalDays, journalEntries, journalKinds, shortDay } from "./journal";

function noteAt(path: string, updated: string, title = path): NoteSummary {
  return { path, title, excerpt: "", updated_at: updated };
}

describe("journalEntries", () => {
  it("collects every dated report, newest first, a month's report above its days", () => {
    const entries = journalEntries([
      noteAt("portfolio/review-2026-10-05.md", "2026-10-06T23:03:00Z"),
      noteAt("decisions/2026-10-05.md", "2026-10-06T23:20:00Z"),
      noteAt("decisions/2026-10-06.md", "2026-10-07T23:20:00Z"),
      noteAt("portfolio/review-2026-10-06.md", "2026-10-07T23:03:00Z"),
      noteAt("scores/review-2026-10.md", "2026-10-11T10:30:00Z"),
      noteAt("scores/review-2026-09.md", "2026-09-27T10:30:00Z"),
      noteAt("daily/2026-10-06.md", "2026-10-06T09:00:00Z"),
      noteAt("research/2026-10-06-chip-supply.md", "2026-10-06T12:00:00Z", "Chip supply"),
    ]);

    expect(entries.map((entry) => entry.path)).toEqual([
      "scores/review-2026-10.md",
      // Within a day, the newest write first: the decision ends the chain.
      "decisions/2026-10-06.md",
      "portfolio/review-2026-10-06.md",
      "research/2026-10-06-chip-supply.md",
      "daily/2026-10-06.md",
      "decisions/2026-10-05.md",
      "portfolio/review-2026-10-05.md",
      "scores/review-2026-09.md",
    ]);
    expect(entries.map((entry) => entry.kind)).toEqual([
      "Weekly review",
      "Decision",
      "Portfolio review",
      "Note",
      "Daily note",
      "Decision",
      "Portfolio review",
      "Weekly review",
    ]);
    expect(entries[0]?.date).toBe("2026-10");
    expect(entries[1]?.date).toBe("2026-10-06");
  });

  it("leaves out run memories, templates, undated notes and impossible dates", () => {
    const entries = journalEntries([
      noteAt("memory/runs/2026-10-06-run.md", "2026-10-07T00:00:00Z"),
      noteAt("templates/daily-2026-01-01.md", "2026-10-07T00:00:00Z"),
      noteAt("companies/AAPL.md", "2026-10-07T00:00:00Z"),
      noteAt("notes/2026-13-01.md", "2026-10-07T00:00:00Z"),
      noteAt("notes/2026-09-31.md", "2026-10-07T00:00:00Z"),
      // The date is in the folder name, not the file's.
      noteAt("2026-10-06/summary.md", "2026-10-07T00:00:00Z"),
    ]);

    expect(entries).toEqual([]);
  });
});

describe("journalDays", () => {
  it("groups one date's reports together, in order", () => {
    const days = journalDays(
      journalEntries([
        noteAt("decisions/2026-10-06.md", "2026-10-07T23:20:00Z"),
        noteAt("portfolio/review-2026-10-06.md", "2026-10-07T23:03:00Z"),
        noteAt("decisions/2026-10-05.md", "2026-10-06T23:20:00Z"),
      ]),
    );

    expect(days.map((day) => [day.date, day.entries.map((entry) => entry.kind)])).toEqual([
      ["2026-10-06", ["Decision", "Portfolio review"]],
      ["2026-10-05", ["Decision"]],
    ]);
  });
});

describe("journalKinds", () => {
  it("lists the kinds present, the pipeline's reports first", () => {
    const entries = journalEntries([
      noteAt("research/2026-10-06-chip-supply.md", "2026-10-06T12:00:00Z"),
      noteAt("decisions/2026-10-06.md", "2026-10-07T23:20:00Z"),
      noteAt("scores/review-2026-10.md", "2026-10-11T10:30:00Z"),
    ]);

    expect(journalKinds(entries)).toEqual(["Decision", "Weekly review", "Note"]);
  });
});

describe("dates", () => {
  it("names a day in the viewer's calendar, whatever the time zone", () => {
    // Parsed as a local date: "2026-10-06" is never the 5th west of UTC.
    expect(dayHeading("2026-10-06")).toBe(
      new Date(2026, 9, 6).toLocaleDateString(undefined, {
        weekday: "long",
        day: "numeric",
        month: "long",
        year: "numeric",
      }),
    );
    expect(dayHeading("2026-10")).toBe(new Date(2026, 9, 1).toLocaleDateString(undefined, { month: "long", year: "numeric" }));
    expect(shortDay("2026-10")).toContain("All of");
  });
});

describe("market alerts in the journal", () => {
  it("names an alert's explanation for what it is", () => {
    const [entry] = journalEntries([noteAt("alerts/2026-10-13-1100.md", "2026-10-13T15:03:00Z")]);
    expect(entry?.kind).toBe("Market alert");
    expect(entry?.date).toBe("2026-10-13");
  });
});
