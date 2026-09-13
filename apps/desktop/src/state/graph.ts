import type { Edge, Node } from "@xyflow/react";

import { ellipsise } from "../lib/format";

import type { AgentNode, RunView } from "./reducer";

/**
 * Turning a run into a graph: pure derivations of the `RunView` alone, so the
 * canvas is a projection of the log like everything else on screen.
 */

/** The supervisor's `agent_id`, fixed by the orchestrator so a replay can find it. */
export const SUPERVISOR = "supervisor";

/**
 * Node geometry, declared rather than measured: anything that depends on
 * measurement depends on when a node appeared rather than on the log, which
 * is how live and replay once framed the same run at different zooms.
 * `.agent-node` in the stylesheet is sized to match.
 */
export const NODE_WIDTH = 200;
export const NODE_HEIGHT = 96;
const COLUMN_GAP = 40;
const ROW_HEIGHT = 160;
/** Workers per row; one row of a dozen zoomed the camera out past legibility. */
export const WORKERS_PER_ROW = 4;

export interface AgentNodeData extends Record<string, unknown> {
  agent: AgentNode;
  selected: boolean;
  /** A name the run handed off to but never spawned; without a node its edge would vanish. */
  ghost: boolean;
}

/**
 * Place the supervisor on the top row and the workers on the rows below, in
 * the order they first appeared. A handoff target the run never spawned gets
 * a ghost node after the real workers, so its edge has somewhere to land.
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

/** One edge per ordered pair, labelled with how many handoffs it carries. */
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
 * The camera, computed from the nodes rather than fitted to them. React Flow's
 * `fitView` frames what it has measured, so its result depends on when it ran
 * and live and replay disagreed. Same nodes and same pane give the same
 * viewport here; the user can still pan and zoom afterwards.
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
