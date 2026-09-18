import { describe, expect, it } from "vitest";

import { fuzzyFilter, fuzzyScore } from "./fuzzy";

describe("fuzzy matching", () => {
  it("prefers an exact substring, then a prefix, over a scattered subsequence", () => {
    const exact = fuzzyScore("stor", "Storage decision") ?? Number.NEGATIVE_INFINITY;
    const inside = fuzzyScore("stor", "Cold storage") ?? Number.NEGATIVE_INFINITY;
    const scattered = fuzzyScore("stor", "Sort the order") ?? Number.NEGATIVE_INFINITY;

    expect(exact).toBeGreaterThan(inside);
    expect(inside).toBeGreaterThan(scattered);
  });

  it("rejects a query whose characters are not all present in order", () => {
    expect(fuzzyScore("xyz", "Storage decision")).toBeNull();
    expect(fuzzyScore("noisiced", "decision")).toBeNull();
  });

  it("returns everything for an empty query and orders matches best first", () => {
    const notes = ["daily/2026-09-18", "decisions/storage", "research/sqlite"];

    expect(fuzzyFilter("", notes, (note) => note).map((match) => match.item)).toEqual(notes);
    expect(fuzzyFilter("dec sto", notes, (note) => note)[0]?.item).toBe("decisions/storage");
  });
});
