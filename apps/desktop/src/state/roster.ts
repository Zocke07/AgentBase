import type { AgentDef } from "@agentspace/schemas";

import * as api from "../lib/api";

import { sharedFetch } from "./shared";

/**
 * The roster — every agent definition, enabled or not.
 *
 * Shown on the Home screen with an enable toggle and on the Agents page with
 * the editor beside it; one store so a toggle on either side is what the
 * other shows.
 */
const NO_AGENTS: readonly AgentDef[] = [];

export const useRoster = sharedFetch<readonly AgentDef[]>(() => api.listAgents(), NO_AGENTS);
