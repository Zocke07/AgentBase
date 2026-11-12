/**
 * The style that makes a capture a frame at rest: every animation and
 * transition ends at once, still firing the `animationend` that
 * `state/usePresence.ts` waits for. A frame caught inside a 1 ms animation is
 * composited in other layers and its antialiased edges round differently,
 * which made two captures of one page differ by a colour level. `ui-shots`
 * and the visual tests both capture under it.
 */
export const STILL_CSS =
  "*, *::before, *::after { animation-duration: 0s !important; animation-delay: 0s !important; " +
  "transition-duration: 0s !important; transition-delay: 0s !important; }";
