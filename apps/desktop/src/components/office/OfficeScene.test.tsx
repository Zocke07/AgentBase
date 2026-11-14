import { readFileSync } from "node:fs";
import { join } from "node:path";

import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { placeOffice } from "../../lib/officeLayout";
import { nowLine } from "../../state/describe";
import { officeOf, type Board } from "../../state/office";
import { reduceAll } from "../../state/reducer";
import { LogBuilder, twoAgentRun } from "../../test/log";
import { scenario, SCENARIOS } from "../../test/scenarios";

import { OfficeScene } from "./OfficeScene";
import { boardCardHeight, cardsOf, deskReach, labelGeometry } from "./estimates";

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
  }, 20_000);
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

  it("unselects a selected desk when it is pressed again", async () => {
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

  it("leaves the board's card more room the more it shows, up to its limits", () => {
    const base: Board = { goal: "Short", status: "running", statusLabel: "running", claim: null, memoryPath: null, documents: [], unrecognised: [] };
    const file = (path: string): Board["documents"][number] => ({ path, kind: "file" });
    const short = boardCardHeight(base);
    const longGoal = boardCardHeight({ ...base, goal: "x".repeat(400) });
    const claimed = boardCardHeight({ ...base, claim: { kind: "summary", text: "y".repeat(400) } });
    const filed = boardCardHeight({ ...base, documents: ["a", "b", "c", "d", "e"].map(file) }, "near");
    expect(longGoal).toBeGreaterThan(short);
    // Clamped in CSS to two lines of goal, three of claim and two file names with a count.
    expect(longGoal).toBe(boardCardHeight({ ...base, goal: "x".repeat(4000) }));
    expect(claimed).toBe(boardCardHeight({ ...base, claim: { kind: "summary", text: "y".repeat(4000) } }));
    expect(filed).toBe(boardCardHeight({ ...base, documents: ["a", "b", "c"].map(file) }, "near"));
    expect(filed).toBeGreaterThan(boardCardHeight({ ...base, documents: ["a"].map(file) }, "near"));
    // Further out the board does not list files, so they take no room.
    expect(boardCardHeight({ ...base, documents: ["a", "b", "c"].map(file) }, "mid")).toBe(short);
  });

  it("places labels by the geometry the camera estimates with, never by a copy of it", () => {
    // The camera leaves room for labels from these numbers; if the stylesheet
    // placed them by numbers of its own, the two could drift apart unseen.
    const css = readFileSync(join(import.meta.dirname, "../../styles/office.css"), "utf8");
    for (const name of Object.keys(labelGeometry())) expect(css, name).toContain(`var(${name})`);
    expect(css).not.toMatch(/\b(98|28|44|34)px\b|\b(4\.4|14|11)rem\b/);
    const stage = show(twoAgentRun()).container.querySelector<HTMLElement>(".office__stage");
    if (stage === null) throw new Error("no stage was drawn");
    for (const [name, value] of Object.entries(labelGeometry())) expect(stage.style.getPropertyValue(name)).toBe(String(value));
  });

  it("stacks a sheet in a desk's tray per file it wrote, and the library's books on the lead desk", () => {
    const view = reduceAll(scenario("morning-collection").events);
    const model = officeOf(view);
    const { container } = render(<OfficeScene model={model} description={nowLine(view)} selectedAgent={null} onSelectAgent={vi.fn()} />);
    const sheets = container.querySelectorAll(".office-box--paper").length;
    const expected = [...(model.lead === null ? [] : [model.lead]), ...model.desks].reduce((total, each) => total + Math.min(each.documents.length, 4), 0);
    expect(sheets).toBe(expected);
    expect(sheets).toBeGreaterThan(0);
    expect(container.querySelectorAll(".office-box--book")).toHaveLength(Math.min(model.library.length, 4));
  });

  it("poses each figure by its activity, raises a card in the question's risk, and lights the lamp while it works", () => {
    // The pose itself is CSS keyed on the activity; the drawing carries the
    // activity, both arms, and the card only while a person is asked.
    let raised = 0;
    for (const [id, cursor] of [["shell-question", undefined], ["two-agents", undefined], ["morning-collection", 40]] as const) {
      const events = scenario(id).events.slice(0, cursor);
      const view = reduceAll(events);
      const model = officeOf(view);
      const { container, unmount } = render(<OfficeScene model={model} description={nowLine(view)} selectedAgent={null} onSelectAgent={vi.fn()} />);
      const seated = [...(model.lead === null ? [] : [model.lead]), ...model.desks].filter((each) => !each.ghost);
      const figures = [...container.querySelectorAll(".office-character")];
      expect(figures).toHaveLength(seated.length);
      for (const figure of figures) expect(figure.querySelectorAll(".office-character__arm")).toHaveLength(2);
      expect(new Set(figures.map((figure) => figure.getAttribute("class")))).toEqual(new Set(seated.map((each) => `office-character office-character--${each.activity}`)));
      const waiting = seated.filter((each) => each.activity === "waiting");
      const cards = [...container.querySelectorAll(".office-character__card")];
      expect(cards, id).toHaveLength(waiting.length);
      raised += cards.length;
      for (const card of cards) expect(card.getAttribute("class")).toMatch(/office-character__card--(low|medium|high)$/);
      expect(container.querySelectorAll(".office-lamp--on"), id).toHaveLength(seated.filter((each) => each.activity !== "completed").length);
      unmount();
    }
    expect(raised).toBeGreaterThan(0);
  });

  it("hangs the lead desk's plate and papers in front of it, and a worker's plate over its head", () => {
    // The lead desk's plate over its head would lie under the papers of the
    // desk behind it in the first row; in front of it there is only floor.
    show(twoAgentRun());
    const lead = screen.getByTestId("office-desk-supervisor");
    const worker = screen.getByTestId("office-desk-researcher");
    expect(lead.parentElement?.className).toBe("office-desk__front");
    expect(worker.parentElement?.classList.contains("office-desk")).toBe(true);
    const papers = lead.closest(".office-desk")?.querySelector(".office-desk__papers");
    if (papers) expect(papers.parentElement?.className).toBe("office-desk__front");
  });

  it("estimates the reach of a desk's words where they hang: the lead's in front, a worker's over its head", () => {
    // At the start of the run's work the supervisor is busy with a call, the
    // researcher is not yet speaking; at the end both are done.
    const model = officeOf(reduceAll(scenario("two-agents").events));
    const lead = model.lead;
    const worker = model.desks[0];
    if (lead === null || worker === undefined) throw new Error("the scenario has a lead and a worker");
    const leadReach = deskReach(lead, 0.9, 64);
    const workerReach = deskReach(worker, 0.9, 64);
    expect(leadReach.below).toBeGreaterThan(0);
    expect(workerReach.above).toBeGreaterThan(0);
    // A lead with no bubble has nothing over its head; a quiet worker nothing in front.
    if (lead.bubble === null) expect(leadReach.above).toBe(0);
    if (worker.quiet) expect(workerReach.below).toBe(0);
    // A bubble reaches higher than a plate alone.
    const speaking = { ...worker, bubble: { kind: "speech" as const, text: "A finding worth saying in a few words." } };
    expect(deskReach(speaking, 0.9, 64).above).toBeGreaterThan(workerReach.above);
    // The words keep their size: drawn further out, they reach less far past the room.
    expect(deskReach(lead, 0.5, 64).below).toBeLessThan(leadReach.below);
    // The camera leaves the lead's words room in front, and none for a room without a lead.
    expect(cardsOf(model.board, model.reception, lead).lead).toBeGreaterThan(0);
    expect(cardsOf(model.board, model.reception, null).lead).toBe(0);
    // A question waiting adds a line to the reception's card.
    const asking = cardsOf(model.board, { ...model.reception, waiting: 1 }, lead).reception;
    expect(asking).toBeGreaterThan(cardsOf(model.board, model.reception, lead).reception);
  });

});
