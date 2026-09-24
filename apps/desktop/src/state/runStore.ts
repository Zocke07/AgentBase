import type { Event } from "@agentbase/schemas";
import { create } from "zustand";

import { EMPTY_RUN, reduce, reduceAll, type RunView } from "./reducer";


/**
 * The run store: an event array, a cursor into it, and the fold of the prefix.
 *
 * `view` is always `reduceAll(events.slice(0, cursor))`. Live is that with
 * the cursor at the end; replay is the same fold with a smaller cursor, so
 * there is one rendering path, not two that agree until one gains a feature.
 * The fold advances incrementally as events arrive. `headView` is the fold at
 * the head, kept while scrubbed back, for the questions that are about the
 * run rather than about where the viewer stands.
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
  /** The fold up to `cursor`: what is on screen. */
  readonly view: RunView;
  /** The fold up to the head: what the run is, wherever the viewer stands. */
  readonly headView: RunView;
  readonly connection: ConnectionStatus;
  /** Events that arrived more than one `seq` past the head. Should stay zero; shown if not. */
  readonly gaps: number;

  /** Switch to a run with its history, in one update, so switching never shows an empty run. */
  open: (runId: string, history?: readonly Event[]) => void;
  /** One event. The same as `appendEvents([event])`. */
  appendEvent: (event: Event) => void;
  /** A batch, folded in one update, so a burst of `llm.token`s is one render. */
  appendEvents: (batch: readonly Event[]) => void;
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
  headView: EMPTY_RUN,
  connection: { kind: "idle" } as ConnectionStatus,
  gaps: 0,
};

export const useRunStore = create<RunStoreState>()((set, get) => ({
  ...INITIAL,

  open: (runId, history = []) => {
    const ordered = [...history].sort((left, right) => left.seq - right.seq);
    const headView = reduceAll(ordered);
    set({
      ...INITIAL,
      runId,
      events: ordered,
      cursor: ordered.length,
      view: headView,
      headView,
      connection: { kind: "connecting" },
    });
  },

  appendEvent: (event) => {
    get().appendEvents([event]);
  },

  appendEvents: (batch) => {
    const { events, cursor, following } = get();
    let { headView, gaps } = get();
    let head = events.at(-1)?.seq ?? 0;
    const accepted: Event[] = [];

    for (const event of batch) {
      // A resume or a fresh EventSource can redeliver; anything at or below the head is dropped.
      if (event.seq <= head) continue;

      if (event.seq > head + 1) gaps += 1;
      head = event.seq;
      accepted.push(event);
      headView = reduce(headView, event);
    }

    if (accepted.length === 0) return;

    const nextEvents = [...events, ...accepted];

    // Scrubbed back: keep collecting, leave the view where the user put it.
    if (!following) {
      set({ events: nextEvents, headView, gaps });
      return;
    }

    set({
      events: nextEvents,
      cursor: cursor + accepted.length,
      view: headView,
      headView,
      gaps,
    });
  },

  setCursor: (cursor) => {
    const state = get();
    const target = Math.max(0, Math.min(cursor, state.events.length));

    // Forward folds continue from here; backward folds start over, because the
    // reducer has no inverse and an undo path would be a second definition of
    // each event. The head is already folded.
    const view =
      target === state.events.length
        ? state.headView
        : target >= state.cursor
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
