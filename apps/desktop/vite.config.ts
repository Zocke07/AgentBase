import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

/**
 * BUILD_SPEC §1 constraint 3: everything binds 127.0.0.1. That includes the dev
 * server — `host` is pinned here rather than left to Vite's default so that
 * `--host` on the command line cannot widen it by accident.
 */
export default defineConfig({
  plugins: [react()],
  root: fileURLToPath(new URL(".", import.meta.url)),
  clearScreen: false,
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    watch: {
      // Never watch the Rust tree. `tauri dev` runs cargo and Vite against the
      // same directory, and Vite's watcher opens `target/` files while cargo is
      // still writing them — on Windows that is an EBUSY the watcher raises as
      // a fatal error, killing the dev server and taking `tauri dev` with it.
      // Nothing under here is a frontend source file, so there is nothing to
      // lose by ignoring it.
      ignored: ["**/src-tauri/**"],
    },
  },
  preview: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    sourcemap: true,
  },
});
