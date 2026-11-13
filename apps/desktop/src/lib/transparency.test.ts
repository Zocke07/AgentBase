import { afterEach, describe, expect, it, vi } from "vitest";

afterEach(() => {
  localStorage.clear();
  vi.unstubAllGlobals();
  vi.resetModules();
});

async function load() {
  vi.resetModules();
  return import("./transparency");
}

function systemAsks(reduce: boolean): void {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: reduce && query === "(prefers-reduced-transparency: reduce)",
    media: query,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
  }));
}

describe("reduce transparency", () => {
  it("is off where the system cannot be asked and nothing is stored", async () => {
    const { useTransparencyStore } = await load();
    expect(useTransparencyStore.getState().reduce).toBe(false);
  });

  it("starts from the system's setting where the engine reports it", async () => {
    systemAsks(true);
    const { useTransparencyStore } = await load();
    expect(useTransparencyStore.getState().reduce).toBe(true);
  });

  it("keeps a person's choice over the system's, in either direction", async () => {
    systemAsks(true);
    localStorage.setItem("agentbase.reduce-transparency", "off");
    expect((await load()).useTransparencyStore.getState().reduce).toBe(false);

    systemAsks(false);
    localStorage.setItem("agentbase.reduce-transparency", "on");
    expect((await load()).useTransparencyStore.getState().reduce).toBe(true);
  });

  it("remembers a choice that differs from the system's, on this computer", async () => {
    const { useTransparencyStore } = await load();
    useTransparencyStore.getState().setReduce(true);
    expect(localStorage.getItem("agentbase.reduce-transparency")).toBe("on");
    expect(useTransparencyStore.getState().reduce).toBe(true);
  });

  it("goes back to following the system when the choice is the system's own", async () => {
    systemAsks(true);
    const { useTransparencyStore } = await load();
    useTransparencyStore.getState().setReduce(false);
    expect(localStorage.getItem("agentbase.reduce-transparency")).toBe("off");
    useTransparencyStore.getState().setReduce(true);
    expect(localStorage.getItem("agentbase.reduce-transparency")).toBeNull();
  });

  it("follows a change of the system's setting, unless a choice is stored", async () => {
    const { useTransparencyStore } = await load();
    useTransparencyStore.getState().followSystem(true);
    expect(useTransparencyStore.getState().reduce).toBe(true);
    useTransparencyStore.getState().followSystem(false);
    expect(useTransparencyStore.getState().reduce).toBe(false);

    // A person who chose "on" keeps it when the system then says "off".
    useTransparencyStore.getState().setReduce(true);
    useTransparencyStore.getState().followSystem(false);
    expect(useTransparencyStore.getState().reduce).toBe(true);
  });

  it("is written on the document root for the stylesheet", async () => {
    const { applyTransparency } = await load();
    const root = document.createElement("html");
    applyTransparency(true, root);
    expect(root.dataset.transparency).toBe("reduce");
    applyTransparency(false, root);
    expect(root.dataset.transparency).toBeUndefined();
  });
});
