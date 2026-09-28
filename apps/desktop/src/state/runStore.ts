import type { Event } from "@agentbase/schemas";
import { create } from "zustand";

import { EMPTY_RUN, reduce, reduceAll, type RunView } from "./reducer";


/**
 * Run store: event array, cursor, and folded prefix.
 *
 * `view` always folds `events.slice(0, cursor)`: live ends at the head and
 * replay uses an earlier cursor, sharing one rendering path. Fold arrivals
 * incrementally; retain `headView` while scrubbed back for run-level questions.
 */

export type ConnectionStatus =
  | { kind: "idle" }
  | { kind: "connecting" }
  | { kind: "live" }
  /** Stream ended with the run; not an error and never retried. */
  | { kind: "closed"; reason: "run-finished" }
  | { kind: "error"; message: string };

export interface RunStoreState {
  readonly runId: string | null;
  /** Received events, ordered by `seq` without gaps or repeats. */
  readonly events: readonly Event[];
  /** Events applied to `view`; equals `events.length` when live. */
  readonly cursor: number;
  /** Whether the cursor tracks the head; false after scrubbing back. */
  readonly following: boolean;
  /** Fold through `cursor`, shown on screen. */
  readonly view: RunView;
  /** Fold through the head, regardless of viewer position. */
  readonly headView: RunView;
  readonly connection: ConnectionStatus;
  /** Events arriving more than one `seq` beyond head; should remain zero. */
  readonly gaps: number;

  /** Switch with history atomically, never showing an empty run. */
  open: (runId: string, history?: readonly Event[]) => void;
  /** One event. The same as `appendEvents([event])`. */
  appendEvent: (event: Event) => void;
  /** Batch-fold events in one update so token bursts render once. */
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
      // Resumed or fresh EventSource streams can redeliver head-or-earlier events.
      if (event.seq <= head) continue;

      if (event.seq > head + 1) gaps += 1;
      head = event.seq;
      accepted.push(event);
      headView = reduce(headView, event);
    }

    if (accepted.length === 0) return;

    const nextEvents = [...events, ...accepted];

    // Continue collecting while preserving the scrubbed view.
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

    // Fold forward incrementally; refold backward because reducer events lack
    // inverses. The head is already folded.
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
