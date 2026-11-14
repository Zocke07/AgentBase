import { useRef, useState, type KeyboardEvent, type MouseEvent, type ReactNode } from "react";
import { createPortal } from "react-dom";

import { Menu, type MenuItem } from "./Menu";

/**
 * A context menu (Phase 20, brief 6.6): the actions a thing already has
 * elsewhere, opened on it by a right-click, Shift+F10 or the Menu key. It
 * is a `Menu`, so the arrows, type-ahead, Escape and focus coming back to
 * the thing all work as they do on a menu button.
 *
 * A right-click opens it at the pointer; the keyboard opens it under the
 * thing's own corner. Either way it is placed from a point held by an empty
 * element in the document's body. The menu stays mounted once opened, so it
 * can play its way out and give focus back as any menu does.
 *
 * Spread `trigger` on the element the menu belongs to and render `menu`
 * anywhere. `items` is read when the menu opens, with the element it opened
 * on, so it says what is true at that moment and one menu can serve many
 * rows (each naming itself in a data attribute).
 */

export interface ContextMenu {
  readonly trigger: {
    onContextMenu: (event: MouseEvent<HTMLElement>) => void;
    onKeyDown: (event: KeyboardEvent<HTMLElement>) => void;
  };
  readonly menu: ReactNode;
}

/** The keys that open a context menu from the keyboard. */
export function opensContextMenu(event: { key: string; shiftKey: boolean }): boolean {
  return event.key === "ContextMenu" || (event.shiftKey && event.key === "F10");
}

/**
 * `within`, when given, is a selector: the trigger then sits on a container
 * and the menu opens for the nearest matching element under the pointer or
 * with focus, or not at all.
 */
export function useContextMenu(
  label: string,
  items: (element: HTMLElement) => readonly MenuItem[],
  within?: string,
): ContextMenu {
  const [open, setOpen] = useState(false);
  // Each opening is a fresh menu (`opening` keys it), placed anew even when
  // the last one is still playing its way out.
  const [at, setAt] = useState<{ x: number; y: number; items: readonly MenuItem[]; opening: number } | null>(null);
  const point = useRef<HTMLSpanElement>(null);
  const owner = useRef<HTMLElement | null>(null);

  /** The element the menu is for, from where the event happened. */
  const subject = (event: { currentTarget: HTMLElement; target: EventTarget }): HTMLElement | null => {
    if (within === undefined) return event.currentTarget;
    const found = event.target instanceof Element ? event.target.closest<HTMLElement>(within) : null;
    return found !== null && event.currentTarget.contains(found) ? found : null;
  };

  /** Whether a menu opened; nothing does when the element has no actions. */
  const show = (element: HTMLElement, x: number, y: number): boolean => {
    const rows = items(element);
    if (rows.length === 0) return false;
    owner.current = element;
    setAt((last) => ({ x, y, items: rows, opening: (last?.opening ?? 0) + 1 }));
    setOpen(true);
    return true;
  };

  return {
    trigger: {
      onContextMenu: (event) => {
        const element = subject(event);
        if (element === null) return;
        event.preventDefault();
        // The innermost thing with a menu answers; its container does not.
        event.stopPropagation();
        show(element, event.clientX, event.clientY);
      },
      onKeyDown: (event) => {
        if (!opensContextMenu(event)) return;
        const element = subject(event);
        if (element === null) return;
        const box = element.getBoundingClientRect();
        if (!show(element, box.left + 8, box.bottom)) return;
        event.preventDefault();
        event.stopPropagation();
      },
    },
    menu:
      at === null ? null : (
        <>
          {createPortal(
            <span ref={point} className="context-point" style={{ left: at.x, top: at.y }} aria-hidden="true" />,
            document.body,
          )}
          <Menu
            key={at.opening}
            open={open}
            onClose={() => {
              setOpen(false);
            }}
            anchor={point}
            returnFocus={owner}
            label={label}
            items={at.items}
          />
        </>
      ),
  };
}
