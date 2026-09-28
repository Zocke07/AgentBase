import { useCallback, useState } from "react";

import { readRenamedStorage } from "../lib/storage";

/**
 * Persist a viewer choice, such as a collapsed sidebar, in browser storage.
 * Unavailable storage never blocks rendering.
 */
export function useStoredFlag(name: string, fallback = false): [boolean, (value: boolean) => void] {
  const key = `agentbase.flag.${name}`;
  const legacyKey = `agentspace.flag.${name}`;
  const [value, setValue] = useState<boolean>(() => {
    const stored = readRenamedStorage(key, legacyKey);
    return stored === null ? fallback : stored === "1";
  });

  const set = useCallback(
    (next: boolean) => {
      setValue(next);
      try {
        localStorage.setItem(key, next ? "1" : "0");
      } catch {
        // Choice still holds for this view.
      }
    },
    [key],
  );

  return [value, set];
}
