import { useCallback, useSyncExternalStore } from "react";

/**
 * Whether a CSS media query matches, kept current as the window changes.
 * Where `matchMedia` does not exist (the test environment) the answer is
 * false, so the wide layout is the one under test by default.
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
