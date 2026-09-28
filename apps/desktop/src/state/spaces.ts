import type { SpaceResponse } from "@agentbase/schemas";
import { create } from "zustand";

import * as api from "../lib/api";
import { readRenamedStorage } from "../lib/storage";

/**
 * Spaces and this window's selected space, stored in the browser rather than
 * workspace settings. Validate the remembered ID on each load; fall back to
 * default.
 */
export interface SpacesState {
  readonly spaces: readonly SpaceResponse[];
  /** Window-selected space; null until the list loads. */
  readonly currentId: string | null;
  readonly error: string | null;
  readonly loading: boolean;
  readonly loaded: boolean;
  load: () => Promise<void>;
  ensure: () => void;
  /** Select another space; ignore IDs absent from the list. */
  select: (id: string) => void;
  reset: () => void;
}

const KEY = "agentbase.space";
const LEGACY_KEY = "agentspace.space";

function readStored(): string | null {
  return readRenamedStorage(KEY, LEGACY_KEY);
}

function store(id: string): void {
  try {
    localStorage.setItem(KEY, id);
  } catch {
    // Select for this window without persisting.
  }
}

/** Return an existing remembered space (including archived) or the default;
 * archived spaces retain viewable runs and their unarchive settings. */
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
