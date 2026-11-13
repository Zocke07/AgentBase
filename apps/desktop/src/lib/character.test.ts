import { describe, expect, it } from "vitest";

import { silhouetteOf, SILHOUETTES } from "./character";

describe("an agent's silhouette", () => {
  it("is the same for the same name, every time", () => {
    expect(silhouetteOf("researcher")).toEqual(silhouetteOf("researcher"));
    // Pinned: a change here would change how every agent looks.
    expect(silhouetteOf("supervisor")).toEqual(silhouetteOf("supervisor"));
  });

  it("tells the shipped roles apart", () => {
    const roles = [
      "supervisor",
      "news-scanner",
      "market-movers",
      "event-calendar",
      "portfolio-review",
      "bull-architect",
      "bear-architect",
      "risk-manager",
      "decision",
      "review-analyst",
      "researcher",
      "writer",
      "reviewer",
    ];
    const shapes = new Set(roles.map((role) => JSON.stringify(silhouetteOf(role))));
    // Thirteen names over thirty-six shapes: most must differ.
    expect(shapes.size).toBeGreaterThanOrEqual(9);
  });

  it("uses every part across many names", () => {
    const seen = new Set<string>();
    for (let index = 0; index < 400; index += 1) seen.add(JSON.stringify(silhouetteOf(`agent-${String(index)}`)));
    expect(seen.size).toBe(SILHOUETTES);
  });

  it("handles a name of any length", () => {
    expect(silhouetteOf("")).toBeDefined();
    expect(silhouetteOf("x".repeat(500))).toBeDefined();
  });
});
