import { afterEach, describe, expect, it, vi } from "vitest";

import { moveWithTransition } from "./viewTransition";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("moving between places", () => {
  it("updates at once where the engine has no view transitions", async () => {
    const update = vi.fn();
    const doc = { hidden: false, documentElement: { dataset: {} } } as unknown as Document;
    const done = moveWithTransition(update, doc);
    expect(update).toHaveBeenCalledOnce();
    await expect(done).resolves.toBeUndefined();
  });

  it("goes through a transition where there is one, settling once the update is in", async () => {
    const update = vi.fn();
    const start = vi.fn((callback: () => void) => {
      callback();
      return { updateCallbackDone: Promise.resolve() };
    });
    const doc = { hidden: false, startViewTransition: start, documentElement: { dataset: {} } } as unknown as Document;
    await moveWithTransition(update, doc);
    expect(start).toHaveBeenCalledOnce();
    expect(update).toHaveBeenCalledOnce();
  });

  it("does not animate while the tour floats over the window", async () => {
    const start = vi.fn();
    const update = vi.fn();
    const doc = {
      hidden: false,
      startViewTransition: start,
      documentElement: { dataset: { viewTransitions: "off" } },
    } as unknown as Document;
    await moveWithTransition(update, doc);
    expect(start).not.toHaveBeenCalled();
    expect(update).toHaveBeenCalledOnce();
  });

  it("does not animate under reduced motion, or in a hidden window", () => {
    const start = vi.fn();
    vi.stubGlobal("matchMedia", (query: string) => ({ matches: query.includes("reduce") }));
    void moveWithTransition(vi.fn(), { hidden: false, startViewTransition: start, documentElement: { dataset: {} } } as unknown as Document);
    vi.unstubAllGlobals();
    void moveWithTransition(vi.fn(), { hidden: true, startViewTransition: start, documentElement: { dataset: {} } } as unknown as Document);
    expect(start).not.toHaveBeenCalled();
  });
});
