import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { reduceAll } from "../state/reducer";
import { twoAgentRun } from "../test/log";

import { RunPanel } from "./RunPanel";

/**
 * `RunPanel` decides what "the selected agent" means for the graph, the detail
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
    expect(screen.queryByRole("button", { name: "Jump to end" })).toBeNull();

    rerender(<RunPanel {...props} view={reduceAll(events.slice(0, 5))} cursor={5} />);
    const scrubbed = screen.getByTestId("scrub-state");
    expect(scrubbed.textContent).toContain("earlier point");
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

  it("fills the window with the canvas until Esc, and offers the summary and canvas handles", () => {
    render(<RunPanel {...props()} />);
    const canvas = screen.getByTestId("run-graph").parentElement;
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
