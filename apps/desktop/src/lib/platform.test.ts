import { describe, expect, it } from "vitest";

import { applyPlatform, detectPlatform } from "./platform";

describe("the platform", () => {
  it("is the Mac in WKWebView, which has no userAgentData", () => {
    expect(
      detectPlatform({
        platform: "MacIntel",
        userAgent: "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko)",
      }),
    ).toBe("mac");
  });

  it("is Windows in WebView2, by userAgentData first", () => {
    expect(
      detectPlatform({
        platform: "Win32",
        userAgent: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/140.0.0.0 Safari/537.36 Edg/140.0.0.0",
        userAgentData: { platform: "Windows" },
      }),
    ).toBe("windows");
  });

  it("trusts userAgentData over the older platform string", () => {
    expect(detectPlatform({ platform: "Win32", userAgentData: { platform: "macOS" } })).toBe("mac");
  });

  it("falls back to the user agent when nothing names the platform", () => {
    expect(detectPlatform({ userAgent: "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0)" })).toBe("mac");
    expect(detectPlatform({ userAgent: "Mozilla/5.0 (X11; Linux x86_64)" })).toBe("windows");
    expect(detectPlatform({})).toBe("windows");
  });

  it("draws anything that is not a Mac as Windows, the primary target", () => {
    expect(detectPlatform({ platform: "Linux x86_64" })).toBe("windows");
  });

  it("is written on the document root for the stylesheet", () => {
    const root = document.createElement("html");
    applyPlatform("mac", root);
    expect(root.dataset.platform).toBe("mac");
    applyPlatform("windows", root);
    expect(root.dataset.platform).toBe("windows");
  });
});
