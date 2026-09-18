import { describe, expect, it } from "vitest";

import { forceLayout } from "./graphLayout";

describe("forceLayout", () => {
  it("places the same graph identically every time", () => {
    const ids = ["a", "b", "c", "d"];
    const edges = [["a", "b"], ["b", "c"]] as const;

    expect(forceLayout(ids, edges)).toEqual(forceLayout(ids, edges));
  });

  it("pulls linked notes closer than unlinked ones", () => {
    const ids = ["hub", "spoke", "loner"];
    const placed = forceLayout(ids, [["hub", "spoke"]]);
    const distance = (left: string, right: string) => {
      const a = placed.get(left);
      const b = placed.get(right);
      if (a === undefined || b === undefined) throw new Error("missing node");
      return Math.hypot(a.x - b.x, a.y - b.y);
    };

    expect(distance("hub", "spoke")).toBeLessThan(distance("hub", "loner"));
  });

  it("keeps every node, even one linked to nothing or to an unknown name", () => {
    const placed = forceLayout(["a", "b"], [["a", "ghost"]]);

    expect([...placed.keys()]).toEqual(["a", "b"]);
  });
});
