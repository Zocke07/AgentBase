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
 *
 * `headView` is the same fold at the head, kept even while the user is scrubbed
 * back. It costs one `reduce` per event and answers the questions that are
 * about the run rather than about where the viewer is standing — what the
 * picker's badge should say, whether the run finished while being watched —
 * and it makes returning to the head a lookup instead of a refold. While
 * `following`, `view` *is* `headView`, the same object.
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
  /** The fold up to `cursor` — what is on screen. */
  readonly view: RunView;
  /** The fold up to the head — what the run is, wherever the viewer stands. */
  readonly headView: RunView;
  readonly connection: ConnectionStatus;
  /**
   * How many times an event arrived with a `seq` more than one past the head.
   * The server re-reads from SQLite on any anomaly so this should stay zero;
   * the event is kept either way and the count is shown, because a "no gaps"
   * contract that is checked nowhere is one nobody would notice breaking.
   */
  readonly gaps: number;

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
  headView: EMPTY_RUN,
  connection: { kind: "idle" } as ConnectionStatus,
  gaps: 0,
};

export const useRunStore = create<RunStoreState>()((set, get) => ({
  ...INITIAL,

  open: (runId) => {
    set({ ...INITIAL, runId, connection: { kind: "connecting" } });
  },

  appendEvent: (event) => {
    const { events, cursor, following, headView } = get();
    const head = events.at(-1)?.seq ?? 0;

    // A resumed stream re-reads from its cursor, and a fresh EventSource
    // re-reads from the beginning, so the same event legitimately arrives twice.
    // Dropping anything at or below the head makes both harmless, and is why the
    // client never has to reason about *why* a duplicate turned up.
    if (event.seq <= head) return;

    const nextEvents = [...events, event];
    const gaps = get().gaps + (event.seq > head + 1 ? 1 : 0);
    const nextHead = reduce(headView, event);

    // Scrubbed back: keep collecting, leave the view where the user put it.
    // Yanking the cursor to the head because an event arrived would make the
    // scrubber unusable on a live run.
    if (!following) {
      set({ events: nextEvents, headView: nextHead, gaps });
      return;
    }

    set({
      events: nextEvents,
      cursor: cursor + 1,
      view: nextHead,
      headView: nextHead,
      gaps,
    });
  },

  loadHistory: (events) => {
    const ordered = [...events].sort((left, right) => left.seq - right.seq);
    const headView = reduceAll(ordered);
    set({
      events: ordered,
      cursor: ordered.length,
      following: true,
      view: headView,
      headView,
    });
  },

  setCursor: (cursor) => {
    const state = get();
    const target = Math.max(0, Math.min(cursor, state.events.length));

    // Folding forward from where we are, rather than from the start, is what
    // keeps a live run linear. Folding backwards has to start over, because the
    // reducer has no inverse — and nor should it: an undo path would be a second
    // definition of what each event means. The head itself is already folded.
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
