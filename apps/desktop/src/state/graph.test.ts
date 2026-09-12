import { describe, expect, it } from "vitest";

import { LogBuilder, twoAgentRun } from "../test/log";

import { edgesFor, layout, NODE_HEIGHT, NODE_WIDTH, viewportFor } from "./graph";
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
  it("puts the supervisor on the top row and workers below it", () => {
    const nodes = layout(view(), null);

    const supervisor = nodes.find((node) => node.id === "supervisor");
    const worker = nodes.find((node) => node.id === "researcher");

    expect(supervisor?.position.y).toBe(0);
    expect(worker?.position.y).toBeGreaterThan(0);
  });

  it("declares each node's size rather than leaving it to be measured", () => {
    /* A node without dimensions is only measured once its element has been laid
       out, and anything downstream of measurement then depends on when the node
       appeared rather than on the log. */
    for (const node of layout(view(), null)) {
      expect(node.width).toBe(NODE_WIDTH);
      expect(node.height).toBe(NODE_HEIGHT);
    }
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

  it("wraps workers onto a second row past four", () => {
    /* One row per run put a dozen workers 2880px wide and the camera zoomed
       out until nothing on a node could be read. */
    const log = new LogBuilder();
    const events = [log.add("agent.spawned", { role: "s" }, "supervisor")];
    for (let index = 0; index < 6; index += 1) {
      events.push(log.add("agent.spawned", { role: "w" }, `w${String(index)}`));
    }
    const nodes = layout(reduceAll(events), null);

    const rows = new Set(nodes.filter((n) => n.id !== "supervisor").map((n) => n.position.y));
    expect(rows.size).toBe(2);
    const perRow = [...rows].map((y) => nodes.filter((n) => n.position.y === y).length);
    expect(perRow).toEqual([4, 2]);
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

    const xs = nodes.map((node) => node.position.x);
    const left = Math.min(...xs) * zoom + x;
    const right = (Math.max(...xs) + NODE_WIDTH) * zoom + x;

    expect(left).toBeCloseTo(paneWidth - right, 5);
  });

  it("falls back to an identity viewport when there is nothing to frame", () => {
    expect(viewportFor([], 800, 600)).toEqual({ x: 0, y: 0, zoom: 1 });
    expect(viewportFor(layout(view(), null), 0, 0)).toEqual({ x: 0, y: 0, zoom: 1 });
  });
});
