import { useEffect } from "react";
import { create } from "zustand";

/**
 * Reduce transparency (Phase 20, brief 4.3). Floating layers (menus,
 * popovers, sheets) are drawn on a translucent material over a blur. With
 * this on they are opaque instead: the stylesheet reads
 * `data-transparency="reduce"` on `<html>` and swaps the material tokens.
 *
 * It follows the system's own setting where the engine reports it
 * (`prefers-reduced-transparency`; WebKit does not reliably), live, until a
 * person chooses otherwise in Settings. A choice is kept the way the theme
 * is: in this window's browser storage, never in the backend. Only a choice
 * that differs from the system's is stored, so switching back to what the
 * system asks for is switching back to following it.
 */

const KEY = "agentbase.reduce-transparency";
const QUERY = "(prefers-reduced-transparency: reduce)";

function systemQuery(): MediaQueryList | null {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return null;
  return window.matchMedia(QUERY);
}

/** What the system asks for, or false where it cannot be asked. */
export function systemReducesTransparency(): boolean {
  return systemQuery()?.matches ?? false;
}

/** A stored choice, or null when the person follows the system. */
function readStored(): boolean | null {
  try {
    const stored = localStorage.getItem(KEY);
    return stored === "on" ? true : stored === "off" ? false : null;
  } catch {
    return null;
  }
}

/** Put the setting on the document root, where the stylesheet reads it. */
export function applyTransparency(reduce: boolean, root: HTMLElement = document.documentElement): void {
  if (reduce) root.dataset.transparency = "reduce";
  else delete root.dataset.transparency;
}

interface TransparencyState {
  readonly reduce: boolean;
  /** The person's own choice, in Settings. */
  setReduce: (reduce: boolean) => void;
  /** The system's setting changed: followed unless a choice is stored. */
  followSystem: (systemReduces: boolean) => void;
}

export const useTransparencyStore = create<TransparencyState>()((set) => ({
  reduce: readStored() ?? systemReducesTransparency(),
  setReduce: (reduce) => {
    try {
      if (reduce === systemReducesTransparency()) localStorage.removeItem(KEY);
      else localStorage.setItem(KEY, reduce ? "on" : "off");
    } catch {
      // Apply for this window without persisting.
    }
    set({ reduce });
  },
  followSystem: (systemReduces) => {
    if (readStored() === null) set({ reduce: systemReduces });
  },
}));

/** Sync the document root to the setting; called once by the shell. */
export function useTransparency(): boolean {
  const reduce = useTransparencyStore((state) => state.reduce);
  useEffect(() => {
    applyTransparency(reduce);
  }, [reduce]);
  useEffect(() => {
    const query = systemQuery();
    if (query === null || typeof query.addEventListener !== "function") return undefined;
    const onChange = (event: MediaQueryListEvent) => {
      useTransparencyStore.getState().followSystem(event.matches);
    };
    query.addEventListener("change", onChange);
    return () => {
      query.removeEventListener("change", onChange);
    };
  }, []);
  return reduce;
}
