import { useEffect } from "react";
import { create } from "zustand";

/**
 * Light or dark — BUILD_SPEC §5 Phase 11, "following the OS with an override
 * in Settings".
 *
 * The stylesheet defines both palettes as tokens: the light one on `:root`,
 * the dark one under `prefers-color-scheme: dark` for the default and under
 * `[data-theme="dark"]` for the override, with `[data-theme="light"]` winning
 * the other way. So "system" is the absence of the attribute, and the two
 * overrides are the attribute set. Nothing else on the page knows which
 * theme it is in.
 *
 * The choice is a fact about this window, not about the workspace: it lives
 * in this browser's storage rather than in the sidecar's settings table,
 * where it would follow the data directory to another machine and mean
 * nothing there. The read and the write are wrapped, because storage can be
 * unavailable — a private window, a webview with site data blocked — and a
 * theme preference is not worth a blank page.
 */

export type Theme = "system" | "light" | "dark";

export const THEMES: readonly Theme[] = ["system", "light", "dark"];

const KEY = "agentspace.theme";

function isTheme(value: unknown): value is Theme {
  return value === "system" || value === "light" || value === "dark";
}

function readStoredTheme(): Theme {
  try {
    const stored = localStorage.getItem(KEY);
    return isTheme(stored) ? stored : "system";
  } catch {
    return "system";
  }
}

/** Put the choice on the document root, where the stylesheet reads it. */
function applyTheme(theme: Theme): void {
  const root = document.documentElement;
  if (theme === "system") delete root.dataset.theme;
  else root.dataset.theme = theme;
}

interface ThemeState {
  readonly theme: Theme;
  setTheme: (theme: Theme) => void;
}

export const useThemeStore = create<ThemeState>()((set) => ({
  theme: readStoredTheme(),
  setTheme: (theme) => {
    try {
      if (theme === "system") localStorage.removeItem(KEY);
      else localStorage.setItem(KEY, theme);
    } catch {
      // Not remembered, still applied for this window.
    }
    set({ theme });
  },
}));

/** Keep the document root in step with the chosen theme. Called once, by the shell. */
export function useTheme(): Theme {
  const theme = useThemeStore((state) => state.theme);
  useEffect(() => {
    applyTheme(theme);
  }, [theme]);
  return theme;
}
