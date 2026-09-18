import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";


import { edgesFor } from "../state/graph";
import { reduceAll } from "../state/reducer";
import { LogBuilder, twoAgentRun } from "../test/log";

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

  it("names the tool an agent is running, and stops once the result is in", () => {
    /* Between `tool.called` and `tool.result` the agent is doing the one thing
       the log is most interested in. It used to read "waiting for approval"
       here (the label the approval left behind) for as long as the tool ran. */
    const events = twoAgentRun();
    const called = events.findIndex((event) => event.type === "tool.called" && event.agent_id === "researcher") + 1;
    const running = render(
      <RunGraph view={reduceAll(events.slice(0, called))} selectedAgent={null} onSelectAgent={vi.fn()} />,
    );
    const node = running.getByTestId("agent-node-researcher");
    expect(node.className).toContain("agent-node--executing");
    expect(node.textContent).toContain("running write_file");
    running.unmount();

    const finished = render(
      <RunGraph view={reduceAll(events.slice(0, called + 1))} selectedAgent={null} onSelectAgent={vi.fn()} />,
    );
    expect(finished.getByTestId("agent-node-researcher").textContent).not.toContain("running");
  });

  it("tints a node whose last event was an error, and says what it was", () => {
    const log = new LogBuilder();
    const errored = reduceAll([
      log.add("agent.spawned", { role: "w" }, "w"),
      log.add("tool.error", { tool: "run_shell", error: "timed out after 30s" }, "w"),
    ]);
    const { getByTestId } = render(
      <RunGraph view={errored} selectedAgent={null} onSelectAgent={vi.fn()} />,
    );

    const node = getByTestId("agent-node-w");
    expect(node.className).toContain("agent-node--errored");
    expect(node.textContent).toContain("timed out");
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

  it("gives every node the handles an edge attaches to", () => {
    /* The regression this file exists for, found by running a real run and
       reading the browser console. `AgentCard` rendered no `<Handle>`, so React
       Flow refused every edge touching it, logging a warning and drawing
       nothing. The graph looked complete with every handoff missing, and every
       test here passed, because they all asserted node content.

       React Flow will not lay out an SVG edge in jsdom at all (it needs real
       measurement), so the drawn edge is verified in a browser rather than
       here. What is checkable here is the thing that was actually wrong. */
    const { container } = graph();

    const nodes = container.querySelectorAll('[data-testid^="agent-node-"]');
    expect(nodes.length).toBeGreaterThan(0);

    for (const node of nodes) {
      expect(node.querySelector(".react-flow__handle-left")).not.toBeNull();
      expect(node.querySelector(".react-flow__handle-right")).not.toBeNull();
    }
  });

  it("frames the run with a goal card and an outcome card", () => {
    const { getByTestId } = graph();

    expect(getByTestId("goal-node").textContent).toContain("Summarise the quarterly report");
    expect(getByTestId("goal-node").textContent).toContain("from this window");
    expect(getByTestId("outcome-node").textContent).toContain("Quarterly report summarised and saved");
    expect(getByTestId("outcome-node").className).toContain("end-node--completed");
    expect(getByTestId("outcome-node").textContent).toContain("2 agents · 2 tool calls");
  });

  it("shows what an agent did with each tool as a chip on its card", () => {
    const { getByTestId } = graph();

    const chips = [...getByTestId("agent-node-researcher").querySelectorAll(".agent-node__tool")];
    // The chip shows the verb; the full name and the counts are in its tooltip.
    expect(chips.map((chip) => chip.textContent)).toEqual(["read1", "write1"]);
    expect(chips[0]?.getAttribute("title")).toBe("read_file: 0 executed, 1 denied");
    expect(chips[0]?.className).toContain("agent-node__tool--denied");
  });

  it("says the outcome is still in progress while the run is", () => {
    const events = twoAgentRun();
    const { getByTestId } = render(
      <RunGraph view={reduceAll(events.slice(0, 9))} selectedAgent={null} onSelectAgent={vi.fn()} />,
    );

    expect(getByTestId("outcome-node").textContent).toContain("Still in progress");
    expect(getByTestId("outcome-node").className).toContain("end-node--running");
  });

  it("derives one edge per ordered pair, counting repeats", () => {
    /* A supervisor delegating twice to the same worker would otherwise draw two
       identical lines on top of each other and lose the count. Asserted on the
       derivation rather than the drawing, for the reason above. */
    const events = twoAgentRun();
    const handoff = events[8];
    if (handoff === undefined) throw new Error("fixture changed shape");

    const once = edgesFor(reduceAll(events));
    const twice = edgesFor(reduceAll([...events, { ...handoff, seq: 999, id: 999 }]));

    expect(once).toHaveLength(1);
    expect(once[0]).toMatchObject({ id: "supervisor->researcher", source: "supervisor", target: "researcher" });
    expect(once[0]?.label).toContain("handoff");
    expect(twice[0]?.label).toBe("2 handoffs");
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
