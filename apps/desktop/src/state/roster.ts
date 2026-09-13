import type { AgentDef } from "@agentspace/schemas";
import { create } from "zustand";

import * as api from "../lib/api";

/**
 * The roster: every definition on the current space's roster, shared by the
 * Home screen and the Agents page. Keyed on a space. `load` is latest-wins,
 * so a slow fetch cannot overwrite a later reload; `ensure` loads once on
 * mount if nobody has.
 */
export interface RosterState {
  readonly agents: readonly AgentDef[];
  /** The space whose roster this is. `undefined` is every definition. */
  readonly spaceId: string | undefined;
  readonly error: string | null;
  readonly loading: boolean;
  readonly loaded: boolean;
  load: () => Promise<void>;
  ensure: () => void;
  setSpace: (spaceId: string) => void;
  reset: () => void;
}

const NO_AGENTS: readonly AgentDef[] = [];

let token = 0;

export const useRoster = create<RosterState>()((set, get) => ({
  agents: NO_AGENTS,
  spaceId: undefined,
  error: null,
  loading: false,
  loaded: false,

  load: async () => {
    token += 1;
    const mine = token;
    set({ loading: true, error: null });
    try {
      const agents = await api.listAgents(get().spaceId);
      if (mine === token) set({ agents, error: null, loading: false, loaded: true });
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

  setSpace: (spaceId) => {
    if (get().spaceId === spaceId) return;
    token += 1;
    set({ spaceId, agents: NO_AGENTS, error: null, loading: false, loaded: false });
    void get().load();
  },

  reset: () => {
    token += 1;
    set({ agents: NO_AGENTS, spaceId: undefined, error: null, loading: false, loaded: false });
  },
}));
