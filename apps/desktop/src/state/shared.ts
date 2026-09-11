import { create, type StoreApi, type UseBoundStore } from "zustand";

/**
 * Something fetched from the sidecar that more than one view shows.
 *
 * `useFetched` is per component, which is right for a list one panel owns.
 * The redesign put the roster on the Home screen *and* on the Agents page,
 * and the run list on Home *and* in the Runs picker — and two copies of a
 * list that one of them edits disagree the moment it does. One store, and
 * every view reads it; whichever view changes the thing reloads it, and both
 * see the result.
 *
 * `load` is "latest wins": a response for a request that has since been
 * superseded is dropped, so a reload issued after an edit cannot be
 * overwritten by a slower fetch that began before it. `ensure` is what a view
 * calls on mount — load once if nobody has, otherwise nothing — so three
 * views mounting together make one request rather than three.
 */
export interface SharedState<T> {
  readonly data: T;
  readonly error: string | null;
  /** A request is in flight. `data` is whatever was last known meanwhile. */
  readonly loading: boolean;
  /** At least one request has settled, so an empty `data` means empty. */
  readonly loaded: boolean;
  load: () => Promise<void>;
  ensure: () => void;
  reset: () => void;
}

export type SharedStore<T> = UseBoundStore<StoreApi<SharedState<T>>>;

export function sharedFetch<T>(fetcher: () => Promise<T>, initial: T): SharedStore<T> {
  let token = 0;

  return create<SharedState<T>>()((set, get) => ({
    data: initial,
    error: null,
    loading: false,
    loaded: false,

    load: async () => {
      token += 1;
      const mine = token;
      // A retry is a fresh question: the old answer's error does not apply.
      set({ loading: true, error: null });
      try {
        const value = await fetcher();
        if (mine === token) set({ data: value, error: null, loading: false, loaded: true });
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
      const { loaded, loading } = get();
      if (!loaded && !loading) void get().load();
    },

    reset: () => {
      token += 1;
      set({ data: initial, error: null, loading: false, loaded: false });
    },
  }));
}
