import type { Edge, Node } from "@xyflow/react";

import { ellipsise } from "../lib/format";

import type { AgentNode, RunView } from "./reducer";

/**
 * Turning a run into a graph.
 *
 * Pure derivations, kept out of the component for the same reason the reducer
 * is: they are the interesting part, they are worth testing directly, and a
 * component module that also exports functions defeats React Fast Refresh.
 *
 * Both are functions of the `RunView` alone, which is what lets the canvas be a
 * projection of the log like everything else on screen.
 */

/** The supervisor's `agent_id`, fixed by the orchestrator so a replay can find it. */
export const SUPERVISOR = "supervisor";

/**
 * Node geometry, declared rather than measured.
 *
 * These are handed to React Flow on every node, which matters more than it
 * looks: a node without explicit dimensions is only measured once its DOM
 * element has been laid out, and anything that depends on measurement — the
 * camera, above all — then depends on *when* the node appeared rather than on
 * the log. A run watched from the start framed itself at `scale(1.387)` while
 * the same run replayed framed itself at `scale(1.213)`, which is BUILD_SPEC
 * §5 Phase 7's "pixel-identical" criterion failing on the one part of the
 * canvas that was not a projection of the log.
 *
 * `.agent-node` in the stylesheet is sized to match.
 */
export const NODE_WIDTH = 200;
export const NODE_HEIGHT = 96;
const COLUMN_GAP = 40;
const ROW_HEIGHT = 160;
/**
 * Workers per row. One row put a dozen workers 2880px wide and the camera
 * zoomed out until nothing on a node could be read.
 */
export const WORKERS_PER_ROW = 4;

export interface AgentNodeData extends Record<string, unknown> {
  agent: AgentNode;
  selected: boolean;
  /**
   * A name the run handed off to but never spawned. Watched in Phase 6: a
   * denied worker handed off to a nonexistent `another_agent`, and React
   * Flow dropped the edge — a console warning and nothing drawn — so the
   * handoff that most needed seeing was the one that vanished.
   */
  ghost: boolean;
}

/**
 * Place the supervisor on the top row and the workers on the rows below,
 * `WORKERS_PER_ROW` to a row, in the order they first appeared.
 *
 * The supervisor is found by name because `SUPERVISOR_NAME` is fixed in the
 * orchestrator precisely so a replay can find the root of the graph without
 * inferring it. A handoff target the run never spawned gets a ghost node
 * after the real workers, so its edge has somewhere to land.
 */
export function layout(view: RunView, selected: string | null): Node<AgentNodeData>[] {
  const workers = view.agentOrder.filter((name) => name !== SUPERVISOR);
  const ghosts = [...new Set(view.handoffs.map((h) => h.to))].filter(
    (name) => view.agents[name] === undefined,
  );
  const placed = [...workers, ...ghosts];
  const columns = Math.min(Math.max(placed.length, 1), WORKERS_PER_ROW);
  const width = columns * (NODE_WIDTH + COLUMN_GAP);

  const nodes: Node<AgentNodeData>[] = [];
  const supervisor = view.agents[SUPERVISOR];
  if (supervisor !== undefined) {
    nodes.push({
      id: SUPERVISOR,
      type: "agent",
      position: { x: width / 2 - NODE_WIDTH / 2, y: 0 },
      width: NODE_WIDTH,
      height: NODE_HEIGHT,
      data: { agent: supervisor, selected: selected === SUPERVISOR, ghost: false },
    });
  }

  placed.forEach((name, index) => {
    const agent = view.agents[name];
    const row = Math.floor(index / WORKERS_PER_ROW) + 1;
    const column = index % WORKERS_PER_ROW;
    nodes.push({
      id: name,
      type: "agent",
      position: { x: column * (NODE_WIDTH + COLUMN_GAP), y: row * ROW_HEIGHT },
      width: NODE_WIDTH,
      height: NODE_HEIGHT,
      data: {
        agent: agent ?? ghostAgent(name),
        selected: selected === name,
        ghost: agent === undefined,
      },
    });
  });

  return nodes;
}

