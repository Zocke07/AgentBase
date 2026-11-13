/**
 * An agent's silhouette (Phase 20, decision D3). Agents are abstract desk
 * companions, never people, and one is told from another by its shape and
 * its name plate, never by colour: colour already means status and risk.
 * The shape comes from a stable hash of the agent's name, so the same agent
 * looks the same in every run, live and on replay, on every machine.
 */

export interface Silhouette {
  readonly head: "round" | "square" | "wide";
  readonly antenna: 0 | 1 | 2;
  readonly ears: boolean;
  readonly visor: boolean;
}

const HEADS = ["round", "square", "wide"] as const;
const ANTENNAE = [0, 1, 2] as const;

/** FNV-1a, 32 bit: small, well spread, and the same everywhere. */
function hash(text: string): number {
  let value = 0x811c9dc5;
  for (let index = 0; index < text.length; index += 1) {
    value ^= text.charCodeAt(index);
    value = Math.imul(value, 0x01000193);
  }
  return value >>> 0;
}

export function silhouetteOf(name: string): Silhouette {
  const value = hash(name);
  return {
    head: HEADS[value % HEADS.length] ?? "round",
    antenna: ANTENNAE[(value >>> 4) % ANTENNAE.length] ?? 0,
    ears: ((value >>> 8) & 1) === 1,
    visor: ((value >>> 12) & 1) === 1,
  };
}

/** How many different silhouettes there are. */
export const SILHOUETTES = HEADS.length * ANTENNAE.length * 2 * 2;
