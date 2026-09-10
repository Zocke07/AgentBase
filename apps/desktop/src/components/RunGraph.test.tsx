import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";


import { reduceAll } from "../state/reducer";
import { twoAgentRun } from "../test/log";

import { RunGraph } from "./RunGraph";

/**
 * The graph.
 *
 * These tests exist partly for their own sake and partly to keep
 * `replayIdentity.test.tsx` honest: if React Flow rendered nothing in jsdom,
 * that test would be comparing two empty containers and passing for no reason.
 * Asserting the node content is here is what rules that out.
 */

const view = () => reduceAll(twoAgentRun());

function graph(selected: string | null = null) {
  return render(
    <RunGraph view={view()} selectedAgent={selected} onSelectAgent={vi.fn()} />,
  );
}

describe("RunGraph", () => {
  it("renders a node per agent, with its name and role", () => {
    const { getByTestId } = graph();

    expect(getByTestId("agent-node-supervisor").textContent).toContain("supervisor");
    expect(getByTestId("agent-node-researcher").textContent).toContain("Gathers source material");
  });

  it("shows each agent's model on its node", () => {
    const { getByTestId } = graph();

    expect(getByTestId("agent-node-researcher").textContent).toContain("qwen3:4b");
  });

  it("colours a node by what the agent is doing", () => {
    const { getByTestId } = graph();

    // Both agents finished in the fixture.
    expect(getByTestId("agent-node-researcher").className).toContain("agent-node--completed");
  });

  it("marks an agent as waiting while an approval is outstanding", () => {
    const events = twoAgentRun();
    const upto = events.findIndex((event) => event.type === "approval.requested") + 1;
    const { getByTestId } = render(
      <RunGraph
        view={reduceAll(events.slice(0, upto))}
        selectedAgent={null}
        onSelectAgent={vi.fn()}
      />,
    );

    const node = getByTestId("agent-node-researcher");
    expect(node.className).toContain("agent-node--waiting");
    expect(node.textContent).toContain("waiting for approval");
  });

  it("marks the selected node", () => {
    const { getByTestId } = graph("researcher");

    expect(getByTestId("agent-node-researcher").className).toContain("agent-node--selected");
    expect(getByTestId("agent-node-supervisor").className).not.toContain("agent-node--selected");
  });

  it("says so when there are no agents yet", () => {
    const { getByTestId } = render(
      <RunGraph
        view={reduceAll([])}
        selectedAgent={null}
        onSelectAgent={vi.fn()}
      />,
    );

    expect(getByTestId("run-graph").textContent).toContain("No agents yet");
  });

  it("lays out the same agents in the same places every time", () => {
    /* The layout has to be arithmetic rather than solved, or two renders of one
       run put the nodes in different places and the replay criterion fails for
       a reason unrelated to the events. */
    const first = graph().container.innerHTML;
    const second = graph().container.innerHTML;

    expect(second).toBe(first);
  });
});
