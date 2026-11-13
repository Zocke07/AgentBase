import { describe, expect, it } from "vitest";

import { ANCHOR_GAP, placePanel, WINDOW_MARGIN, type Box } from "./anchor";

const VIEWPORT = { width: 800, height: 600 };
const PANEL = { width: 240, height: 200 };
const anchorAt = (top: number, left: number): Box => ({ top, left, width: 100, height: 28 });

describe("placing a floating panel", () => {
  it("opens under its anchor, lined up with the edge asked for", () => {
    const anchor = anchorAt(100, 300);
    expect(placePanel(anchor, PANEL, VIEWPORT, { side: "bottom", align: "start" })).toMatchObject({
      top: 100 + 28 + ANCHOR_GAP,
      left: 300,
      side: "bottom",
    });
    expect(placePanel(anchor, PANEL, VIEWPORT, { side: "bottom", align: "end" }).left).toBe(300 + 100 - 240);
    expect(placePanel(anchor, PANEL, VIEWPORT, { side: "bottom", align: "center" }).left).toBe(300 + 50 - 120);
  });

  it("flips above when there is no room below and more above", () => {
    const placed = placePanel(anchorAt(520, 300), PANEL, VIEWPORT, { side: "bottom", align: "start" });
    expect(placed.side).toBe("top");
    expect(placed.top).toBe(520 - ANCHOR_GAP - 200);
  });

  it("flips below when asked for above with no room there", () => {
    const placed = placePanel(anchorAt(40, 300), PANEL, VIEWPORT, { side: "top", align: "start" });
    expect(placed.side).toBe("bottom");
  });

  it("stays on its side when the other has even less room", () => {
    const tall = { width: 240, height: 580 };
    const placed = placePanel(anchorAt(200, 300), tall, VIEWPORT, { side: "bottom", align: "start" });
    expect(placed.side).toBe("bottom");
    // It cannot fit: it is told how much height it has, and stays on screen.
    expect(placed.maxHeight).toBe(600 - 228 - ANCHOR_GAP - WINDOW_MARGIN);
    expect(placed.top).toBeGreaterThanOrEqual(WINDOW_MARGIN);
  });

  it("slides back inside the window's left and right edges", () => {
    expect(placePanel(anchorAt(100, 740), PANEL, VIEWPORT, { side: "bottom", align: "start" }).left).toBe(
      800 - WINDOW_MARGIN - 240,
    );
    expect(placePanel(anchorAt(100, 0), PANEL, VIEWPORT, { side: "bottom", align: "end" }).left).toBe(WINDOW_MARGIN);
  });

  it("keeps a panel wider than the window against the left margin", () => {
    const wide = { width: 900, height: 100 };
    expect(placePanel(anchorAt(100, 300), wide, VIEWPORT, { side: "bottom", align: "center" }).left).toBe(WINDOW_MARGIN);
  });
});
