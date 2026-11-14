import { readFileSync } from "node:fs";
import { join } from "node:path";

import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { scenario } from "../test/scenarios";

import { ScenarioPlayer } from "./ScenarioPlayer";
import { Workbench } from "./Workbench";
import { applyEnvironment, DEFAULT_ENVIRONMENT, environmentFrom } from "./environment";
import { PAGES } from "./pages";

/** The scenario player's own bar, apart from the run view's scrubber inside it. */
const player = () => within(screen.getByRole("group", { name: "How the log arrives" }));

const root = document.documentElement;

afterEach(() => {
  applyEnvironment(DEFAULT_ENVIRONMENT);
  delete root.dataset.platform;
  window.history.replaceState(null, "", "/");
});

describe("the workbench's conditions", () => {
  it("reads theme, motion and platform from a link, falling back on anything else", () => {
    expect(environmentFrom(new URLSearchParams("theme=dark&motion=reduce&platform=windows&transparency=reduce"))).toEqual({
      theme: "dark",
      motion: "reduce",
      platform: "windows",
      transparency: "reduce",
    });
    expect(environmentFrom(new URLSearchParams("theme=neon&motion=fast&platform=amiga"))).toEqual(DEFAULT_ENVIRONMENT);
    expect(environmentFrom(new URLSearchParams(""))).toEqual(DEFAULT_ENVIRONMENT);
  });

  it("puts each choice where the stylesheet reads it, and takes it away again", () => {
    applyEnvironment({ theme: "dark", motion: "reduce", platform: "windows", transparency: "reduce" });
    expect(root.dataset).toMatchObject({ theme: "dark", motion: "reduce", platform: "windows", transparency: "reduce" });

    // "System" is the absence of an override, as in the app's own theme setting.
    applyEnvironment(DEFAULT_ENVIRONMENT);
    expect(root.dataset.theme).toBeUndefined();
    expect(root.dataset.motion).toBeUndefined();
    expect(root.dataset.transparency).toBeUndefined();
    expect(root.dataset.platform).toBe("mac");
  });
});

