import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

/**
 * Keep test configuration separate from `vite.config.ts`: dev-server binding
 * and Rust watcher exclusions do not affect tests.
 *
 * Use `jsdom` to test the run reducer and rendered DOM. BUILD_SPEC §5 Phase 7's
 * live/replay UI parity requires identical DOM under identical CSS.
 */
export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    // Require explicit imports; test files get no ambient globals.
    globals: false,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
    restoreMocks: true,
  },
});
