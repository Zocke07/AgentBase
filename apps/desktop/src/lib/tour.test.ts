import { describe, expect, it } from "vitest";

import { place } from "./tour";

const viewport = { width: 800, height: 600 };

describe("the tour card's place", () => {
  it("sits beside a target in the rail", () => {
    expect(place({ top: 100, left: 8, width: 44, height: 40 }, viewport, 300)).toEqual({ top: 100, left: 64 });
  });

  it("stays wholly inside the window, however far down its target was measured", () => {
    // A target measured below the window (a scroller still easing) once put
    // the card out of sight, Next and all.
    const spot = place({ top: 1400, left: 120, width: 600, height: 300 }, viewport, 320);
    const top = spot?.top ?? Number.NaN;
    expect(top).toBeGreaterThanOrEqual(16);
    expect(top + 320).toBeLessThanOrEqual(600 - 16);
  });

  it("goes above a wide target near the bottom, rather than over it", () => {
    const spot = place({ top: 420, left: 120, width: 600, height: 100 }, viewport, 200);
    expect(spot?.top).toBe(420 - 200 - 12);
  });

  it("is centred when there is no target", () => {
    expect(place(null, viewport, 200)).toBeNull();
  });
});
