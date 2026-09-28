import type { Run } from "@agentbase/schemas";
import { create } from "zustand";

import * as api from "../lib/api";
import type { RunOrigin } from "../lib/api";

/**
 * Newest-first `runs` table shared by Home and Runs picker; reload when stale.
 * Rows are snapshots; an open run's status comes from the store fold. Key by
 * space.
 */
export interface RunListState {
  readonly runs: readonly Run[];
  /** Runs' space; `undefined` selects all. */
  readonly spaceId: string | undefined;
  /** Starting origin filter; `undefined` selects all. */
  readonly origin: RunOrigin | undefined;
  /** Last requested row count; `loadMore` increases it. */
  readonly limit: number;
  readonly error: string | null;
  readonly loading: boolean;
  readonly loaded: boolean;
  load: () => Promise<void>;
  ensure: () => void;
  /** Ask for another page and re-read. */
  loadMore: () => void;
  setSpace: (spaceId: string) => void;
  /** Filter by origin or all; reload from first page. */
  setOrigin: (origin: RunOrigin | undefined) => void;
  reset: () => void;
}

/** How many runs the list asks for at a time. */
const PAGE = 50;

const NO_RUNS: readonly Run[] = [];

let token = 0;

export const useRunList = create<RunListState>()((set, get) => ({
  runs: NO_RUNS,
  spaceId: undefined,
  origin: undefined,
  limit: PAGE,
  error: null,
  loading: false,
  loaded: false,

  load: async () => {
    token += 1;
    const mine = token;
    set({ loading: true, error: null });
    try {
      const runs = await api.listRuns(get().limit, get().spaceId, get().origin);
      if (mine === token) set({ runs, error: null, loading: false, loaded: true });
    } catch (failure) {
      if (mine === token) {
        set({
          error: failure instanceof Error ? failure.message : String(failure),
          loading: false,
          loaded: true,
        });
      }
    }
  },

  ensure: () => {
    // Wait for a space key; loading earlier duplicates the shell-keyed request.
    const { loaded, loading, spaceId } = get();
    if (spaceId !== undefined && !loaded && !loading) void get().load();
  },

  loadMore: () => {
    set({ limit: get().limit + PAGE });
    void get().load();
  },

  setSpace: (spaceId) => {
    if (get().spaceId === spaceId) return;
    token += 1;
    set({ spaceId, runs: NO_RUNS, limit: PAGE, error: null, loading: false, loaded: false });
    void get().load();
  },

  setOrigin: (origin) => {
    if (get().origin === origin) return;
    token += 1;
    set({ origin, runs: NO_RUNS, limit: PAGE, error: null, loading: false, loaded: false });
    if (get().spaceId !== undefined) void get().load();
  },

  reset: () => {
    token += 1;
    set({ runs: NO_RUNS, spaceId: undefined, origin: undefined, limit: PAGE, error: null, loading: false, loaded: false });
  },
}));

/** Whether there may be rows beyond what was asked for. */
export function hasMore(state: Pick<RunListState, "runs" | "limit">): boolean {
  return state.runs.length >= state.limit;
}

const TERMINAL: ReadonlySet<Run["status"]> = new Set(["completed", "failed", "cancelled"]);

/** A run the table says has not ended. */
export function unfinished(run: Pick<Run, "status">): boolean {
  return !TERMINAL.has(run.status);
}
