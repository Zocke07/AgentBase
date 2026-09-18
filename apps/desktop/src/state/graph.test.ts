import { describe, expect, it } from "vitest";

import { LogBuilder, twoAgentRun } from "../test/log";

import {
  edgesFor,
  GOAL,
  layout,
  NODE_HEIGHT,
  NODE_WIDTH,
  OUTCOME,
  toolUsesFor,
  viewportFor,
  workflowEdges,
} from "./graph";
import { reduceAll } from "./reducer";


/**
 * Turning a run into a graph.
 *
 * The camera tests are here because of a measured failure. React Flow's own
 * `fitView` frames what it has measured, so a run watched from the start framed
 * itself at `scale(1.43)` while the same run replayed framed itself at
 * `scale(1.25)`: 10% of the canvas's pixels different, with an identical graph
 * underneath. That is BUILD_SPEC §5 Phase 7's "pixel-identical" criterion
 * failing on the one part of the canvas that was not a projection of the log.
 *
 * `viewportFor` replaces it with arithmetic, so the camera is a function of the
 * nodes and the pane and nothing else.
 */

const view = () => reduceAll(twoAgentRun());

describe("layout", () => {
  it("reads left to right: the goal, the supervisor, the workers, the outcome", () => {
    const nodes = layout(view(), null);
    const x = (id: string) => nodes.find((node) => node.id === id)?.position.x ?? Number.NaN;

    expect(x(GOAL)).toBeLessThan(x("supervisor"));
    expect(x("supervisor")).toBeLessThan(x("researcher"));
    expect(x("researcher")).toBeLessThan(x(OUTCOME));
  });

  it("declares each node's size rather than leaving it to be measured", () => {
    /* A node without dimensions is only measured once its element has been laid
       out, and anything downstream of measurement then depends on when the node
       appeared rather than on the log. */
    for (const node of layout(view(), null)) {
      expect(node.width).toBeGreaterThan(0);
      expect(node.height).toBeGreaterThan(0);
      if (node.type === "agent") {
        expect(node.width).toBe(NODE_WIDTH);
        expect(node.height).toBe(NODE_HEIGHT);
      }
    }
  });

  it("carries the goal and the outcome on their own cards", () => {
    const nodes = layout(view(), null);

    expect(nodes.find((node) => node.id === GOAL)?.data).toMatchObject({
      goal: "Summarise the quarterly report",
      status: "completed",
    });
    expect(nodes.find((node) => node.id === OUTCOME)?.data).toMatchObject({
      status: "completed",
      claim: { kind: "summary" },
      toolCalls: 2,
    });
  });

  it("sums what each agent did with its tools onto its card", () => {
    const researcher = layout(view(), null).find((node) => node.id === "researcher");

    expect(researcher?.data.tools).toEqual([
      { tool: "read_file", calls: 0, denied: 1, running: false },
      { tool: "write_file", calls: 1, denied: 0, running: false },
    ]);
    expect(layout(view(), null).find((node) => node.id === "supervisor")?.data.delegated).toBe(1);
  });

  it("places the same agents identically every time", () => {
    expect(layout(view(), null)).toEqual(layout(view(), null));
  });

  it("marks the selected node and only that one", () => {
    const nodes = layout(view(), "researcher");

    expect(nodes.find((node) => node.id === "researcher")?.data.selected).toBe(true);
    expect(nodes.find((node) => node.id === "supervisor")?.data.selected).toBe(false);
  });
});

  it("wraps workers into a second column past four", () => {
    /* One column per run put a dozen workers 1600px tall and the camera zoomed
       out until nothing on a node could be read. */
    const log = new LogBuilder();
    const events = [log.add("agent.spawned", { role: "s" }, "supervisor")];
    for (let index = 0; index < 6; index += 1) {
      events.push(log.add("agent.spawned", { role: "w" }, `w${String(index)}`));
    }
    const nodes = layout(reduceAll(events), null);

    const workers = nodes.filter((n) => n.type === "agent" && n.id !== "supervisor");
    const columns = new Set(workers.map((n) => n.position.x));
    expect(columns.size).toBe(2);
    const perColumn = [...columns].map((x) => workers.filter((n) => n.position.x === x).length);
    expect(perColumn).toEqual([4, 2]);
    expect(nodes.find((n) => n.id === OUTCOME)?.position.x).toBeGreaterThan(Math.max(...columns));
  });

  it("is a projection of the cursor: a tool in flight is marked running on its card", () => {
    const events = twoAgentRun();
    const called = events.findIndex((event) => event.type === "tool.called" && event.agent_id === "researcher") + 1;

    expect(toolUsesFor(reduceAll(events.slice(0, called)), "researcher")).toContainEqual({
      tool: "write_file",
      calls: 1,
      denied: 0,
      running: true,
    });
    expect(toolUsesFor(reduceAll(events.slice(0, called + 1)), "researcher")).toContainEqual({
      tool: "write_file",
      calls: 1,
      denied: 0,
      running: false,
    });
  });

  it("draws a handoff to a name the run never spawned as a ghost node", () => {
    /* Watched in Phase 6: after a denial the worker handed off to a
       nonexistent `another_agent`. React Flow drops an edge whose target
       does not exist (with a console warning and nothing drawn), so the
       one handoff that most needs seeing was the one that vanished. */
    const log = new LogBuilder();
    const state = reduceAll([
      log.add("agent.spawned", { role: "w" }, "escaper"),
      log.add("agent.handoff", { to: "another_agent", task: "help" }, "escaper"),
    ]);
    const nodes = layout(state, null);

    const ghost = nodes.find((node) => node.id === "another_agent");
    expect(ghost?.data.ghost).toBe(true);
    expect(nodes.find((node) => node.id === "escaper")?.data.ghost).toBe(false);
    expect(edgesFor(state).map((edge) => [edge.source, edge.target])).toEqual([["escaper", "another_agent"]]);
  });

