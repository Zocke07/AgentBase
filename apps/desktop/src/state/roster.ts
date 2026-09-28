import type { AgentDef } from "@agentbase/schemas";
import { create } from "zustand";

import * as api from "../lib/api";

/**
 * Current-space roster shared by Home and Agents. Key by space; latest-wins
 * loading prevents slow fetches overwriting reloads, and `ensure` loads once.
 */
export interface RosterState {
  readonly agents: readonly AgentDef[];
  /** Roster space; `undefined` selects every definition. */
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
    // Wait for a space key; loading earlier duplicates the shell-keyed request.
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
