/**
 * The conditions a page is looked at under: theme, motion and platform. The
 * workbench sets them as attributes on `<html>`, where the stylesheet reads
 * them, so one tab can show what each operating system setting would.
 */

export type ThemeChoice = "system" | "light" | "dark";
export type MotionChoice = "system" | "reduce";
export type PlatformChoice = "mac" | "windows";
export type TransparencyChoice = "system" | "reduce";

export interface Environment {
  readonly theme: ThemeChoice;
  readonly motion: MotionChoice;
  readonly platform: PlatformChoice;
  readonly transparency: TransparencyChoice;
}

export const THEME_CHOICES: readonly ThemeChoice[] = ["system", "light", "dark"];
export const MOTION_CHOICES: readonly MotionChoice[] = ["system", "reduce"];
export const PLATFORM_CHOICES: readonly PlatformChoice[] = ["mac", "windows"];
export const TRANSPARENCY_CHOICES: readonly TransparencyChoice[] = ["system", "reduce"];

export const DEFAULT_ENVIRONMENT: Environment = {
  theme: "system",
  motion: "system",
  platform: "mac",
  transparency: "system",
};

const oneOf = <Choice extends string>(choices: readonly Choice[], value: string | null, fallback: Choice): Choice =>
  choices.find((choice) => choice === value) ?? fallback;

/** Read the environment from a URL's query, so a state can be linked to. */
export function environmentFrom(query: URLSearchParams): Environment {
  return {
    theme: oneOf(THEME_CHOICES, query.get("theme"), DEFAULT_ENVIRONMENT.theme),
    motion: oneOf(MOTION_CHOICES, query.get("motion"), DEFAULT_ENVIRONMENT.motion),
    platform: oneOf(PLATFORM_CHOICES, query.get("platform"), DEFAULT_ENVIRONMENT.platform),
    transparency: oneOf(TRANSPARENCY_CHOICES, query.get("transparency"), DEFAULT_ENVIRONMENT.transparency),
  };
}

/**
 * Put the environment on the document root.
 *
 * - `data-theme` is the app's own override (`lib/theme.ts`); "system" removes it.
 * - `data-motion="reduce"` is the workbench's stand-in for the OS setting: a
 *   page cannot change a media query, so `workbench.css` repeats the app's
 *   reduced-motion block under this attribute. The browser tests use the real
 *   media feature instead.
 * - `data-platform` is where the app says which platform it is on
 *   (`lib/platform.ts`); the stylesheet reads it for the scrollbars.
 * - `data-transparency="reduce"` is the app's own Reduce transparency
 *   setting (`lib/transparency.ts`): floating layers turn opaque.
 */
export function applyEnvironment(environment: Environment, root: HTMLElement = document.documentElement): void {
  if (environment.theme === "system") delete root.dataset.theme;
  else root.dataset.theme = environment.theme;

  if (environment.motion === "system") delete root.dataset.motion;
  else root.dataset.motion = environment.motion;

  root.dataset.platform = environment.platform;

  if (environment.transparency === "system") delete root.dataset.transparency;
  else root.dataset.transparency = environment.transparency;
}

/** The theme a page is drawn in, once "system" is resolved. */
export function effectiveTheme(theme: ThemeChoice): "light" | "dark" {
  if (theme !== "system") return theme;
  const prefersDark = typeof window.matchMedia === "function" && window.matchMedia("(prefers-color-scheme: dark)").matches;
  return prefersDark ? "dark" : "light";
}
