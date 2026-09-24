import { useCallback, useState } from "react";

import { readRenamedStorage } from "../lib/storage";

/**
 * A yes-or-no the viewer chose, kept in this browser's storage: a collapsed
 * sidebar, a folded section. Storage is a convenience, not state the app
 * depends on: it can be empty or refuse, and the page renders either way.
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
        // Nothing to do: the choice still holds for this view.
      }
    },
    [key],
  );

  return [value, set];
}
