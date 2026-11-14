import { afterEach, describe, expect, it } from "vitest";

import { keepsNativeMenu, suppressNativeMenu } from "./nativeMenu";

const user = { dev: false, altKey: false };

afterEach(() => {
  document.body.innerHTML = "";
});

describe("the webview's own context menu", () => {
  it("opens in a field and over selected text, for Cut, Copy and Paste", () => {
    document.body.innerHTML = '<input id="field"><div contenteditable="true"><b id="inside">x</b></div><p id="prose">x</p>';
    expect(keepsNativeMenu(document.getElementById("field"), false, user)).toBe(true);
    expect(keepsNativeMenu(document.getElementById("inside"), false, user)).toBe(true);
    expect(keepsNativeMenu(document.getElementById("prose"), true, user)).toBe(true);
  });

  it("does not open over the chrome", () => {
    document.body.innerHTML = '<button id="button">Run once</button>';
    expect(keepsNativeMenu(document.getElementById("button"), false, user)).toBe(false);
  });

  it("opens anywhere for Alt and the right button in a development build", () => {
    document.body.innerHTML = '<button id="button">Run once</button>';
    expect(keepsNativeMenu(document.getElementById("button"), false, { dev: true, altKey: true })).toBe(true);
    expect(keepsNativeMenu(document.getElementById("button"), false, { dev: false, altKey: true })).toBe(false);
  });

  it("is suppressed by the document's listener, and left alone once stopped", () => {
    document.body.innerHTML = '<button id="button">Run once</button>';
    const stop = suppressNativeMenu(document, false);
    const press = () => {
      const event = new MouseEvent("contextmenu", { bubbles: true, cancelable: true });
      document.getElementById("button")?.dispatchEvent(event);
      return event.defaultPrevented;
    };
    expect(press()).toBe(true);
    stop();
    expect(press()).toBe(false);
  });

  it("opens over selected text, but not over the chrome while text elsewhere is selected", () => {
    document.body.innerHTML = '<p id="prose">a sentence to copy</p><button id="button">Run once</button>';
    const stop = suppressNativeMenu(document, false);
    const prose = document.getElementById("prose");
    if (prose === null) throw new Error("The paragraph is missing.");
    const range = document.createRange();
    range.selectNodeContents(prose);
    document.getSelection()?.removeAllRanges();
    document.getSelection()?.addRange(range);
    const press = (id: string) => {
      const event = new MouseEvent("contextmenu", { bubbles: true, cancelable: true });
      document.getElementById(id)?.dispatchEvent(event);
      return event.defaultPrevented;
    };
    expect(press("prose")).toBe(false);
    expect(press("button")).toBe(true);
    stop();
  });
});
