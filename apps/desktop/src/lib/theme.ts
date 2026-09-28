import { useEffect } from "react";
import { create } from "zustand";

import { readRenamedStorage, removeRenamedStorage } from "./storage";

/**
 * Light or dark theme with OS-following override. "System" removes
 * `data-theme`; CSS tokens resolve it. Persist per-window choice when storage
 * is available.
 */

export type Theme = "system" | "light" | "dark";

export const THEMES: readonly Theme[] = ["system", "light", "dark"];

const KEY = "agentbase.theme";
const LEGACY_KEY = "agentspace.theme";

function isTheme(value: unknown): value is Theme {
  return value === "system" || value === "light" || value === "dark";
}

function readStoredTheme(): Theme {
  const stored = readRenamedStorage(KEY, LEGACY_KEY);
  return isTheme(stored) ? stored : "system";
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
      if (theme === "system") removeRenamedStorage(KEY, LEGACY_KEY);
      else localStorage.setItem(KEY, theme);
    } catch {
      // Apply for this window without persisting.
    }
    set({ theme });
  },
}));

/** Sync the document root to the chosen theme; called once by the shell. */
export function useTheme(): Theme {
  const theme = useThemeStore((state) => state.theme);
  useEffect(() => {
    applyTheme(theme);
  }, [theme]);
  return theme;
}
