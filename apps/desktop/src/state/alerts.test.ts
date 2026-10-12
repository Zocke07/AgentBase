import { afterEach, describe, expect, it } from "vitest";

import { marketAlert } from "../test/alerts";

import { alertBatches, moveBasis, moveLabel, pendingNotices, readRaised, writeRaised } from "./alerts";

afterEach(() => {
  localStorage.clear();
});

describe("market alerts in the window", () => {
  it("groups one check's alerts together, newest check first", () => {
    const batches = alertBatches([
      marketAlert({ id: "a3", batch_id: "b2", symbol: "AVGO" }),
      marketAlert({ id: "a1", batch_id: "b1" }),
      marketAlert({ id: "a2", batch_id: "b1", symbol: "^IXIC", instrument: "index" }),
    ]);
    expect(batches.map((batch) => [batch.batchId, batch.alerts.map((alert) => alert.symbol)])).toEqual([
      ["b2", ["AVGO"]],
      ["b1", ["MU", "^IXIC"]],
    ]);
  });

  it("says what moved and from what", () => {
    expect(moveLabel(marketAlert())).toBe("MU down 5.5%");
    expect(moveBasis(marketAlert())).toBe("since the previous close");
    expect(moveBasis(marketAlert({ reference: "window", window_minutes: 15 }))).toBe("in 15 minutes");
    expect(moveBasis(marketAlert({ reference: "regular_close" }))).toBe("since today's close, after hours");
  });

  it("raises each alert once, then its explanation once it is done", () => {
    const running = [marketAlert()];
    const [first] = pendingNotices(running, new Set());
    expect(first).toEqual({ key: "alert:batch-1", title: "Market alert", body: "MU down 5.5%. Looking for the reason." });
    expect(pendingNotices(running, new Set(["alert:batch-1"]))).toEqual([]);

    const done = [marketAlert({ explanation_status: "done", explanation: "A broker downgrade." })];
    expect(pendingNotices(done, new Set(["alert:batch-1"]))).toEqual([
      { key: "why:batch-1", title: "Why MU moved", body: "A broker downgrade." },
    ]);
  });

  it("remembers the notices it raised, and tells a first look from an empty one", () => {
    expect(readRaised()).toBeNull();
    writeRaised(["alert:batch-1"]);
    expect(readRaised()).toEqual(new Set(["alert:batch-1"]));
    writeRaised([]);
    expect(readRaised()).toEqual(new Set());
  });
});
