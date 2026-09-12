import type { AgentDef } from "@agentspace/schemas";
import { create } from "zustand";

import * as api from "../lib/api";

/**
 * The roster: every agent definition on the current space's roster,
 * enabled or not.
 *
 * Shown on the Home screen with an enable toggle and on the Agents page with
 * the editor beside it; one store so a toggle on either side is what the
 * other shows. Keyed on a space: switching spaces empties it and re-reads,
 * so a card for the previous roster never sits under the new space's name.
 *
 * `load` is "latest wins": a response for a request that has since been
 * superseded is dropped, so a reload issued after an edit cannot be
 * overwritten by a slower fetch that began before it. `ensure` is what a
 * view calls on mount (load once if nobody has, otherwise nothing), so two
 * views mounting together make one request rather than two.
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
