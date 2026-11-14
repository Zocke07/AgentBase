import { afterEach, describe, expect, it, vi } from "vitest";

import { watchVisibility } from "./visibility";

afterEach(() => {
  vi.restoreAllMocks();
  delete document.documentElement.dataset.hidden;
});

describe("watchVisibility", () => {
  it("marks the document while the window is hidden, and clears the mark when it is seen again", () => {
    let hidden = false;
    vi.spyOn(document, "hidden", "get").mockImplementation(() => hidden);
    const stop = watchVisibility();
    expect(document.documentElement.dataset.hidden).toBeUndefined();

    hidden = true;
    document.dispatchEvent(new Event("visibilitychange"));
    expect(document.documentElement.dataset.hidden).toBe("true");

    hidden = false;
    document.dispatchEvent(new Event("visibilitychange"));
    expect(document.documentElement.dataset.hidden).toBeUndefined();

    stop();
    hidden = true;
    document.dispatchEvent(new Event("visibilitychange"));
    expect(document.documentElement.dataset.hidden).toBeUndefined();
  });
});
