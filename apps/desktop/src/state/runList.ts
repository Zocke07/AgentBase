import type { Run } from "@agentbase/schemas";
import { create } from "zustand";

import * as api from "../lib/api";
import type { RunOrigin } from "../lib/api";

/**
 * The run list: the `runs` table, newest first, shared by the Home screen and
 * the Runs picker and re-read by whoever learns it is stale. The rows are a
 * snapshot; the open run's status comes from the store's fold. Keyed on a space.
 */
export interface RunListState {
  readonly runs: readonly Run[];
  /** The space whose runs these are. `undefined` is every run. */
  readonly spaceId: string | undefined;
  /** Only runs started this way; `undefined` is every run, whoever started it. */
  readonly origin: RunOrigin | undefined;
  /** How many rows the sidecar was last asked for; grows with `loadMore`. */
  readonly limit: number;
  readonly error: string | null;
  readonly loading: boolean;
  readonly loaded: boolean;
  load: () => Promise<void>;
  ensure: () => void;
  /** Ask for another page and re-read. */
  loadMore: () => void;
  setSpace: (spaceId: string) => void;
  /** Narrow to one origin, or widen to all; re-reads from the first page. */
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
    // A list that does not yet know its space has nothing to load: the
    // shell keys it once the space list has answered, and that is the one
    // request. Loading here as well was a second, un-keyed fetch on mount.
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
