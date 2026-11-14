import { describe, expect, it } from "vitest";

import { sameData } from "./equal";

describe("sameData", () => {
  it("compares primitives, arrays and plain objects by what they hold", () => {
    expect(sameData(1, 1)).toBe(true);
    expect(sameData(Number.NaN, Number.NaN)).toBe(true);
    expect(sameData("a", "b")).toBe(false);
    expect(sameData(null, null)).toBe(true);
    expect(sameData(null, {})).toBe(false);
    expect(sameData({ a: [1, { b: "c" }], d: null }, { a: [1, { b: "c" }], d: null })).toBe(true);
    expect(sameData({ a: [1, { b: "c" }] }, { a: [1, { b: "x" }] })).toBe(false);
    expect(sameData([1, 2], [1, 2, 3])).toBe(false);
    expect(sameData([], {})).toBe(false);
  });

  it("tells a missing key from one that holds undefined", () => {
    expect(sameData({ a: undefined }, { b: undefined })).toBe(false);
    expect(sameData({ a: 1 }, { a: 1, b: 2 })).toBe(false);
  });
});
