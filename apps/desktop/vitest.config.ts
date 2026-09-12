import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

/**
 * Test configuration, kept apart from `vite.config.ts`.
 *
 * The app config pins the dev server to 127.0.0.1 and ignores the Rust tree;
 * none of that has anything to do with running tests, and merging the two would
 * mean every change to one is a change to the other's blast radius.
 *
 * `jsdom` rather than a browser: the thing under test is the run reducer and the
 * DOM the dashboard renders from it. BUILD_SPEC §5 Phase 7 asks that replaying a
 * run produce "pixel-identical UI state to what was shown live", and identical
 * DOM under identical CSS is what that reduces to: a claim a real DOM can make
 * and a snapshot of component state cannot.
 */
export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    // Explicit imports, not injected globals: the rest of this codebase has no
    // ambient magic and test files should not be the exception.
    globals: false,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
    restoreMocks: true,
  },
});
