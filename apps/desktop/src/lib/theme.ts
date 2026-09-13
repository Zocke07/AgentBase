import { useEffect } from "react";
import { create } from "zustand";

/**
 * Light or dark, following the OS with an override. "System" is the absence
 * of the `data-theme` attribute; the stylesheet's tokens do the rest. The
 * choice is a fact about this window, kept in this browser's storage, with
 * the read and write wrapped because storage can be unavailable.
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
