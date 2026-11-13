import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { placeOffice } from "../../lib/officeLayout";
import { nowLine } from "../../state/describe";
import { officeOf } from "../../state/office";
import { reduceAll } from "../../state/reducer";
import { LogBuilder, twoAgentRun } from "../../test/log";
import { scenario, SCENARIOS } from "../../test/scenarios";

import { OfficeScene } from "./OfficeScene";

function show(events: Parameters<typeof reduceAll>[0], selected: string | null = null, onSelect = vi.fn()) {
  const view = reduceAll(events);
  return {
    onSelect,
    ...render(<OfficeScene model={officeOf(view)} description={nowLine(view)} selectedAgent={selected} onSelectAgent={onSelect} />),
  };
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("the office reads no clock", () => {
  it("draws every scenario, at several cursors, with every clock and random source refusing", () => {
    // Brief 7.8: nothing in the projection may read the time or roll a die.
    const refuse = (name: string) => () => {
      throw new Error(`the office called ${name}`);
    };
    vi.spyOn(Date, "now").mockImplementation(refuse("Date.now"));
    vi.spyOn(Math, "random").mockImplementation(refuse("Math.random"));
    vi.stubGlobal("requestAnimationFrame", refuse("requestAnimationFrame"));
    const clock = vi.spyOn(performance, "now");

    for (const entry of SCENARIOS) {
      const step = Math.max(1, Math.floor(entry.events.length / 6));
      for (let cursor = 0; cursor <= entry.events.length; cursor += step) {
        const view = reduceAll(entry.events.slice(0, cursor));
        // The projection and the layout are the office's own code alone, so
        // there even `performance.now` must stay untouched. React's scheduler
        // reads it while rendering, so the drawing is held to the other three.
        clock.mockImplementation(refuse("performance.now"));
        const model = officeOf(view);
        placeOffice(model.desks.length);
        clock.mockRestore();
        vi.spyOn(performance, "now");

        const rendered = render(<OfficeScene model={model} description={nowLine(view)} selectedAgent={null} onSelectAgent={() => undefined} />);
        expect(rendered.getByTestId("office")).toBeDefined();
        rendered.unmount();
      }
    }
  });
});

describe("the office in words", () => {
  it("is a named region described by the Now line", () => {
    const events = twoAgentRun();
    show(events);
    const region = screen.getByRole("region", { name: "The office" });
    expect(within(region).getByTestId("office-description").textContent).toBe(nowLine(reduceAll(events)));
  });

  it("makes each desk a button whose name says who, what for and what now", () => {
    show(scenario("shell-question").events);
    const researcher = screen.getByRole("button", { name: /^researcher Waiting for you .*\. \d+ tool calls?\.$/ });
    expect(researcher.textContent).toContain("Waiting for you");
    // The drawing itself is hidden from a screen reader: the words carry it.
    expect(screen.getByTestId("office").querySelector("svg.office-room")?.getAttribute("aria-hidden")).toBe("true");
  });

  it("opens each desk's name with the words on its plate, in their order", () => {
    // Someone who speaks to the screen says what they see (WCAG 2.5.3).
    show(scenario("morning-collection").events);
    for (const button of screen.getByTestId("office").querySelectorAll<HTMLButtonElement>("[data-desk]")) {
      // As one line of text, spaces between the parts included.
      const shown = button.textContent.trim();
      expect(shown).toMatch(/\S \S/);
      expect(button.getAttribute("aria-label")?.startsWith(shown), shown).toBe(true);
    }
  });

  it("mirrors a waiting question at the reception without offering to answer it", () => {
    show(scenario("shell-question").events);
    const office = screen.getByTestId("office");
    expect(office.textContent).toContain("1 question waiting: answer above");
    // Questions are answered in the docked panel alone (Phase 11).
    expect(within(office).queryByRole("button", { name: /allow|deny/i })).toBeNull();
  });

  it("labels what an agent says as said, and puts no stamp on it", () => {
    const events = twoAgentRun();
    const speaking = events.findIndex((event) => event.type === "llm.token") + 1;
    show(events.slice(0, speaking));
    const bubble = screen.getByTestId("office").querySelector(".office-bubble");
    expect(bubble?.textContent).toMatch(/is saying: /);
    expect(bubble?.querySelector('[data-icon="stamp"]')).toBeNull();
  });

  it("shows the run's own summary on the board as what the supervisor said", () => {
    show(twoAgentRun());
    const board = screen.getByTestId("office").querySelector(".office-board-card");
    expect(board?.textContent).toContain("The supervisor said");
    expect(board?.textContent).toContain("completed");
  });

  it("announces a finish politely, and never a question", () => {
    show(twoAgentRun());
    const live = screen.getByTestId("office-announcement");
    expect(live.getAttribute("aria-live")).toBe("polite");
    expect(live.textContent).toBe("The run completed.");
  });

  it("says that an empty chair's agent never started, and takes no press", () => {
    show(scenario("ghost-handoff").events);
    const ghosts = screen.getAllByRole("button").filter((button) => button.getAttribute("aria-label")?.includes("nobody took it up"));
    expect(ghosts.length).toBeGreaterThan(0);
    for (const ghost of ghosts) expect((ghost as HTMLButtonElement).disabled).toBe(true);
  });
});

describe("the office by keyboard", () => {
  it("has one tab stop, on the selected desk or the one at work", () => {
    show(scenario("morning-collection").events, "market-movers");
    const desks = [...screen.getByTestId("office").querySelectorAll<HTMLButtonElement>("[data-desk]")];
    expect(desks.filter((desk) => desk.tabIndex === 0).map((desk) => desk.dataset.desk)).toEqual(["market-movers"]);
  });

  it("moves between desks with the arrow keys, Home and End, and selects with Enter", async () => {
    const user = userEvent.setup();
    const { onSelect } = show(scenario("morning-collection").events);
    const desks = [...screen.getByTestId("office").querySelectorAll<HTMLButtonElement>("[data-desk]")];
    const names = desks.map((desk) => desk.dataset.desk);
    expect(names).toEqual(["supervisor", "news-scanner", "market-movers", "event-calendar", "portfolio-review"]);

    desks[0]?.focus();
    await user.keyboard("{ArrowRight}");
    expect(document.activeElement).toBe(desks[1]);
    await user.keyboard("{End}");
    expect(document.activeElement).toBe(desks[4]);
    await user.keyboard("{ArrowRight}");
    expect(document.activeElement).toBe(desks[0]);
    await user.keyboard("{ArrowLeft}{Home}{ArrowDown}");
    expect(document.activeElement).toBe(desks[1]);

    await user.keyboard("{Enter}");
    expect(onSelect).toHaveBeenCalledExactlyOnceWith("news-scanner");
  });

  it("unselects a selected desk when it is pressed again, as the diagram does", async () => {
    const user = userEvent.setup();
    const { onSelect } = show(twoAgentRun(), "researcher");
    const researcher = screen.getByTestId("office-desk-researcher");
    expect(researcher.getAttribute("aria-pressed")).toBe("true");
    await user.click(researcher);
    expect(onSelect).toHaveBeenCalledExactlyOnceWith(null);
  });

  it("keeps a long error to a few lines on the desk, with the whole of it in the tooltip", () => {
    const long = `read_file was not run: ${"the answer was cut off at the output limit ".repeat(8)}`;
    const log = new LogBuilder();
    const view = reduceAll([
      log.add("run.started", { goal: "g" }),
      log.add("agent.spawned", { role: "Writes" }, "writer"),
      log.add("tool.error", { tool: "write_file", error: long }, "writer"),
    ]);
    render(<OfficeScene model={officeOf(view)} description="" selectedAgent={null} onSelectAgent={() => undefined} />);
    const note = screen.getByTestId("office").querySelector(".office-trouble");
    expect(note?.getAttribute("title")).toBe(long);
    expect(note?.textContent.length).toBeLessThan(130);
  });

  it("says a budget warning in a live region of its own", () => {
    show(scenario("budget-warning").events);
    const live = screen.getByTestId("office-budget-announcement");
    expect(live.getAttribute("aria-live")).toBe("polite");
    expect(live.textContent).toBe("Spending is close to the monthly limit.");
  });

  it("closes the inspector's selection with Escape", async () => {
    const user = userEvent.setup();
    const { onSelect } = show(twoAgentRun(), "researcher");
    screen.getByTestId("office-desk-researcher").focus();
    await user.keyboard("{Escape}");
    expect(onSelect).toHaveBeenCalledWith(null);
  });

  it("offers the camera's moves as named buttons", () => {
    show(twoAgentRun());
    const controls = within(screen.getByRole("group", { name: "View of the office" }));
    for (const name of ["Follow the work", "Show the whole room", "Zoom in", "Zoom out"]) {
      expect(controls.getByRole("button", { name })).toBeDefined();
    }
    expect(controls.getByRole("button", { name: "Follow the work" }).getAttribute("aria-pressed")).toBe("true");
  });
});
