import { describe, expect, it } from "vitest";

import { keychainAvailable } from "./keychain";

describe("keychainAvailable", () => {
  it("is false in a plain browser, where there is no shell holding a keychain", () => {
    /* `just dev-desktop` opens the page in a browser; the settings tab then
       explains that keys can be set only from the app. The true branch needs
       Tauri's injected globals and is exercised in the packaged app. */
    expect(keychainAvailable()).toBe(false);
  });
});
