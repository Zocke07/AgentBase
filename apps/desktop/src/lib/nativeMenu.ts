import { isEditable } from "./shortcuts";

/**
 * The webview's own context menu (Phase 20, brief 6.6). A native app shows
 * none over its chrome, so it is suppressed, except where its Cut, Copy and
 * Paste help: in a field someone types in, and over text someone has
 * selected (content stays selectable, brief 6.7). The app's own context
 * menus call `preventDefault` themselves and never reach this.
 *
 * In a development build, Alt (Option) with the right button keeps the
 * webview's menu everywhere, for its Inspect Element.
 */

/**
 * Whether the webview's own menu should open for this press. `onSelection`
 * is whether it landed on text that is selected: a selection elsewhere in
 * the window does not open the menu over the chrome.
 */
export function keepsNativeMenu(target: EventTarget | null, onSelection: boolean, developer: { dev: boolean; altKey: boolean }): boolean {
  if (developer.dev && developer.altKey) return true;
  return isEditable(target) || onSelection;
}

/** Whether the press landed on selected text. */
function pressedOnSelection(doc: Document, target: EventTarget | null): boolean {
  const selection = doc.getSelection();
  if (selection === null || selection.isCollapsed || selection.toString().trim() === "") return false;
  // A right-click lands on the element holding the text, which wraps the
  // selection rather than sitting inside it: ask whether they meet.
  if (!(target instanceof Node)) return false;
  for (let index = 0; index < selection.rangeCount; index += 1) {
    if (selection.getRangeAt(index).intersectsNode(target)) return true;
  }
  return false;
}

/** Started once, from `main.tsx`; returns what stops it. */
export function suppressNativeMenu(doc: Document = document, dev: boolean = import.meta.env.DEV): () => void {
  const onContextMenu = (event: MouseEvent) => {
    if (event.defaultPrevented) return;
    if (!keepsNativeMenu(event.target, pressedOnSelection(doc, event.target), { dev, altKey: event.altKey })) event.preventDefault();
  };
  doc.addEventListener("contextmenu", onContextMenu);
  return () => {
    doc.removeEventListener("contextmenu", onContextMenu);
  };
}
