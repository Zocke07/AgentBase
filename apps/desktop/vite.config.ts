import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

/**
 * BUILD_SPEC §1 constraint 3: pin the dev server to 127.0.0.1 so `--host`
 * cannot widen it accidentally.
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
      // Ignore Rust output: while `tauri dev` runs both tools, Vite can open a
      // `target/` file Cargo is writing and fail with Windows EBUSY. It contains
      // no frontend source.
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
