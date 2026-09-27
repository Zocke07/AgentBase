import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { sentenceFor } from "../state/describe";
import { LogBuilder, twoAgentRun } from "../test/log";

import { EventLog } from "./EventLog";

/**
 * The log panel's filters are component state (which rows a person is looking
 * at is a fact about the person), and that is exactly why they can go stale:
 * the run underneath them changes and the filter does not.
 */

function log(events = twoAgentRun(), cursor = events.length) {
  const onSelectAgent = vi.fn();
  const agents = [...new Set(events.map((event) => event.agent_id).filter((id): id is string => id !== null))];
  const rendered = render(
    <EventLog
      events={events}
      cursor={cursor}
      agents={agents}
      selectedAgent={null}
      onSelectAgent={onSelectAgent}
    />,
  );
  return { ...rendered, onSelectAgent, agents };
}

const typeFilter = () => screen.getByLabelText<HTMLSelectElement>("Type");
const rowTypes = () =>
  [...document.querySelectorAll(".log__type")].map((cell) => cell.textContent);

describe("a row", () => {
  it("opens to show its whole payload", async () => {
    /* Rows are one-liners. The panel's job is to be the thing you check the
       reduced view against, and a one-liner cannot show a tool result or the
       message list an `llm.request` carried. */
    const user = userEvent.setup();
    log();

    const row = document.querySelector<HTMLElement>(".log__row");
    if (row === null) throw new Error("no row");
    expect(screen.queryByTestId("log-payload")).toBeNull();

    await user.click(row);

    const payload = screen.getByTestId("log-payload");
    expect(payload.textContent).toContain('"goal"');
    expect(payload.textContent).toContain("Summarise the quarterly report");
    expect(row.getAttribute("aria-expanded")).toBe("true");

    await user.click(row);
    expect(screen.queryByTestId("log-payload")).toBeNull();
  });
});

describe("filtering by type", () => {
  it("narrows the rows to one family", async () => {
    const user = userEvent.setup();
    log();

    await user.selectOptions(typeFilter(), "tool");

    expect(rowTypes().every((type) => type.startsWith("tool."))).toBe(true);
  });

  it("narrows the rows to one exact type", async () => {
    /* A family is too coarse to isolate `tool.denied` from `tool.called`,
       which is the question the log exists to answer. */
    const user = userEvent.setup();
    log();

    await user.selectOptions(typeFilter(), "tool.denied");

    expect(rowTypes()).toEqual(["tool.denied"]);
  });

  it("hides streamed tokens by default, and says how many", async () => {
    /* 232 of a real run's 288 events were `llm.token`. They are what the
       agent detail shows as text; in the log they bury everything else. */
    const user = userEvent.setup();
    log();

    expect(rowTypes()).not.toContain("llm.token");
    const toggle = screen.getByLabelText<HTMLInputElement>(/tokens/);
    expect(toggle.checked).toBe(false);
    expect(toggle.closest("label")?.textContent).toContain("2");

    await user.click(toggle);

    expect(rowTypes()).toContain("llm.token");
  });

  it("finds rows by text", async () => {
    const user = userEvent.setup();
    log();

    await user.type(screen.getByLabelText("Find"), "notes.txt");

    expect(rowTypes().length).toBeGreaterThan(0);
    expect(rowTypes().length).toBeLessThan(10);
    for (const row of document.querySelectorAll(".log__row")) {
      expect(row.textContent).toContain("notes.txt");
    }
  });

  it("drops a filter the new run has no rows for, instead of showing an empty log", async () => {
    /* Pick a Discord run, filter to `channel.*`, pick a run from this window:
       `channel` is not among its families, the select showed blank, and every
       row was hidden behind a filter the user could not see. */
    const user = userEvent.setup();
    const discord = new LogBuilder("run-discord");
    const chatRun = [
      discord.add("channel.inbound", { channel: "discord", identity: "owner", text: "hi" }),
      discord.add("run.started", { goal: "hi" }),
      discord.add("run.completed", { summary: "done" }),
    ];
    const { rerender } = log(chatRun, chatRun.length);
    await user.selectOptions(typeFilter(), "channel");
    expect(screen.getAllByRole("listitem")).toHaveLength(1);

    const local = twoAgentRun();
    rerender(
      <EventLog
        events={local}
        cursor={local.length}
        agents={["supervisor", "researcher"]}
        selectedAgent={null}
        onSelectAgent={vi.fn()}
      />,
    );

    expect(typeFilter().value).toBe("all");
    // Every row except the streamed tokens, which are hidden by default.
    const visible = local.filter((event) => event.type !== "llm.token").length;
    expect(screen.getAllByRole("listitem")).toHaveLength(visible);
  });

  it("falls back to every type when the scrubber moves before the filtered family's first event", async () => {
    /* Same shape, reached by scrubbing rather than by switching runs. */
    const user = userEvent.setup();
    const events = twoAgentRun();
    const firstTool = events.findIndex((event) => event.type.startsWith("tool."));
    const { rerender } = log(events);
    await user.selectOptions(typeFilter(), "tool");

    rerender(
      <EventLog
        events={events}
        cursor={firstTool}
        agents={["supervisor", "researcher"]}
        selectedAgent={null}
        onSelectAgent={vi.fn()}
      />,
    );

    expect(typeFilter().value).toBe("all");
    expect(screen.getAllByRole("listitem")).toHaveLength(firstTool);
  });
});

