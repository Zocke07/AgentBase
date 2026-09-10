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
