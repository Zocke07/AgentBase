import { useCallback, useState } from "react";

/**
 * A panel size the viewer chose, kept in this browser's storage. Null means
 * the stylesheet's default applies. Storage is a convenience, not state the
 * app depends on: it can be empty or refuse, and the page renders either way.
 */
export function useStoredSize(name: string): [number | null, (value: number | null) => void] {
  const key = `agentspace.size.${name}`;
  const [value, setValue] = useState<number | null>(() => {
    try {
      const stored = localStorage.getItem(key);
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
        if (next === null) localStorage.removeItem(key);
        else localStorage.setItem(key, String(next));
      } catch {
        // Nothing to do: the size still applies for this view.
      }
    },
    [key],
  );

  return [value, set];
}
