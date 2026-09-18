import { describe, expect, it } from "vitest";

import { restartAvailable } from "./shell";

describe("restartAvailable", () => {
  it("is false in a plain browser, where no shell owns the process", () => {
    /* `just dev-desktop` opens the page in a browser tab; closing and reopening
       a tab restarts nothing, so the settings screen offers no button there.
       The true branch needs Tauri's injected globals and is exercised in the
       packaged app. */
    expect(restartAvailable()).toBe(false);
  });
});
