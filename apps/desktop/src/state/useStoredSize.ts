import { useCallback, useState } from "react";

import { readRenamedStorage, removeRenamedStorage } from "../lib/storage";

/**
 * Persist a viewer-selected panel size in browser storage. Null uses CSS
 * defaults; unavailable storage never blocks rendering.
 */
export function useStoredSize(name: string): [number | null, (value: number | null) => void] {
  const key = `agentbase.size.${name}`;
  const legacyKey = `agentspace.size.${name}`;
  const [value, setValue] = useState<number | null>(() => {
    try {
      const stored = readRenamedStorage(key, legacyKey);
      const parsed = stored === null ? Number.NaN : Number(stored);
      return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
    } catch {
      return null;
    }
  });

  const set = useCallback(
    (next: number | null) => {
      setValue(next);
      try {
        if (next === null) removeRenamedStorage(key, legacyKey);
        else localStorage.setItem(key, String(next));
      } catch {
        // Size still applies for this view.
      }
    },
    [key, legacyKey],
  );

  return [value, set];
}
