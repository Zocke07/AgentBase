import { useCallback, useSyncExternalStore } from "react";

/**
 * Track a CSS media query as the window changes. Without `matchMedia` (tests),
 * return false to test the wide layout by default.
 */
export function useMediaQuery(query: string): boolean {
  const subscribe = useCallback(
    (notify: () => void) => {
      if (typeof window.matchMedia !== "function") return () => undefined;
      const list = window.matchMedia(query);
      list.addEventListener("change", notify);
      return () => {
        list.removeEventListener("change", notify);
      };
    },
    [query],
  );
  const read = () => typeof window.matchMedia === "function" && window.matchMedia(query).matches;
  return useSyncExternalStore(subscribe, read, () => false);
}
