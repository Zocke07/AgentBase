import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { writtenFiles } from "../state/files";
import { reduceAll } from "../state/reducer";
import { twoAgentRun } from "../test/log";
import { scenario, SCENARIOS } from "../test/scenarios";

import { RunPanel } from "./RunPanel";

// The panel keeps the log's fold in browser storage; a test that fails
// before clearing what it set must not change the tests after it.
afterEach(() => {
  localStorage.clear();
});

/**
 * `RunPanel` decides what "the selected agent" means for the office, the detail
 * aside and the log together, so the three cannot disagree.
 */

describe("the selected agent", () => {
  it("is nobody when the cursor sits before that agent's first event", () => {
    /* `selectedAgent` is the caller's state and survives a scrub. Scrubbed to
       before the researcher spawned, the fold has no such agent: the log's
       select showed a blank, every row was hidden behind a filter on a name
       not in the list, and the aside rendered a node that did not exist yet. */
    const events = twoAgentRun();
    const beforeResearcher = events.findIndex((event) => event.agent_id === "researcher");

    // The log starts folded beside the room; open, it shows its rows.
    localStorage.setItem("agentbase.flag.runs.office.log.collapsed", "0");
    render(
      <RunPanel
        view={reduceAll(events.slice(0, beforeResearcher))}
        events={events}
        cursor={beforeResearcher}
        selectedAgent="researcher"
        onSelectAgent={vi.fn()}
        onCursorChange={vi.fn()}
        approvalReadOnly="replay"
        onResolveApproval={() => Promise.resolve()}
      />,
    );

    expect(screen.queryByTestId("agent-detail")).toBeNull();
    expect(screen.getByLabelText<HTMLSelectElement>("Agent").value).toBe("all");
    expect(screen.getAllByRole("listitem")).toHaveLength(beforeResearcher);
    localStorage.removeItem("agentbase.flag.runs.office.log.collapsed");
  });
});

describe("the scrubber", () => {
  it("keeps the same row shape at the head and off it", () => {
    /* The notice and the "Jump to end" button used to appear only when
       scrubbed, in the same flex row as the range input, so dragging the thumb
       off the end made the track shrink under the pointer and the thumb jump,
       and dragging it back made the text vanish. The slot is always there; what
       it says changes. */
    const events = twoAgentRun();
    const props = {
      events,
      selectedAgent: null,
      onSelectAgent: vi.fn(),
      onCursorChange: vi.fn(),
      approvalReadOnly: "replay" as const,
      onResolveApproval: () => Promise.resolve(),
    };

    const { rerender } = render(<RunPanel {...props} view={reduceAll(events)} cursor={events.length} />);
    const atHead = screen.getByTestId("scrub-state");
    expect(atHead.textContent).toContain("latest");
    expect(screen.getByRole("slider").getAttribute("aria-valuetext")).toBe(
      "Event 28 of 28. Latest event.",
    );
    expect(screen.queryByRole("button", { name: "Jump to end" })).toBeNull();

    rerender(<RunPanel {...props} view={reduceAll(events.slice(0, 5))} cursor={5} />);
    const scrubbed = screen.getByTestId("scrub-state");
    expect(scrubbed.textContent).toContain("earlier point");
    expect(screen.getByRole("slider").getAttribute("aria-valuetext")).toBe(
      "Event 5 of 28. Earlier point in this run.",
    );
    expect(screen.getByRole("button", { name: "Jump to end" })).toBeDefined();

    // The counter reserves room for the widest reading it will show, so
    // "5 / 28" and "28 / 28" take the same width and the track beside them
    // does not move as the number changes.
    expect(screen.getByTestId("scrub-position").style.minWidth).toBe("7ch");
  });
});

describe("the agent inspector", () => {
  it("shows what the selected agent said and did with its tools, at this cursor", () => {
    const events = twoAgentRun();
    const onSelectAgent = vi.fn();

    render(
      <RunPanel
        view={reduceAll(events)}
        events={events}
        cursor={events.length}
        selectedAgent="researcher"
        onSelectAgent={onSelectAgent}
        onCursorChange={vi.fn()}
        approvalReadOnly="finished"
        onResolveApproval={() => Promise.resolve()}
      />,
    );

    const detail = screen.getByTestId("agent-detail");
    expect(screen.getByTestId("agent-last-message").textContent).toContain("Revenue up 12% QoQ");
    const calls = screen.getByTestId("agent-tool-calls");
    expect(calls.textContent).toContain("read_file");
    expect(calls.textContent).toContain("refused by the sandbox");
    expect(calls.textContent).toContain("write_file");
    expect(calls.textContent).toContain("Wrote 31 characters");
    expect(detail.textContent).toContain("done");

    screen.getByRole("button", { name: "Close the agent detail" }).click();
    expect(onSelectAgent).toHaveBeenCalledWith(null);
  });
});

