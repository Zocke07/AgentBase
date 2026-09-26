import { useEffect, useState } from "react";

/**
 * Keeps something on screen for as long as its exit animation takes.
 *
 * React removes an element the moment its condition turns false, so an
 * animation on the way out never gets to play. This holds the element for
 * `exitMs` after `open` goes false and says it is `closing`, which the
 * component turns into a `--closing` class that the stylesheet animates.
 *
 * Where motion is reduced, or the environment cannot say (tests have no
 * `matchMedia`), there is no exit phase at all: the element goes at once,
 * exactly as it did before this hook existed.
 */
export function usePresence(open: boolean, exitMs = 160): { mounted: boolean; closing: boolean } {
  const [lingering, setLingering] = useState(false);
  const [seen, setSeen] = useState(open);

  // Adjusting state during render when the prop changes, rather than in an
  // effect, so the closing frame is the very next paint.
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
