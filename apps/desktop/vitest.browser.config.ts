import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { playwright } from "@vitest/browser-playwright";
import { defineConfig } from "vitest/config";

/**
 * The visual tests (`just test-visual`): the workbench's pages rendered in
 * real engines, compared with committed screenshots and checked by axe.
 *
 * Chromium stands in for WebView2 on Windows and WebKit for WKWebView on
 * macOS; jsdom, which the unit tests use, lays nothing out and computes no
 * colour. Baselines carry the browser and the platform in their file names,
 * because fonts differ between operating systems.
 *
 * Kept apart from `vitest.config.ts`: these need downloaded browsers
 * (`just setup-browsers`) and are not part of `just ci` until both platforms
 * have baselines.
 */
export default defineConfig({
  plugins: [react()],
  test: {
    globals: false,
    include: ["src/**/*.visual.tsx"],
    setupFiles: ["./src/test/browser-setup.ts"],
    restoreMocks: true,
    // Where a failed comparison leaves its actual and diff images: beside the
    // other development output, not in the source tree.
    attachmentsDir: fileURLToPath(new URL("../../.dev/visual", import.meta.url)),
    browser: {
      enabled: true,
      headless: true,
      // A person's time zone and language must not reach a screenshot.
      provider: playwright({ contextOptions: { timezoneId: "UTC", locale: "en-US" } }),
      instances: [{ browser: "chromium" }, { browser: "webkit" }],
      // Small enough to keep the committed baselines light, and wide enough
      // that the run view lays out as it does in a window. The visual test
      // sets the same size before each page and grows it for a tall one.
      viewport: { width: 1100, height: 720 },
      screenshotFailures: false,
    },
  },
});
