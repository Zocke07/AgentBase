import { useEffect, useState } from "react";

/**
 * Retain elements through their exit animation.
 *
 * React removes false-condition elements immediately. Retain them for `exitMs`
 * after `open` becomes false and mark them `closing` for CSS `--closing`.
 *
 * With reduced motion, or without `matchMedia` in tests, remove immediately.
 */
export function usePresence(open: boolean, exitMs = 160): { mounted: boolean; closing: boolean } {
  const [lingering, setLingering] = useState(false);
  const [seen, setSeen] = useState(open);

  // Update during render so the closing frame reaches the next paint.
  if (seen !== open) {
    setSeen(open);
    setLingering(!open && !prefersReducedMotion());
  }

  useEffect(() => {
    if (!lingering) return undefined;
    const timer = window.setTimeout(() => {
      setLingering(false);
    }, exitMs);
    return () => {
      window.clearTimeout(timer);
    };
  }, [lingering, exitMs]);

  return { mounted: open || lingering, closing: !open && lingering };
}

/** True when the OS asks for less motion, or when there is no way to ask. */
export function prefersReducedMotion(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return true;
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}