describe("the panels", () => {
  const props = () => {
    const events = twoAgentRun();
    return {
      events,
      view: reduceAll(events),
      cursor: events.length,
      selectedAgent: null,
      onSelectAgent: vi.fn(),
      onCursorChange: vi.fn(),
      approvalReadOnly: null,
      onResolveApproval: () => Promise.resolve(),
    };
  };

  it("fills the window with the office until Esc, and offers the summary and canvas handles", () => {
    // The log starts folded, which leaves no canvas divider.
    localStorage.setItem("agentbase.flag.runs.office.log.collapsed", "0");
    render(<RunPanel {...props()} />);
    localStorage.removeItem("agentbase.flag.runs.office.log.collapsed");
    const canvas = screen.getByTestId("office").parentElement;
    expect(canvas?.className).not.toContain("run-panel__canvas--expanded");
    expect(screen.getByRole("separator", { name: "Resize the summary" })).toBeDefined();
    expect(screen.getByRole("separator", { name: "Resize the canvas" })).toBeDefined();

    fireEvent.click(screen.getByRole("button", { name: "Full screen" }));
    expect(canvas?.className).toContain("run-panel__canvas--expanded");
    // The divider beneath the canvas means nothing while it fills the window.
    expect(screen.queryByRole("separator", { name: "Resize the canvas" })).toBeNull();
    expect(screen.getByRole("button", { name: "Leave full screen" })).toBeDefined();

    fireEvent.keyDown(window, { key: "Escape" });
    expect(canvas?.className).not.toContain("run-panel__canvas--expanded");
  });
});

describe("the office in full screen", () => {
  it("closes the inspector on the first Escape and leaves full screen on the next", () => {
    const events = twoAgentRun();
    const onSelectAgent = vi.fn();
    const { rerender } = render(
      <RunPanel
        view={reduceAll(events)}
        events={events}
        cursor={events.length}
        selectedAgent="supervisor"
        onSelectAgent={onSelectAgent}
        onCursorChange={vi.fn()}
        approvalReadOnly="finished"
        onResolveApproval={() => Promise.resolve()}
      />,
    );
    const canvas = screen.getByTestId("office").parentElement;
    fireEvent.click(screen.getByRole("button", { name: "Full screen" }));
    expect(canvas?.className).toContain("run-panel__canvas--expanded");

    fireEvent.keyDown(screen.getByTestId("office-desk-supervisor"), { key: "Escape" });
    expect(onSelectAgent).toHaveBeenCalledWith(null);
    expect(canvas?.className).toContain("run-panel__canvas--expanded");

    rerender(
      <RunPanel
        view={reduceAll(events)}
        events={events}
        cursor={events.length}
        selectedAgent={null}
        onSelectAgent={onSelectAgent}
        onCursorChange={vi.fn()}
        approvalReadOnly="finished"
        onResolveApproval={() => Promise.resolve()}
      />,
    );
    fireEvent.keyDown(screen.getByTestId("office-desk-supervisor"), { key: "Escape" });
    expect(canvas?.className).not.toContain("run-panel__canvas--expanded");
  });
});

