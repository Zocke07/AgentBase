import { describe, expect, it } from "vitest";

import { SECTION_ORDER } from "./sections";
import { matchesKeys, shortcut, shortcutLabel, SHORTCUTS, shouldIgnoreKey, withShortcut, type KeyPress } from "./shortcuts";

const press = (key: string, held: Partial<KeyPress> = {}): KeyPress => ({
  key,
  metaKey: false,
  ctrlKey: false,
  shiftKey: false,
  altKey: false,
  ...held,
});

describe("the keyboard map", () => {
  it("names every shortcut once, and gives no two the same keys in one scope", () => {
    expect(new Set(SHORTCUTS.map((entry) => entry.id)).size).toBe(SHORTCUTS.length);
    const taken = SHORTCUTS.map((entry) => `${entry.scope}:${shortcutLabel(entry.keys, "windows")}`);
    expect(new Set(taken).size).toBe(taken.length);
  });

  it("gives every section its digit, in rail order", () => {
    SECTION_ORDER.forEach((section, index) => {
      expect(shortcut(`section-${section}`).keys).toEqual({ key: String(index + 1), mod: true });
    });
  });

  it("writes a shortcut the way each platform does", () => {
    expect(shortcutLabel({ key: "K", mod: true }, "mac")).toBe("⌘K");
    expect(shortcutLabel({ key: "K", mod: true }, "windows")).toBe("Ctrl+K");
    expect(shortcutLabel({ key: ",", mod: true }, "mac")).toBe("⌘,");
    expect(shortcutLabel({ key: "P", mod: true, shift: true, alt: true }, "mac")).toBe("⌥⇧⌘P");
    expect(shortcutLabel({ key: "P", mod: true, shift: true, alt: true }, "windows")).toBe("Ctrl+Alt+Shift+P");
    expect(shortcutLabel({ key: "ArrowRight", shift: true }, "mac")).toBe("⇧→");
    expect(shortcutLabel({ key: "ArrowRight", shift: true }, "windows")).toBe("Shift+Right");
    expect(shortcutLabel({ key: "F" }, "mac")).toBe("F");
  });

  it("puts a shortcut after a name for a tooltip", () => {
    expect(withShortcut("Open a note", "note-open", "mac")).toBe("Open a note (⌘O)");
    expect(withShortcut("Open a note", "note-open", "windows")).toBe("Open a note (Ctrl+O)");
    expect(() => shortcut("no-such-thing")).toThrow();
  });

  it("matches a press with Command or with Ctrl, whatever the platform", () => {
    const keys = shortcut("palette").keys;
    expect(matchesKeys(press("k", { metaKey: true }), keys)).toBe(true);
    expect(matchesKeys(press("K", { ctrlKey: true }), keys)).toBe(true);
    expect(matchesKeys(press("k"), keys)).toBe(false);
    expect(matchesKeys(press("k", { ctrlKey: true, shiftKey: true }), keys)).toBe(false);
    expect(matchesKeys(press("k", { ctrlKey: true, altKey: true }), keys)).toBe(false);
  });

  it("matches plain keys, named keys with Shift, and symbols however they are typed", () => {
    expect(matchesKeys(press("f"), shortcut("office-follow").keys)).toBe(true);
    expect(matchesKeys(press("f", { ctrlKey: true }), shortcut("office-follow").keys)).toBe(false);
    expect(matchesKeys(press(" "), shortcut("timeline-play").keys)).toBe(true);
    expect(matchesKeys(press(" ", { shiftKey: true }), shortcut("timeline-play").keys)).toBe(false);
    expect(matchesKeys(press("ArrowRight", { shiftKey: true }), shortcut("timeline-next").keys)).toBe(true);
    expect(matchesKeys(press("ArrowRight"), shortcut("timeline-next").keys)).toBe(false);
    expect(matchesKeys(press("ArrowRight"), shortcut("timeline-forward").keys)).toBe(true);
    // "+" needs Shift on most keyboards and none on a number pad.
    expect(matchesKeys(press("+", { shiftKey: true }), shortcut("office-zoom-in").keys)).toBe(true);
    expect(matchesKeys(press("+"), shortcut("office-zoom-in").keys)).toBe(true);
  });

  it("leaves a plain key alone while someone types, and any key from a hidden section", () => {
    const field = document.createElement("input");
    const hidden = document.createElement("section");
    hidden.hidden = true;
    const inside = document.createElement("button");
    hidden.append(inside);
    document.body.append(field, hidden);

    expect(shouldIgnoreKey(field, { key: "F" })).toBe(true);
    // Saving with the command key still works from the editor.
    expect(shouldIgnoreKey(field, { key: "S", mod: true })).toBe(false);
    expect(shouldIgnoreKey(inside, { key: "K", mod: true })).toBe(true);
    expect(shouldIgnoreKey(document.body, { key: "F" })).toBe(false);
    expect(shouldIgnoreKey(null, { key: "F" })).toBe(false);
    field.remove();
    hidden.remove();
  });
});
