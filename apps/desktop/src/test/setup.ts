import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

/**
 * Unmount every rendered tree between tests.
 *
 * Testing Library does this automatically when Vitest's globals are injected,
 * and this project runs with `globals: false` — so without it the first test's
 * DOM is still mounted during the second, and a query that should match one
 * node matches two. That failure reads as a component bug, which is the worst
 * kind of test-harness defect.
 */
afterEach(() => {
  cleanup();
});

/**
 * Browser APIs jsdom does not implement, which React Flow uses on mount.
 *
 * These are stubs for genuinely missing platform features, not for anything
 * this project wrote. `ResizeObserver` reports element geometry, and jsdom has
 * no layout at all — every element is zero-sized there. That is fine for what
 * these tests assert: the graph's DOM structure and content come from the event
 * log, and the only thing lost is the measured pixel size, which is identical
 * (and zero) on both sides of every comparison.
 *
 * Anything that depended on real measurement would need a browser, and would be
 * a different test than the one being written here.
 */
class NoopResizeObserver implements ResizeObserver {
  observe(): void {
    // No layout in jsdom, so there is never a size change to report.
  }
  unobserve(): void {
    /* nothing observed */
  }
  disconnect(): void {
    /* nothing observed */
  }
}

// Assigned unconditionally: TypeScript's DOM lib declares both as always
// present, so a `??=` reads to the compiler as dead code — while in jsdom they
// are genuinely missing at runtime.
globalThis.ResizeObserver = NoopResizeObserver;

// React Flow reads a transform matrix off the pane. jsdom has no CSSOM view.
globalThis.DOMMatrixReadOnly = class {
  readonly m22: number = 1;
  constructor(readonly transform?: string) {}
} as unknown as typeof DOMMatrixReadOnly;

// Used by React Flow's pointer handling; jsdom returns nothing useful anyway.
Element.prototype.getBoundingClientRect = function getBoundingClientRect(): DOMRect {
  return {
    x: 0,
    y: 0,
    width: 0,
    height: 0,
    top: 0,
    right: 0,
    bottom: 0,
    left: 0,
    toJSON: () => ({}),
  };
};
