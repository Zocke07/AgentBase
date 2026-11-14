import { flushSync } from "react-dom";

/**
 * Moving between places (Phase 20, brief 5.3): a section change, or opening
 * a run, crossfades through a same-document View Transition where the
 * engine has one and motion is allowed. Elsewhere the update happens at
 * once, and the arriving section's own `view-in` plays instead.
 *
 * The returned promise settles once the update is in the document, which
 * is later than the call when a transition runs: anything that needs the
 * new section on screen (a scroll, a focus) waits for it.
 */
export function moveWithTransition(update: () => void, doc: Document = document): Promise<void> {
  const reduced = typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (typeof doc.startViewTransition !== "function" || reduced || doc.hidden) {
    update();
    return Promise.resolve();
  }
  const transition = doc.startViewTransition(() => {
    // The transition captures the new state as soon as this returns, so
    // React must have written it by then.
    flushSync(update);
  });
  // A transition skipped (another started, or the page hid) still runs its
  // update; either way the new section is there.
  return transition.updateCallbackDone.catch(() => undefined);
}