describe("the inspector", () => {
  it("closes with Escape from inside it, and the office stays full screen", () => {
    const events = twoAgentRun();
    const onSelectAgent = vi.fn();
    render(
      <RunPanel
        view={reduceAll(events)}
        events={events}
        cursor={events.length}
        selectedAgent="supervisor"
        onSelectAgent={onSelectAgent}
        onCursorChange={vi.fn()}
        approvalReadOnly="finished"
        onResolveApproval={() => Promise.resolve()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Full screen" }));
    const detail = screen.getByTestId("agent-detail");
    expect(detail.parentElement?.className).toContain("run-panel__canvas--expanded");
    fireEvent.keyDown(within(detail).getByRole("button", { name: "Close the agent detail" }), { key: "Escape" });
    expect(onSelectAgent).toHaveBeenCalledWith(null);
    expect(detail.parentElement?.className).toContain("run-panel__canvas--expanded");
  });
});

describe("the inspector's files", () => {
  it("lists the files the selected agent wrote, each opening in Knowledge", () => {
    const { events } = scenario("morning-collection");
    const view = reduceAll(events);
    const writer = view.toolCalls.find((call) => call.result !== null && call.tool === "write_file");
    if (writer === undefined) throw new Error("the scenario writes a file");
    const onOpenFile = vi.fn();
    render(
      <RunPanel
        view={view}
        events={events}
        cursor={events.length}
        selectedAgent={writer.agent}
        onSelectAgent={vi.fn()}
        onCursorChange={vi.fn()}
        approvalReadOnly="finished"
        onResolveApproval={() => Promise.resolve()}
        onOpenFile={onOpenFile}
      />,
    );
    const files = screen.getByTestId("agent-files");
    const path = String(writer.args.path);
    fireEvent.click(within(files).getByRole("button", { name: path }));
    expect(onOpenFile).toHaveBeenCalledWith(path);
  });

  it("opens a note the agent wrote as a note, as the run summary does", () => {
    // Whichever made-up run writes a Markdown note with its own call.
    const found = SCENARIOS.map((entry) => {
      const view = reduceAll(entry.events);
      const note = writtenFiles(view).find((file) => file.kind === "note");
      const writer = view.toolCalls.find((call) => call.result !== null && call.args.path === note?.path);
      return { events: entry.events, view, note, writer };
    }).find((entry) => entry.note !== undefined && entry.writer !== undefined);
    if (found?.note === undefined || found.writer === undefined) throw new Error("a scenario writes a note");
    const { events, view, note, writer } = found;
    const onOpenNote = vi.fn();
    const onOpenFile = vi.fn();
    render(
      <RunPanel
        view={view}
        events={events}
        cursor={events.length}
        selectedAgent={writer.agent}
        onSelectAgent={vi.fn()}
        onCursorChange={vi.fn()}
        approvalReadOnly="finished"
        onResolveApproval={() => Promise.resolve()}
        onOpenNote={onOpenNote}
        onOpenFile={onOpenFile}
      />,
    );
    fireEvent.click(within(screen.getByTestId("agent-files")).getByRole("button", { name: note.path }));
    expect(onOpenNote).toHaveBeenCalledWith(note.path, null);
    expect(onOpenFile).not.toHaveBeenCalled();
  });
});

describe("the event log's fold", () => {
  const events = twoAgentRun();
  const panel = () => (
    <RunPanel
      view={reduceAll(events)}
      events={events}
      cursor={events.length}
      selectedAgent={null}
      onSelectAgent={vi.fn()}
      onCursorChange={vi.fn()}
      approvalReadOnly="finished"
      onResolveApproval={() => Promise.resolve()}
    />
  );

  it("opens on the office, with the summary's detail and the log folded away for the room", () => {
    localStorage.removeItem("agentbase.flag.runs.office.log.collapsed");
    const { unmount } = render(panel());
    expect(screen.getByTestId("office")).toBeDefined();
    // The diagram is retired (D8): nothing offers another drawing.
    expect(screen.queryByRole("radio", { name: "Diagram" })).toBeNull();
    expect(screen.getByRole("button", { name: "Event log" }).getAttribute("aria-expanded")).toBe("false");
    // The title and the figures stay; what the room shows is one press away.
    expect(screen.getByTestId("fact-tool-calls").textContent).toBe("2");
    const more = screen.getByTestId("run-more");
    expect(more.hasAttribute("open")).toBe(false);
    expect(more.contains(screen.getByTestId("run-claim"))).toBe(true);

    // Opening the log is remembered.
    fireEvent.click(screen.getByRole("button", { name: "Event log" }));
    expect(screen.getByRole("button", { name: "Event log" }).getAttribute("aria-expanded")).toBe("true");
    unmount();
    render(panel());
    expect(screen.getByRole("button", { name: "Event log" }).getAttribute("aria-expanded")).toBe("true");
    localStorage.removeItem("agentbase.flag.runs.office.log.collapsed");
  });

  it("gives the log's room to the canvas and remembers the choice", () => {
    localStorage.setItem("agentbase.flag.runs.office.log.collapsed", "0");
    const { unmount } = render(panel());
    expect(screen.getByLabelText("Resize the canvas")).toBeDefined();

    fireEvent.click(screen.getByRole("button", { name: "Event log" }));

    expect(screen.getByTestId("run-projection").className).toContain("run-projection--log-collapsed");
    // Nothing below the canvas to divide the room with.
    expect(screen.queryByLabelText("Resize the canvas")).toBeNull();
    unmount();

    render(panel());
    expect(screen.getByRole("button", { name: "Event log" }).getAttribute("aria-expanded")).toBe("false");
    localStorage.removeItem("agentbase.flag.runs.office.log.collapsed");
  });
});
