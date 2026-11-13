import { useEffect, useEffectEvent, useId } from "react";

/**
 * The floating layers that are open, lowest first. Escape and a press
 * outside belong to the topmost one alone: a menu opened from a sheet closes
 * without taking the sheet with it. Module state, because the layers are
 * rendered by unrelated parts of the tree.
 */
interface Layer {
  readonly id: string;
  /** The element the layer was opened from. */
  readonly origin: () => Element | null;
  /** Called when that element has been hidden under the layer. */
  readonly orphaned: () => void;
}

const open: Layer[] = [];

export function isTopLayer(id: string): boolean {
  return open.at(-1)?.id === id;
}

/**
 * Every section stays mounted behind `hidden`, and a layer renders into the
 * document's body, outside its section. So when a section is hidden (a
 * shortcut, a notification that opens a run), a layer opened from inside it
 * would stay floating over the next one. One observer watches for `hidden`
 * changing anywhere while any layer is open, and closes the layers it
 * orphans.
 */
let watcher: MutationObserver | null = null;

function closeOrphans(): void {
  for (const layer of [...open]) {
    if (layer.origin()?.closest("[hidden]") instanceof Element) layer.orphaned();
  }
}

function watch(): void {
  if (open.length > 0 && watcher === null && typeof MutationObserver === "function") {
    watcher = new MutationObserver(closeOrphans);
    watcher.observe(document.body, { attributes: true, attributeFilter: ["hidden"], subtree: true });
  } else if (open.length === 0 && watcher !== null) {
    watcher.disconnect();
    watcher = null;
  }
}

/**
 * Register a layer while `active`, and return its id for `isTopLayer`.
 * `origin` is the element it was opened from; `orphaned` closes it.
 */
export function useLayer(active: boolean, origin: () => Element | null, orphaned: () => void): string {
  const id = useId();
  const readOrigin = useEffectEvent(origin);
  const onOrphaned = useEffectEvent(orphaned);
  useEffect(() => {
    if (!active) return undefined;
    open.push({ id, origin: () => readOrigin(), orphaned: () => { onOrphaned(); } });
    watch();
    return () => {
      const index = open.findLastIndex((layer) => layer.id === id);
      if (index >= 0) open.splice(index, 1);
      watch();
    };
  }, [active, id]);
  return id;
}

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), ' +
  'textarea:not([disabled]), summary, [tabindex]:not([tabindex="-1"])';

/** What Tab can reach inside `root`, in document order. */
export function focusableIn(root: HTMLElement): HTMLElement[] {
  return [...root.querySelectorAll<HTMLElement>(FOCUSABLE)].filter((element) => element.closest("[hidden], [inert]") === null);
}
