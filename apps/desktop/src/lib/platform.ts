import { insideTauri } from "./tauri";

/**
 * Which platform the window is on, decided once (Phase 20, brief 4.5).
 *
 * The app ships for Windows and macOS and is the same on both, apart from
 * what each platform's own apps do: the font, the scrollbars, the shortcut
 * glyphs and the title bar. `applyPlatform` writes the answer on `<html>` as
 * `data-platform`, where the stylesheet reads it, and nothing else reads the
 * user agent. Anything that is not a Mac is drawn as Windows, the primary
 * target (BUILD_SPEC §1, constraint 7).
 */

export type Platform = "mac" | "windows";

/** The parts of `navigator` that say what the platform is. */
export interface PlatformHints {
  readonly platform?: string | undefined;
  readonly userAgent?: string | undefined;
  /** Chromium only, so WebView2 has it and WKWebView does not. */
  readonly userAgentData?: { readonly platform?: string | undefined } | undefined;
}

export function detectPlatform(hints: PlatformHints): Platform {
  const named = hints.userAgentData?.platform ?? hints.platform ?? "";
  if (/mac/i.test(named)) return "mac";
  if (named !== "") return "windows";
  return /Macintosh|Mac OS X/i.test(hints.userAgent ?? "") ? "mac" : "windows";
}

/** The platform of this window. */
export function currentPlatform(): Platform {
  return typeof navigator === "undefined" ? "windows" : detectPlatform(navigator);
}

/**
 * How the window's title bar is drawn (decision D5): an overlay on macOS,
 * inside the app, where the toolbar is the title bar and the window's
 * controls sit over the rail; the platform's own everywhere else, Windows
 * and a plain browser included.
 */
export type TitleBar = "overlay" | "native";

export function titleBarOf(platform: Platform, inApp: boolean): TitleBar {
  return platform === "mac" && inApp ? "overlay" : "native";
}

/** This window's title bar. */
export function currentTitleBar(): TitleBar {
  return titleBarOf(currentPlatform(), insideTauri());
}

/** Name the platform and the title bar on the document root; called once, before the first paint. */
export function applyPlatform(
  platform: Platform = currentPlatform(),
  root: HTMLElement = document.documentElement,
  inApp: boolean = insideTauri(),
): void {
  root.dataset.platform = platform;
  root.dataset.titlebar = titleBarOf(platform, inApp);
}
