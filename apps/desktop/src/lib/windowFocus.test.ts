import { afterEach, describe, expect, it } from "vitest";

import { watchWindowFocus } from "./windowFocus";

let stop: (() => void) | null = null;

afterEach(() => {
  stop?.();
  stop = null;
});

describe("the window in front", () => {
  it("is said on the document root, and follows focus and blur", () => {
    stop = watchWindowFocus();
    const root = document.documentElement;
    expect(root.dataset.windowActive).toBe(document.hasFocus() ? "true" : "false");

    window.dispatchEvent(new Event("blur"));
    expect(root.dataset.windowActive).toBe("false");
    window.dispatchEvent(new Event("focus"));
    expect(root.dataset.windowActive).toBe("true");
  });

  it("leaves nothing behind once stopped", () => {
    watchWindowFocus()();
    expect(document.documentElement.dataset.windowActive).toBeUndefined();
    window.dispatchEvent(new Event("blur"));
    expect(document.documentElement.dataset.windowActive).toBeUndefined();
  });
});