describe("the workbench", () => {
  let fetchStub: ReturnType<typeof vi.fn<typeof fetch>>;

  beforeEach(() => {
    fetchStub = vi.fn<typeof fetch>(() => Promise.reject(new Error("the workbench called the sidecar")));
    vi.stubGlobal("fetch", fetchStub);
    vi.stubGlobal(
      "EventSource",
      vi.fn(() => {
        throw new Error("the workbench opened an event stream");
      }),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("names every page once, in a form a file name can hold", () => {
    const ids = PAGES.map((page) => page.id);
    expect(new Set(ids).size).toBe(ids.length);
    for (const id of ids) expect(id).toMatch(/^[a-z0-9-]+$/);
  });

  it("draws every page from fixtures alone, without calling the sidecar", () => {
    render(<Workbench initialPage={null} initialEnvironment={DEFAULT_ENVIRONMENT} />);
    const nav = within(screen.getByRole("navigation", { name: "Workbench pages" }));

    for (const page of PAGES) {
      fireEvent.click(nav.getByRole("button", { name: page.title }));
      expect(screen.getByTestId("wb-page").dataset.page).toBe(page.id);
      expect(screen.getByRole("heading", { level: 1, name: page.title })).toBeDefined();
      expect(screen.getByTestId("wb-page").textContent).not.toBe("");
    }

    expect(fetchStub).not.toHaveBeenCalled();
    expect(EventSource).not.toHaveBeenCalled();
  });

  it("keeps the page and the conditions in the link", () => {
    render(<Workbench initialPage="type" initialEnvironment={DEFAULT_ENVIRONMENT} />);
    expect(window.location.search).toBe("?page=type");

    fireEvent.change(screen.getByLabelText("Theme"), { target: { value: "dark" } });
    fireEvent.change(screen.getByLabelText("Platform"), { target: { value: "windows" } });

    expect(root.dataset).toMatchObject({ theme: "dark", platform: "windows" });
    expect(window.location.search).toBe("?page=type&theme=dark&platform=windows");
  });

  it("opens a linked run page at the linked cursor, and the link follows the cursor", () => {
    render(<Workbench initialPage="office-two-agents" initialEnvironment={DEFAULT_ENVIRONMENT} initialCursor={12} />);
    expect(screen.getByTestId("scrub-position").textContent).toBe("12 / 28");
    expect(window.location.search).toBe("?page=office-two-agents&cursor=12");

    fireEvent.click(player().getByRole("button", { name: "Step" }));
    expect(screen.getByTestId("scrub-position").textContent).toBe("13 / 28");
    expect(window.location.search).toBe("?page=office-two-agents&cursor=13");
  });

  it("keeps a cursor out of the link of a page that has none", () => {
    render(<Workbench initialPage="tokens" initialEnvironment={DEFAULT_ENVIRONMENT} initialCursor={5} />);
    expect(window.location.search).toBe("?page=tokens");

    // Moving to a run page starts at the end of its log, not at the stale cursor.
    const nav = within(screen.getByRole("navigation", { name: "Workbench pages" }));
    fireEvent.click(nav.getByRole("button", { name: "Two agents" }));
    expect(screen.getByTestId("scrub-position").textContent).toBe("28 / 28");
    expect(window.location.search).toBe("?page=office-two-agents&cursor=28");
  });

  it("opens the first page for a link it does not know", () => {
    render(<Workbench initialPage="no-such-page" initialEnvironment={DEFAULT_ENVIRONMENT} />);
    expect(screen.getByTestId("wb-page").dataset.page).toBe(PAGES[0]?.id);
  });
});

describe("the Motion switch", () => {
  /** A stylesheet's rules as selectors and declarations, with spacing evened out. */
  function rules(css: string): [string[], string][] {
    return [...css.replace(/\/\*[\s\S]*?\*\//g, "").matchAll(/([^{}]+)\{([^{}]*)\}/g)].map(([, selectors = "", body = ""]) => [
      selectors.split(",").map((selector) => selector.trim()),
      body.replace(/\s+/g, " ").trim(),
    ]);
  }

  it("repeats the app's reduced-motion block, rule for rule", () => {
    /* A page cannot switch the OS setting, so workbench.css copies the block
       under an attribute. A copy that drifted would show motion the real
       setting does not give. */
    const src = join(import.meta.dirname, "..");
    const app = readFileSync(join(src, "styles", "accessibility.css"), "utf8");
    const opening = "@media (prefers-reduced-motion: reduce) {";
    const start = app.indexOf(opening);
    expect(start).toBeGreaterThanOrEqual(0);
    // The block ends at the first closing brace that starts a line.
    const real = rules(app.slice(start + opening.length, app.indexOf("\n}", start)));
    expect(real.length).toBeGreaterThan(0);

    const prefix = ':root[data-motion="reduce"] ';
    const copy = rules(readFileSync(join(src, "workbench", "workbench.css"), "utf8"))
      .filter(([selectors]) => selectors.every((selector) => selector.startsWith(prefix)))
      .map(([selectors, body]): [string[], string] => [selectors.map((selector) => selector.slice(prefix.length)), body]);

    expect(copy).toEqual(real);
  });
});

describe("the scenario player", () => {
  const projection = () => screen.getByTestId("run-projection").innerHTML;

  it("steps the cursor one event at a time", () => {
    render(<ScenarioPlayer scenario={scenario("two-agents")} cursor={5} />);
    expect(screen.getByTestId("scrub-position").textContent).toBe("5 / 28");

    fireEvent.click(player().getByRole("button", { name: "Step" }));
    expect(screen.getByTestId("scrub-position").textContent).toBe("6 / 28");

    fireEvent.click(player().getByRole("button", { name: "Step back" }));
    fireEvent.click(player().getByRole("button", { name: "Step back" }));
    expect(screen.getByTestId("scrub-position").textContent).toBe("4 / 28");
  });

  it("plays forward on a timer and stops at the end of the log", () => {
    vi.useFakeTimers();
    try {
      render(<ScenarioPlayer scenario={scenario("two-agents")} cursor={26} />);
      fireEvent.click(player().getByRole("button", { name: "Play" }));
      expect(player().getByRole("button", { name: "Pause" })).toBeDefined();

      // One interval at a time, as a clock would: each step re-arms the timer.
      for (let step = 0; step < 4; step += 1) {
        act(() => {
          vi.advanceTimersByTime(600);
        });
      }
      expect(screen.getByTestId("scrub-position").textContent).toBe("28 / 28");
      expect(player().getByRole("button", { name: "Play" })).toBeDefined();
    } finally {
      vi.useRealTimers();
    }
  });

  it("draws the same run whether the events arrive live or are replayed", () => {
    const replayed = render(<ScenarioPlayer scenario={scenario("sandbox-denial")} cursor={14} />);
    expect(screen.getByTestId("scrub-position").textContent).toBe("14 / 38");
    const fromReplay = projection();
    replayed.unmount();

    // Live, only the first 14 events exist; replayed, all 38 do.
    render(<ScenarioPlayer scenario={scenario("sandbox-denial")} cursor={14} mode="live" />);
    expect(screen.getByTestId("scrub-position").textContent).toBe("14 / 14");
    expect(projection()).toBe(fromReplay);
  });

  it("switches between the two without moving the cursor", () => {
    render(<ScenarioPlayer scenario={scenario("sandbox-denial")} cursor={14} />);
    fireEvent.change(screen.getByLabelText("Arrives as"), { target: { value: "live" } });
    expect(screen.getByTestId("scrub-position").textContent).toBe("14 / 14");
    expect(screen.getByTestId("now-line").textContent).toBe("researcher is deciding what to do next.");
  });

  it("offers an answer only where the run view would: at the head of a run still going", () => {
    const waiting = scenario("shell-question");
    const { unmount } = render(<ScenarioPlayer scenario={waiting} />);
    expect(screen.getByRole("button", { name: "Deny" })).toBeDefined();
    unmount();

    // Scrubbed back to the moment it was asked, with later events after it.
    const asked = scenario("two-agents").events.findIndex((event) => event.type === "approval.requested") + 1;
    render(<ScenarioPlayer scenario={scenario("two-agents")} cursor={asked} />);
    expect(screen.getByTestId("approval-question").textContent).toContain("notes.txt");
    expect(screen.queryByRole("button", { name: "Deny" })).toBeNull();
  });
});
