import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

/**
 * Unmount every rendered tree between tests.
 *
 * Testing Library does this automatically when Vitest's globals are injected,
 * and this project runs with `globals: false`, so without it the first test's
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
 * this project wrote. jsdom has no layout engine at all: every element measures
 * zero, and `ResizeObserver` does not exist.
 *
 * The sizes below are not decoration. React Flow refuses to position an edge
 * between nodes it has not measured, so with zero-sized nodes it renders the
 * graph with every edge silently missing, which is exactly the bug a real run
 * exposed, and exactly the bug a test cannot see unless measurement reports
 * something. Reporting a fixed, plausible size is what lets
 * `RunGraph.test.tsx` assert that a handoff actually draws.
 */

const NODE_WIDTH = 200;
const NODE_HEIGHT = 96;
const PANE_WIDTH = 1200;
const PANE_HEIGHT = 600;

function sizeOf(element: Element): { width: number; height: number } {
  if (element.classList.contains("react-flow__node")) {
    return { width: NODE_WIDTH, height: NODE_HEIGHT };
  }
  return { width: PANE_WIDTH, height: PANE_HEIGHT };
}

/**
 * Reports a size once, synchronously, then stays quiet.
 *
 * A real one fires on layout changes; there are none here, and the single
 * initial report is what React Flow needs to mark a node measured.
 */
class StubResizeObserver implements ResizeObserver {
  constructor(private readonly callback: ResizeObserverCallback) {}

  observe(target: Element): void {
    const { width, height } = sizeOf(target);
    const entry = {
      target,
      contentRect: { width, height, top: 0, left: 0, right: width, bottom: height, x: 0, y: 0 },
      borderBoxSize: [{ inlineSize: width, blockSize: height }],
      contentBoxSize: [{ inlineSize: width, blockSize: height }],
      devicePixelContentBoxSize: [{ inlineSize: width, blockSize: height }],
    } as unknown as ResizeObserverEntry;

    this.callback([entry], this);
  }

  unobserve(): void {
    /* nothing to stop reporting */
  }

  disconnect(): void {
    /* nothing to stop reporting */
  }
}

// Assigned unconditionally: TypeScript's DOM lib declares these as always
// present, so a `??=` reads to the compiler as dead code, while in jsdom they
// are genuinely missing at runtime.
globalThis.ResizeObserver = StubResizeObserver;

// React Flow reads a transform matrix off the pane. jsdom has no CSSOM view.
globalThis.DOMMatrixReadOnly = class {
  readonly m22: number = 1;
  constructor(readonly transform?: string) {}
} as unknown as typeof DOMMatrixReadOnly;

Element.prototype.getBoundingClientRect = function getBoundingClientRect(): DOMRect {
  const { width, height } = sizeOf(this);
  return {
    x: 0,
    y: 0,
    width,
    height,
    top: 0,
    right: width,
    bottom: height,
    left: 0,
    toJSON: () => ({}),
  };
};
