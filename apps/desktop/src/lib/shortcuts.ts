import type { Platform } from "./platform";
import { SECTION_LABEL, SECTION_ORDER } from "./sections";

/**
 * The keyboard map (Phase 20, brief 6.5): every shortcut in one table, with
 * how each platform writes it. Tooltips, menu rows and the command palette
 * show a shortcut through `shortcutLabel`, so macOS reads "⌘K" and Windows
 * "Ctrl+K", and nothing else spells one out.
 *
 * `mod` is the platform's command key: Command on macOS, Ctrl on Windows.
 * A handler accepts either, as the shell always has, so a Mac keyboard on
 * Windows or the reverse still works; only the label differs.
 */

export interface Keys {
  readonly key: string;
  readonly mod?: boolean;
  readonly shift?: boolean;
  readonly alt?: boolean;
}

export type ShortcutScope = "window" | "knowledge" | "office" | "timeline";

export interface Shortcut {
  readonly id: string;
  readonly keys: Keys;
  /** What it does, as a tooltip or palette row says it. */
  readonly label: string;
  /** Where it applies. `window` works in every section. */
  readonly scope: ShortcutScope;
}

export const SHORTCUTS: readonly Shortcut[] = [
  ...SECTION_ORDER.map(
    (section, index): Shortcut => ({
      id: `section-${section}`,
      keys: { key: String(index + 1), mod: true },
      label: `Go to ${SECTION_LABEL[section]}`,
      scope: "window",
    }),
  ),
  { id: "rail", keys: { key: "B", mod: true }, label: "Show or hide the sidebar", scope: "window" },
  { id: "palette", keys: { key: "K", mod: true }, label: "Find anything", scope: "window" },
  { id: "settings", keys: { key: ",", mod: true }, label: "Open Settings", scope: "window" },
  { id: "note-save", keys: { key: "S", mod: true }, label: "Save the note", scope: "knowledge" },
  { id: "note-view", keys: { key: "E", mod: true }, label: "Switch between writing and preview", scope: "knowledge" },
  { id: "note-open", keys: { key: "O", mod: true }, label: "Open a note", scope: "knowledge" },
  { id: "office-follow", keys: { key: "F" }, label: "Follow the work", scope: "office" },
  { id: "office-fit", keys: { key: "0" }, label: "Show the whole room", scope: "office" },
  { id: "office-zoom-in", keys: { key: "+" }, label: "Zoom in", scope: "office" },
  { id: "office-zoom-out", keys: { key: "-" }, label: "Zoom out", scope: "office" },
  { id: "timeline-play", keys: { key: "Space" }, label: "Play or pause", scope: "timeline" },
  { id: "timeline-back", keys: { key: "ArrowLeft" }, label: "Step back", scope: "timeline" },
  { id: "timeline-forward", keys: { key: "ArrowRight" }, label: "Step forward", scope: "timeline" },
  { id: "timeline-previous", keys: { key: "ArrowLeft", shift: true }, label: "Previous notable event", scope: "timeline" },
  { id: "timeline-next", keys: { key: "ArrowRight", shift: true }, label: "Next notable event", scope: "timeline" },
];

export function shortcut(id: string): Shortcut {
  const found = SHORTCUTS.find((entry) => entry.id === id);
  if (found === undefined) throw new Error(`There is no shortcut called "${id}".`);
  return found;
}

/** Names a key cap carries instead of its `KeyboardEvent.key`. */
const KEY_CAP: Readonly<Record<string, { mac: string; windows: string }>> = {
  ArrowLeft: { mac: "←", windows: "Left" },
  ArrowRight: { mac: "→", windows: "Right" },
  ArrowUp: { mac: "↑", windows: "Up" },
  ArrowDown: { mac: "↓", windows: "Down" },
  Escape: { mac: "Esc", windows: "Esc" },
  Enter: { mac: "↩", windows: "Enter" },
  Space: { mac: "Space", windows: "Space" },
};

/**
 * A shortcut as the platform writes it: glyphs run together on macOS, in
 * Apple's order (Control, Option, Shift, Command); words joined by plus signs
 * on Windows.
 */
export function shortcutLabel(keys: Keys, platform: Platform): string {
  const cap = KEY_CAP[keys.key]?.[platform] ?? keys.key;
  if (platform === "mac") {
    return `${keys.alt === true ? "⌥" : ""}${keys.shift === true ? "⇧" : ""}${keys.mod === true ? "⌘" : ""}${cap}`;
  }
  return [keys.mod === true ? "Ctrl" : null, keys.alt === true ? "Alt" : null, keys.shift === true ? "Shift" : null, cap]
    .filter((part) => part !== null)
    .join("+");
}

/** "Open a note (⌘O)": a name with its shortcut, for a tooltip. */
export function withShortcut(name: string, id: string, platform: Platform): string {
  return `${name} (${shortcutLabel(shortcut(id).keys, platform)})`;
}

/** The parts of a key event a shortcut is matched on. */
export interface KeyPress {
  readonly key: string;
  readonly metaKey: boolean;
  readonly ctrlKey: boolean;
  readonly shiftKey: boolean;
  readonly altKey: boolean;
}

/** Whether a key press is this shortcut. Command and Ctrl both count as `mod`. */
export function matchesKeys(press: KeyPress, keys: Keys): boolean {
  const mod = press.metaKey || press.ctrlKey;
  if (mod !== (keys.mod === true) || press.altKey !== (keys.alt === true)) return false;
  const wanted = keys.key === "Space" ? " " : keys.key;
  // Shift decides the character of a symbol key itself ("+" is Shift and
  // "="), so it is only matched where the shortcut is a letter or a named key.
  const named = keys.key.length > 1 || /[a-z]/i.test(keys.key);
  if (named && press.shiftKey !== (keys.shift === true)) return false;
  return press.key.toLocaleLowerCase() === wanted.toLocaleLowerCase();
}

/**
 * Whether a document-level handler should leave a key press alone: it came
 * from a field someone is typing in, or from inside a section that is hidden
 * (every section stays mounted). Shortcuts with the command key still apply
 * while typing; plain keys never do.
 */
export function shouldIgnoreKey(target: EventTarget | null, keys: Keys): boolean {
  if (!(target instanceof Element)) return false;
  if (target.closest("[hidden]") !== null) return true;
  if (keys.mod === true) return false;
  return isEditable(target);
}

/** Whether the target is, or is inside, a field someone types in. */
export function isEditable(target: EventTarget | null): boolean {
  return (
    target instanceof Element &&
    target.closest('input, textarea, select, [contenteditable=""], [contenteditable="true"], [contenteditable="plaintext-only"]') !== null
  );
}
