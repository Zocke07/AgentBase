import type { SpaceResponse } from "@agentspace/schemas";
import { create } from "zustand";

import * as api from "../lib/api";

/**
 * The spaces, and which one the window is looking at: a fact about this
 * window, remembered in this browser, never a workspace setting. The
 * remembered id is checked against the list on every load and falls back to
 * the default space.
 */
export interface SpacesState {
  readonly spaces: readonly SpaceResponse[];
  /** The space the window is looking at. Null until the list has loaded. */
  readonly currentId: string | null;
  readonly error: string | null;
  readonly loading: boolean;
  readonly loaded: boolean;
  load: () => Promise<void>;
  ensure: () => void;
  /** Look at another space. An id not in the list is ignored. */
  select: (id: string) => void;
  reset: () => void;
}

const KEY = "agentspace.space";

function readStored(): string | null {
  try {
    return localStorage.getItem(KEY);
  } catch {
    return null;
  }
}

function store(id: string): void {
  try {
    localStorage.setItem(KEY, id);
  } catch {
    // Not remembered; still selected for this window.
  }
}

/** The remembered space if it still exists (archived ones included, since
 * an archived space's runs are still viewable and its settings page is where
 * it is unarchived), else the default. */
function resolve(spaces: readonly SpaceResponse[], wanted: string | null): string | null {
  const found = spaces.find((space) => space.id === wanted);
  if (found !== undefined) return found.id;
  return spaces.find((space) => space.is_default)?.id ?? spaces[0]?.id ?? null;
}

const NO_SPACES: readonly SpaceResponse[] = [];

let token = 0;

export const useSpaces = create<SpacesState>()((set, get) => ({
  spaces: NO_SPACES,
  currentId: null,
  error: null,
  loading: false,
  loaded: false,

  load: async () => {
    token += 1;
    const mine = token;
    set({ loading: true, error: null });
    try {
      const spaces = await api.listSpaces();
      if (mine !== token) return;
      const currentId = resolve(spaces, get().currentId ?? readStored());
      set({ spaces, currentId, error: null, loading: false, loaded: true });
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

  select: (id) => {
    if (!get().spaces.some((space) => space.id === id)) return;
    store(id);
    set({ currentId: id });
  },

  reset: () => {
    token += 1;
    set({ spaces: NO_SPACES, currentId: null, error: null, loading: false, loaded: false });
  },
}));

/** The current space's row, or null before the list has loaded. */
export function currentSpace(state: Pick<SpacesState, "spaces" | "currentId">): SpaceResponse | null {
  return state.spaces.find((space) => space.id === state.currentId) ?? null;
}
