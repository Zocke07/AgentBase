import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

/**
 * Unmount every rendered tree between tests. Testing Library only does this
 * itself with Vitest globals on, and this project runs with `globals: false`.
 */
afterEach(() => {
  cleanup();
});

/**
 * Browser APIs jsdom lacks, which React Flow uses on mount. The sizes matter:
 * React Flow draws no edge between nodes it has not measured, and a fixed,
 * plausible size is what lets a test assert a handoff actually draws.
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

/** Reports a size once, synchronously, then stays quiet. */
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