describe("edgesFor", () => {
  it("makes one edge per handoff", () => {
    expect(edgesFor(view())).toEqual([
      {
        id: "supervisor->researcher",
        source: "supervisor",
        target: "researcher",
        label: "handoff · Find the figures",
      },
    ]);
  });

  it("counts repeats between the same pair into one edge", () => {
    const events = twoAgentRun();
    const handoff = events.find((event) => event.type === "agent.handoff");
    if (handoff === undefined) throw new Error("fixture changed shape");

    const edges = edgesFor(reduceAll([...events, { ...handoff, seq: 999, id: 999 }]));

    expect(edges).toHaveLength(1);
    expect(edges[0]?.label).toBe("2 handoffs");
  });

  it("puts the task on a single handoff's edge", () => {
    const edges = edgesFor(view());

    expect(edges[0]?.label).toContain("Find the figures");
  });

  it("has no edges before anything has been delegated", () => {
    expect(edgesFor(reduceAll([]))).toEqual([]);
  });
});

describe("workflowEdges", () => {
  it("joins the goal to the supervisor, the handoffs, and the supervisor to the outcome", () => {
    const edges = workflowEdges(view()).map((edge) => [edge.source, edge.target]);

    expect(edges).toEqual([
      [GOAL, "supervisor"],
      ["supervisor", "researcher"],
      ["supervisor", OUTCOME],
    ]);
  });

  it("animates an edge into an agent still working, and settles once the run ends", () => {
    const events = twoAgentRun();
    const midway = events.findIndex((event) => event.type === "agent.handoff") + 1;

    const live = workflowEdges(reduceAll(events.slice(0, midway)));
    expect(live.find((edge) => edge.target === "researcher")?.animated).toBe(true);
    expect(live.find((edge) => edge.target === OUTCOME)?.className).toContain("flow-edge--running");

    const done = workflowEdges(view());
    expect(done.every((edge) => edge.animated === false)).toBe(true);
    expect(done.find((edge) => edge.target === OUTCOME)?.className).toContain("flow-edge--completed");
  });

  it("has nothing to join before an agent exists", () => {
    expect(workflowEdges(reduceAll([]))).toEqual([]);
  });
});

describe("the camera", () => {
  it("is the same for the same nodes and pane, however they got there", () => {
    /* The property the whole acceptance criterion rests on. Live, the nodes
       arrive one at a time; replayed, all at once. The camera must not care. */
    const nodes = layout(view(), null);

    expect(viewportFor(nodes, 1376, 353)).toEqual(viewportFor(nodes, 1376, 353));
    expect(viewportFor(nodes, 1376, 353)).toEqual(viewportFor(layout(view(), null), 1376, 353));
  });

  it("does not depend on the order the nodes are given in", () => {
    const nodes = layout(view(), null);

    expect(viewportFor([...nodes].reverse(), 1376, 353)).toEqual(viewportFor(nodes, 1376, 353));
  });

  it("zooms out when the pane is too small for the graph", () => {
    const nodes = layout(view(), null);

    const roomy = viewportFor(nodes, 1376, 353);
    const cramped = viewportFor(nodes, 300, 200);

    expect(cramped.zoom).toBeLessThan(roomy.zoom);
  });

  it("never zooms in past the cap, however few agents there are", () => {
    const single = layout(reduceAll(twoAgentRun().slice(0, 3)), null);

    expect(viewportFor(single, 4000, 3000).zoom).toBeLessThanOrEqual(1.4);
  });

  it("centres the content in the pane", () => {
    const nodes = layout(view(), null);
    const paneWidth = 1000;

    const { x, zoom } = viewportFor(nodes, paneWidth, 400);

    const left = Math.min(...nodes.map((node) => node.position.x)) * zoom + x;
    const right = Math.max(...nodes.map((node) => node.position.x + (node.width ?? 0))) * zoom + x;

    expect(left).toBeCloseTo(paneWidth - right, 5);
  });

  it("falls back to an identity viewport when there is nothing to frame", () => {
    expect(viewportFor([], 800, 600)).toEqual({ x: 0, y: 0, zoom: 1 });
    expect(viewportFor(layout(view(), null), 0, 0)).toEqual({ x: 0, y: 0, zoom: 1 });
  });
});
