import { describe, expect, it } from "vitest";

import { clockDate, formatDuration } from "./format";

describe("formatDuration", () => {
  it.each([
    [0, "0s"],
    [27_000, "27s"],
    [92_000, "1m 32s"],
    [3_600_000, "1h 0m"],
    [5_025_000, "1h 23m"],
  ])("renders %i ms as %s", (ms, expected) => {
    expect(formatDuration(ms)).toBe(expected);
  });
});

describe("clockDate", () => {
  it("shows the day as well as the time, so yesterday's run is not today's", () => {
    /* The picker used to show `14:32:05` for a run from last week. */
    const rendered = clockDate("2026-09-10T12:00:05Z");
    expect(rendered).toMatch(/2026-09-1[01]/);
    expect(rendered).toMatch(/\d\d:\d\d/);
  });

  it("renders nonsense as a placeholder rather than throwing", () => {
    expect(clockDate("not a date")).toBe("-");
  });
});