/** A stand-in node for a name that was handed off to and never existed. */
function ghostAgent(name: string): AgentNode {
  return {
    name,
    role: null,
    definitionId: null,
    definitionName: null,
    systemPrompt: null,
    provider: null,
    model: null,
    allowedTools: [],
    autoApprove: [],
    maxSteps: null,
    activity: "spawned",
    currentTool: null,
    lastError: null,
    steps: 0,
    finishedReason: null,
    streamedText: "",
    lastMessage: null,
    seq: 0,
  };
}

/**
 * One edge per ordered pair, labelled with how many handoffs it carries.
 *
 * A separate edge per handoff would draw several identical lines on top of each
 * other in the common case — a supervisor delegating twice to the same worker —
 * and lose the count that makes it interesting.
 */
export function edgesFor(view: RunView): Edge[] {
  const counts = new Map<string, { from: string; to: string; count: number; task: string }>();

  for (const handoff of view.handoffs) {
    const key = `${handoff.from}->${handoff.to}`;
    const existing = counts.get(key);
    if (existing === undefined) {
      counts.set(key, { from: handoff.from, to: handoff.to, count: 1, task: handoff.task });
    } else {
      existing.count += 1;
    }
  }

  return [...counts.entries()].map(([key, edge]) => ({
    id: key,
    source: edge.from,
    target: edge.to,
    // A single handoff shows what was asked; several would be a paragraph.
    label:
      edge.count > 1
        ? `${String(edge.count)} handoffs`
        : edge.task === ""
          ? "handoff"
          : `handoff · ${ellipsise(edge.task, 36)}`,
  }));
}


/** A React Flow viewport: pan offset plus zoom. */
export interface Viewport {
  x: number;
  y: number;
  zoom: number;
}

/** Never zoom in past this, however few agents there are. */
const MAX_ZOOM = 1.4;
/** Fraction of the pane left as breathing room around the content. */
const PADDING = 0.12;

/**
 * The camera, computed from the nodes rather than fitted to them.
 *
 * React Flow's own `fitView` frames whatever it has *measured*, which makes the
 * result depend on when it ran: a run watched from the start framed itself at
 * `scale(1.43)` while the same run replayed framed itself at `scale(1.25)`,
 * with the graph otherwise identical. That is BUILD_SPEC §5 Phase 7's
 * "pixel-identical" criterion failing on the one part of the canvas that was
 * not a projection of the log — and it stayed broken through two attempts to
 * fix it by waiting for measurement, because the timing is React Flow's to
 * decide and not ours.
 *
 * So the camera is arithmetic, like the layout above. Same nodes and same pane
 * give the same viewport, whatever order the nodes arrived in. The user can
 * still pan and zoom afterwards; this only decides where the graph starts.
 */
export function viewportFor(
  nodes: readonly Node<AgentNodeData>[],
  paneWidth: number,
  paneHeight: number,
): Viewport {
  if (nodes.length === 0 || paneWidth <= 0 || paneHeight <= 0) {
    return { x: 0, y: 0, zoom: 1 };
  }

  const xs = nodes.map((node) => node.position.x);
  const ys = nodes.map((node) => node.position.y);
  const minX = Math.min(...xs);
  const minY = Math.min(...ys);
  const contentWidth = Math.max(...xs) + NODE_WIDTH - minX;
  const contentHeight = Math.max(...ys) + NODE_HEIGHT - minY;

  const usableWidth = paneWidth * (1 - PADDING * 2);
  const usableHeight = paneHeight * (1 - PADDING * 2);
  const zoom = Math.min(usableWidth / contentWidth, usableHeight / contentHeight, MAX_ZOOM);

  return {
    x: (paneWidth - contentWidth * zoom) / 2 - minX * zoom,
    y: (paneHeight - contentHeight * zoom) / 2 - minY * zoom,
    zoom,
  };
}
