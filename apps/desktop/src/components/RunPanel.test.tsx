import { render, screen } from "@testing-library/react";
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
       scrubbed, in the same flex row as the range input — so dragging the thumb
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
