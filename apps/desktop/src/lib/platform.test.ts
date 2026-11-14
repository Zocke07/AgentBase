import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { applyPlatform, detectPlatform, titleBarOf } from "./platform";

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

describe("the title bar", () => {
  it("is an overlay on a Mac inside the app, and the platform's own anywhere else", () => {
    expect(titleBarOf("mac", true)).toBe("overlay");
    expect(titleBarOf("mac", false)).toBe("native");
    expect(titleBarOf("windows", true)).toBe("native");
  });

  it("is named on the document root with the platform", () => {
    const root = document.createElement("html");
    applyPlatform("mac", root, true);
    expect(root.dataset.titlebar).toBe("overlay");
    applyPlatform("windows", root, true);
    expect(root.dataset.titlebar).toBe("native");
  });
});

describe("the macOS window configuration", () => {
  // Tauri merges tauri.macos.conf.json over tauri.conf.json, and a merge
  // replaces a whole array: the macOS window must repeat the base window,
  // or a later change to it would silently miss macOS builds.
  const read = (name: string) =>
    JSON.parse(readFileSync(join(import.meta.dirname, "..", "..", "src-tauri", name), "utf8")) as {
      app: { windows: Record<string, unknown>[] };
    };

  it("is the base window with the overlay title bar's keys and nothing else", () => {
    const base = read("tauri.conf.json").app.windows;
    const mac = read("tauri.macos.conf.json").app.windows;
    expect(mac).toHaveLength(base.length);
    const { titleBarStyle, hiddenTitle, trafficLightPosition, ...rest } = mac[0] ?? {};
    expect(rest).toEqual(base[0]);
    expect({ titleBarStyle, hiddenTitle }).toEqual({ titleBarStyle: "Overlay", hiddenTitle: true });
    expect(trafficLightPosition).toBeDefined();
  });
});
