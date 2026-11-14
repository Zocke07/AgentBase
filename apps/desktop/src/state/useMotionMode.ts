import type { Event } from "@agentbase/schemas";
import { useEffect, useState } from "react";

import { motionMode, type MotionMode } from "./timeline";

/**
 * How long a step's motion lasts: the longest entrance (the bouncy spring,
 * 520 ms) with room to spare. After that the room is at rest.
 */
export const STEP_SETTLES_MS = 700;

interface Seen {
  readonly run: string | null;
  readonly cursor: number;
  readonly mode: MotionMode;
}

/**
 * Whether the room is moving through a step the office may animate, or at
 * rest, where whatever appears or changes does so at once (brief 7.8,
 * decision D1). Transport: it depends on where the cursor was and on the
 * clock, not on the log, so it goes on the stage as `data-motion`, which the
 * identity test leaves out.
 *
 * A move of the cursor within a run is a step or a jump (`motionMode`);
 * another run is never a step. The run and cursor seen last are kept in
 * state and compared during render, React's pattern for a value derived
 * from a change of props: the first render after a move already carries the
 * right mode. A step lasts `STEP_SETTLES_MS`; after it, a desk hovered open,
 * the office switched to or a window resized does not animate as if a step
 * had just happened. The timer only ends motion: it removes nothing drawn.
 */
export function useMotionMode(events: readonly Event[], cursor: number): MotionMode {
  const run = events[0]?.run_id ?? null;
  const [seen, setSeen] = useState<Seen>({ run, cursor, mode: "settle" });
  let current = seen;
  if (seen.run !== run || seen.cursor !== cursor) {
    current = { run, cursor, mode: seen.run === run ? motionMode(events, seen.cursor, cursor) : "settle" };
    setSeen(current);
  }

  const stepping = current.mode === "step";
  useEffect(() => {
    if (!stepping) return undefined;
    const timer = window.setTimeout(() => {
      setSeen((now) => (now.run === run && now.cursor === cursor ? { ...now, mode: "settle" } : now));
    }, STEP_SETTLES_MS);
    return () => {
      window.clearTimeout(timer);
    };
  }, [stepping, run, cursor]);

  return current.mode;
}
