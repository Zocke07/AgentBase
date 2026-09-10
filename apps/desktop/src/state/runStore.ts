import type { Event } from "@agentspace/schemas";
import { create } from "zustand";

import { EMPTY_RUN, reduce, reduceAll, type RunView } from "./reducer";


/**
 * The run store: an event array, a cursor into it, and the fold of the prefix.
 *
 * This shape is what makes BUILD_SPEC §5 Phase 7's acceptance criterion
 * structural rather than a promise. The criterion is that "replaying a completed
 * run produces pixel-identical UI state to what was shown live", and the usual
 * way to fail it is to have two code paths — a live one that accumulates state
 * as events arrive, and a replay one that rebuilds it from history — which agree
 * until one of them gains a feature.
 *
 * Here there is one path. `view` is always `reduceAll(events.slice(0, cursor))`.
 * Live is that with `cursor` pinned to the end; replay is the same fold with a
 * smaller cursor. Scrubbing backwards is not a different renderer, it is a
 * smaller number.
 *
 * The fold is computed on write rather than on read, and computed *forward* when
 * the cursor only advances, so a long run stays linear instead of re-folding the
 * whole log on every arriving event.
 */

export type ConnectionStatus =
  | { kind: "idle" }
  | { kind: "connecting" }
  | { kind: "live" }
  /** The stream ended because the run did. Not an error, and not retried. */
  | { kind: "closed"; reason: "run-finished" }
  | { kind: "error"; message: string };

export interface RunStoreState {
  readonly runId: string | null;
  /** Every event received for this run, ordered by `seq`, no gaps, no repeats. */
  readonly events: readonly Event[];
  /** How many events are applied to `view`. Equals `events.length` when live. */
  readonly cursor: number;
  /** Whether the cursor tracks the head. False once the user scrubs back. */
  readonly following: boolean;
  readonly view: RunView;
  readonly connection: ConnectionStatus;

  open: (runId: string) => void;
  appendEvent: (event: Event) => void;
  loadHistory: (events: readonly Event[]) => void;
  setCursor: (cursor: number) => void;
  follow: () => void;
  setConnection: (connection: ConnectionStatus) => void;
  reset: () => void;
}

const INITIAL = {
  runId: null,
  events: [] as readonly Event[],
  cursor: 0,
  following: true,
  view: EMPTY_RUN,
  connection: { kind: "idle" } as ConnectionStatus,
};

export const useRunStore = create<RunStoreState>()((set, get) => ({
  ...INITIAL,

  open: (runId) => {
    set({ ...INITIAL, runId, connection: { kind: "connecting" } });
  },

  appendEvent: (event) => {
    const { events, cursor, following, view } = get();
    const head = events.at(-1)?.seq ?? 0;

    // A resumed stream re-reads from its cursor, and a fresh EventSource
    // re-reads from the beginning, so the same event legitimately arrives twice.
    // Dropping anything at or below the head makes both harmless, and is why the
    // client never has to reason about *why* a duplicate turned up.
    if (event.seq <= head) return;

    const nextEvents = [...events, event];

    // Scrubbed back: keep collecting, leave the view where the user put it.
    // Yanking the cursor to the head because an event arrived would make the
    // scrubber unusable on a live run.
    if (!following) {
      set({ events: nextEvents });
      return;
    }

    set({
      events: nextEvents,
      cursor: cursor + 1,
      view: reduce(view, event),
    });
  },

  loadHistory: (events) => {
    const ordered = [...events].sort((left, right) => left.seq - right.seq);
    set({
      events: ordered,
      cursor: ordered.length,
      following: true,
      view: reduceAll(ordered),
    });
  },

  setCursor: (cursor) => {
    const state = get();
    const target = Math.max(0, Math.min(cursor, state.events.length));

    // Folding forward from where we are, rather than from the start, is what
    // keeps a live run linear. Folding backwards has to start over, because the
    // reducer has no inverse — and nor should it: an undo path would be a second
    // definition of what each event means.
    const view =
      target >= state.cursor
        ? reduceAll(state.events.slice(state.cursor, target), state.view)
        : reduceAll(state.events.slice(0, target));

    set({ cursor: target, view, following: target === state.events.length });
  },

  follow: () => {
    get().setCursor(get().events.length);
  },

  setConnection: (connection) => {
    set({ connection });
  },

  reset: () => {
    set({ ...INITIAL });
  },
}));
