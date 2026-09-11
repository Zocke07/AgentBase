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
