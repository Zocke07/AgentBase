import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { twoAgentRun } from "../test/log";

import { STEP_SETTLES_MS, useMotionMode } from "./useMotionMode";

afterEach(() => {
  vi.useRealTimers();
});

describe("useMotionMode", () => {
  const events = twoAgentRun();

  it("settles a run as it opens, animates a step forward, and settles a jump or a step back", () => {
    const { result, rerender } = renderHook(({ cursor }) => useMotionMode(events, cursor), { initialProps: { cursor: 3 } });
    expect(result.current).toBe("settle");
    rerender({ cursor: 4 });
    expect(result.current).toBe("step");
    // The same cursor again is no new move: the mode stays what the move made it.
    rerender({ cursor: 4 });
    expect(result.current).toBe("step");
    rerender({ cursor: 3 });
    expect(result.current).toBe("settle");
    rerender({ cursor: events.length });
    expect(result.current).toBe("settle");
  });

  it("is at rest again once a step's motion is over", () => {
    vi.useFakeTimers();
    const { result, rerender } = renderHook(({ cursor }) => useMotionMode(events, cursor), { initialProps: { cursor: 3 } });
    rerender({ cursor: 4 });
    expect(result.current).toBe("step");
    act(() => {
      vi.advanceTimersByTime(STEP_SETTLES_MS - 50);
    });
    // A new step in time keeps the room moving.
    rerender({ cursor: 5 });
    act(() => {
      vi.advanceTimersByTime(STEP_SETTLES_MS - 50);
    });
    expect(result.current).toBe("step");
    act(() => {
      vi.advanceTimersByTime(100);
    });
    expect(result.current).toBe("settle");
  });

  it("never treats opening another run as a step, however close the cursors", () => {
    const other = events.map((event) => ({ ...event, run_id: "run-other" }));
    const { result, rerender } = renderHook(({ log, cursor }) => useMotionMode(log, cursor), { initialProps: { log: events, cursor: 3 } });
    rerender({ log: other, cursor: 4 });
    expect(result.current).toBe("settle");
    // The same cursor in another run is a new run too.
    rerender({ log: events, cursor: 4 });
    expect(result.current).toBe("settle");
  });
});