describe("a long log", () => {
  /* jsdom's stubbed layout gives the scroller a 600px viewport (see
     `test/setup.ts`), so a thousand rows of 30px is far more than fits. */
  function longLog(count: number) {
    const log = new LogBuilder();
    const events = [log.add("run.started", { goal: "long" })];
    for (let index = 1; index < count; index += 1) {
      events.push(log.add("agent.thinking", { step: index }, "supervisor"));
    }
    return events;
  }

  const renderedSeqs = () =>
    [...document.querySelectorAll(".log__seq")].map((cell) => Number(cell.textContent));

  it("renders only the rows in view, and moves the window with the scroll", () => {
    const events = longLog(1000);
    log(events);

    const first = renderedSeqs();
    expect(first.length).toBeGreaterThan(10);
    expect(first.length).toBeLessThan(100);
    // Following the tail: the newest row is in the window.
    expect(first).toContain(1000);
    expect(first).not.toContain(1);

    const scroller = document.querySelector<HTMLElement>(".log__rows");
    if (scroller === null) throw new Error("no scroller");
    act(() => {
      scroller.scrollTop = 0;
      fireEvent.scroll(scroller);
    });

    const top = renderedSeqs();
    expect(top).toContain(1);
    expect(top).not.toContain(1000);
    expect(top.length).toBeLessThan(100);
  });

  it("keeps the spacer as tall as every row, so the scrollbar is honest", () => {
    log(longLog(1000));
    const list = document.querySelector<HTMLElement>(".log__list");
    expect(list?.style.height).toBe(`${String(1000 * 30)}px`);
  });
});

describe("folding", () => {
  function folded(collapsed: boolean, events = twoAgentRun(), cursor = events.length) {
    const onCollapsedChange = vi.fn();
    render(
      <EventLog
        events={events}
        cursor={cursor}
        agents={["supervisor", "researcher"]}
        selectedAgent={null}
        onSelectAgent={vi.fn()}
        collapsed={collapsed}
        onCollapsedChange={onCollapsedChange}
      />,
    );
    return onCollapsedChange;
  }

  it("shows one line, the newest step, instead of the rows", () => {
    /* Folded is for someone who wants what is happening now, not the
       record: no rows, no filters, one sentence and how much is behind it. */
    const events = twoAgentRun();
    const last = events.at(-1);
    if (last === undefined) throw new Error("fixture is empty");
    folded(true, events);

    expect(document.querySelectorAll(".log__item")).toHaveLength(0);
    expect(screen.queryByLabelText("Type")).toBeNull();
    expect(screen.getByTestId("log-latest").textContent).toBe(sentenceFor(last));
    expect(screen.getByTestId("event-log").textContent).toContain(`${String(events.length)} events`);
  });

  it("never names a streamed token as the newest step", () => {
    /* Mid-answer, the newest events are tokens: a fragment of a word is not a
       step anyone can follow. */
    const events = twoAgentRun();
    const token = events.findIndex((event) => event.type === "llm.token");
    const before = events[token - 1];
    if (token < 1 || before === undefined) throw new Error("fixture has no token after an event");
    folded(true, events, token + 1);

    expect(screen.getByTestId("log-latest").textContent).toBe(sentenceFor(before));
  });

  it("says which way the control goes and asks the owner to change it", async () => {
    const user = userEvent.setup();
    const onCollapsedChange = folded(false);

    const control = screen.getByRole("button", { name: "Event log" });
    expect(control.getAttribute("aria-expanded")).toBe("true");
    expect(control.getAttribute("aria-controls")).toBe("event-log-rows");
    await user.click(control);

    expect(onCollapsedChange).toHaveBeenCalledWith(true);
  });

  it("keeps a chosen filter while folded", async () => {
    /* The rows stay mounted behind `hidden`, so folding to glance at the
       canvas does not throw away a filter the person set up. */
    const user = userEvent.setup();
    const events = twoAgentRun();
    const { rerender } = render(
      <EventLog events={events} cursor={events.length} agents={[]} selectedAgent={null} onSelectAgent={vi.fn()} onCollapsedChange={vi.fn()} />,
    );
    await user.selectOptions(typeFilter(), "tool");

    rerender(
      <EventLog events={events} cursor={events.length} agents={[]} selectedAgent={null} onSelectAgent={vi.fn()} collapsed onCollapsedChange={vi.fn()} />,
    );
    rerender(
      <EventLog events={events} cursor={events.length} agents={[]} selectedAgent={null} onSelectAgent={vi.fn()} collapsed={false} onCollapsedChange={vi.fn()} />,
    );

    expect(typeFilter().value).toBe("tool");
  });
});
