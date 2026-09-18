import { MarkerType, type Edge, type Node } from "@xyflow/react";

import { ellipsise } from "../lib/format";

import type { AgentNode, RunClaim, RunStatus, RunView } from "./reducer";

/**
 * Turning a run into a workflow: pure derivations of the `RunView` alone, so
 * the canvas is a projection of the log like everything else on screen.
 *
 * The picture reads left to right, the way a person tells the story of a run:
 * the goal, the supervisor that planned it, the workers it delegated to, and
 * the outcome. What an agent did with its tools is folded onto its own card
 * as counts, not drawn as a node per call: the log below has the calls, the
 * canvas has the shape.
 */

/** The supervisor's `agent_id`, fixed by the orchestrator so a replay can find it. */
export const SUPERVISOR = "supervisor";
export const GOAL = "goal";
export const OUTCOME = "outcome";

/**
 * Node geometry, declared rather than measured: anything that depends on
 * measurement depends on when a node appeared rather than on the log, which
 * is how live and replay once framed the same run at different zooms.
 * `.flow-node` in the stylesheet is sized to match.
 */
export const NODE_WIDTH = 224;
export const NODE_HEIGHT = 136;
export const END_WIDTH = 204;
export const END_HEIGHT = 82;
/** Wide enough that a handoff label at LABEL_CHARS sits clear of both cards. */
const COLUMN_GAP = 150;
/** The most of a handoff task an edge label shows; the inspector has the rest. */
const LABEL_CHARS = 22;
const ROW_GAP = 22;
/** Workers per column; a dozen in one column zoomed the camera out past legibility. */
export const WORKERS_PER_COLUMN = 4;

/** How one agent used one tool, summed over the run so far. */
export interface ToolUse {
  readonly tool: string;
  /** Executions (`tool.called`), whether or not a result is in yet. */
  readonly calls: number;
  readonly denied: number;
  /** Whether the agent is inside a call to this tool at this cursor. */
  readonly running: boolean;
}

export interface AgentNodeData extends Record<string, unknown> {
  agent: AgentNode;
  selected: boolean;
  /** A name the run handed off to but never spawned; without a node its edge would vanish. */
  ghost: boolean;
  tools: readonly ToolUse[];
  /** Handoffs this agent made, so the card can say it delegated. */
  delegated: number;
}

export interface GoalNodeData extends Record<string, unknown> {
  goal: string | null;
  status: RunStatus;
  /** The channel a chat-originated run came from; null for the window. */
  channel: string | null;
  /** Vault excerpts sent along with the goal. */
  excerpts: number;
}

export interface OutcomeNodeData extends Record<string, unknown> {
  status: RunStatus;
  claim: RunClaim | null;
  agents: number;
  toolCalls: number;
  errors: number;
  memoryPath: string | null;
}

export type WorkflowNode = Node<AgentNodeData> | Node<GoalNodeData> | Node<OutcomeNodeData>;

/**
 * Place the goal first, the supervisor after it, the workers stacked in the
 * columns that follow (wrapping past four) and the outcome last. Everything
 * single is centred on the band the workers occupy. A handoff target the run
 * never spawned gets a ghost node after the real workers, so its edge has
 * somewhere to land.
 */
export function layout(view: RunView, selected: string | null): WorkflowNode[] {
  const supervisor = view.agents[SUPERVISOR];
  const workers = view.agentOrder.filter((name) => name !== SUPERVISOR);
  const ghosts = [...new Set(view.handoffs.map((handoff) => handoff.to))].filter(
    (name) => view.agents[name] === undefined,
  );
  const placed = [...workers, ...ghosts];
  const workerColumns = Math.ceil(placed.length / WORKERS_PER_COLUMN);
  const rows = Math.min(Math.max(placed.length, 1), WORKERS_PER_COLUMN);
  const band = Math.max(rows * (NODE_HEIGHT + ROW_GAP) - ROW_GAP, NODE_HEIGHT);
  const columnX = (column: number) => column * (NODE_WIDTH + COLUMN_GAP);
  const centred = (height: number) => (band - height) / 2;

  const nodes: WorkflowNode[] = [];
  nodes.push({
    id: GOAL,
    type: "goal",
    position: { x: columnX(0), y: centred(END_HEIGHT) },
    width: END_WIDTH,
    height: END_HEIGHT,
    data: {
      goal: view.goal,
      status: view.status,
      channel: view.origin?.channel ?? null,
      excerpts: view.knowledge.length,
    },
  });

  let column = 1;
  if (supervisor !== undefined) {
    nodes.push(agentNode(view, supervisor, false, selected, { x: columnX(column), y: centred(NODE_HEIGHT) }));
    column += 1;
  }

  placed.forEach((name, index) => {
    const agent = view.agents[name];
    const row = index % WORKERS_PER_COLUMN;
    const workerColumn = Math.floor(index / WORKERS_PER_COLUMN);
    nodes.push(
      agentNode(view, agent ?? ghostAgent(name), agent === undefined, selected, {
        x: columnX(column + workerColumn),
        y: row * (NODE_HEIGHT + ROW_GAP),
      }),
    );
  });
  column += workerColumns;

  nodes.push({
    id: OUTCOME,
    type: "outcome",
    position: { x: columnX(column), y: centred(END_HEIGHT) },
    width: END_WIDTH,
    height: END_HEIGHT,
    data: {
      status: view.status,
      claim: view.claim,
      agents: view.agentOrder.length,
      toolCalls: view.toolCalls.length,
      errors: view.errors.length,
      memoryPath: view.memoryPath,
    },
  });

  return nodes;
}

function agentNode(
  view: RunView,
  agent: AgentNode,
  ghost: boolean,
  selected: string | null,
  position: { x: number; y: number },
): Node<AgentNodeData> {
  return {
    id: agent.name,
    type: "agent",
    position,
    width: NODE_WIDTH,
    height: NODE_HEIGHT,
    data: {
      agent,
      selected: selected === agent.name,
      ghost,
      tools: toolUsesFor(view, agent.name),
      delegated: view.handoffs.filter((handoff) => handoff.from === agent.name).length,
    },
  };
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

/** Each tool an agent has executed or been refused, in the order it first came up. */
export function toolUsesFor(view: RunView, agent: string): ToolUse[] {
  const uses = new Map<string, { calls: number; denied: number }>();
  const touch = (tool: string) => {
    const existing = uses.get(tool);
    if (existing !== undefined) return existing;
    const created = { calls: 0, denied: 0 };
    uses.set(tool, created);
    return created;
  };
  const touched = [
    ...view.toolCalls.filter((call) => call.agent === agent).map((call) => ({ seq: call.seq, tool: call.tool, denied: false })),
    ...view.denials.filter((denial) => denial.agent === agent).map((denial) => ({ seq: denial.seq, tool: denial.tool, denied: true })),
  ].sort((left, right) => left.seq - right.seq);
  for (const entry of touched) {
    const use = touch(entry.tool);
    if (entry.denied) use.denied += 1;
    else use.calls += 1;
  }
  const current = view.agents[agent];
  const running = current?.activity === "executing" ? current.currentTool : null;
  return [...uses.entries()].map(([tool, counts]) => ({ tool, ...counts, running: running === tool }));
}

interface HandoffPair {
  readonly from: string;
  readonly to: string;
  readonly count: number;
  /** The first handoff's task; a later one does not replace it. */
  readonly task: string;
}

/** The handoffs grouped by ordered pair, in the order each pair first appeared. */
function handoffPairs(view: RunView): HandoffPair[] {
  const pairs = new Map<string, { from: string; to: string; count: number; task: string }>();
  for (const handoff of view.handoffs) {
    const key = `${handoff.from}->${handoff.to}`;
    const existing = pairs.get(key);
    if (existing === undefined) {
      pairs.set(key, { from: handoff.from, to: handoff.to, count: 1, task: handoff.task });
    } else {
      existing.count += 1;
    }
  }
  return [...pairs.values()];
}

/** One edge per ordered pair, labelled with how many handoffs it carries. */
export function edgesFor(view: RunView): Edge[] {
  return handoffPairs(view).map((edge) => ({
    id: `${edge.from}->${edge.to}`,
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

const TERMINAL: readonly RunStatus[] = ["completed", "failed", "cancelled"];

/**
 * The whole picture's edges: the goal into the supervisor, every handoff, and
 * the supervisor into the outcome. An edge into an agent still working is
 * animated, which is a fact about this cursor and so the same on replay.
 */
export function workflowEdges(view: RunView): Edge[] {
  const busy = (name: string) => {
    const agent = view.agents[name];
    return view.status === "running" && agent !== undefined && agent.activity !== "completed";
  };
  const arrow = { type: MarkerType.ArrowClosed, width: 18, height: 18 };
  const edges: Edge[] = [];
  const supervisor = view.agents[SUPERVISOR];
  const first = supervisor === undefined ? view.agentOrder[0] : SUPERVISOR;

  if (first !== undefined) {
    edges.push({
      id: `${GOAL}->${first}`,
      source: GOAL,
      target: first,
      sourceHandle: "out",
      targetHandle: "in",
      type: "smoothstep",
      className: "flow-edge flow-edge--goal",
      animated: busy(first),
      markerEnd: arrow,
    });
  }

  for (const pair of handoffPairs(view)) {
    // Work flows rightward through the side ports. A handoff back to the
    // supervisor, or across to another worker, leaves and arrives by the
    // bottom ports so it is drawn beneath the cards rather than over the
    // edge going the other way.
    const forward = pair.from === SUPERVISOR;
    const label = pair.count > 1 ? `${String(pair.count)} handoffs` : ellipsise(pair.task, LABEL_CHARS);
    edges.push({
      id: `${pair.from}->${pair.to}`,
      source: pair.from,
      target: pair.to,
      sourceHandle: forward ? "out" : "back-out",
      targetHandle: forward ? "in" : "back-in",
      type: "smoothstep",
      className: `flow-edge flow-edge--handoff${forward ? "" : " flow-edge--return"}${view.agents[pair.to] === undefined ? " flow-edge--ghost" : ""}`,
      animated: busy(pair.to),
      markerEnd: arrow,
      ...(label === "" ? {} : { label }),
    });
  }

  const last = supervisor === undefined ? view.agentOrder[view.agentOrder.length - 1] : SUPERVISOR;
  if (last !== undefined) {
    const settled = TERMINAL.includes(view.status);
    const outcome: Edge = {
      id: `${last}->${OUTCOME}`,
      source: last,
      target: OUTCOME,
      sourceHandle: "out",
      targetHandle: "in",
      type: "smoothstep",
      className: `flow-edge flow-edge--outcome flow-edge--${view.status}`,
      animated: !settled && view.status === "running",
    };
    edges.push(settled ? { ...outcome, markerEnd: arrow } : outcome);
  }

  return edges;
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
const PADDING = 0.06;

/**
 * The camera, computed from the nodes rather than fitted to them. React Flow's
 * `fitView` frames what it has measured, so its result depends on when it ran
 * and live and replay disagreed. Same nodes and same pane give the same
 * viewport here; the user can still pan and zoom afterwards.
 */
export function viewportFor(
  nodes: readonly WorkflowNode[],
  paneWidth: number,
  paneHeight: number,
): Viewport {
  if (nodes.length === 0 || paneWidth <= 0 || paneHeight <= 0) {
    return { x: 0, y: 0, zoom: 1 };
  }

  const minX = Math.min(...nodes.map((node) => node.position.x));
  const minY = Math.min(...nodes.map((node) => node.position.y));
  const maxX = Math.max(...nodes.map((node) => node.position.x + (node.width ?? NODE_WIDTH)));
  const maxY = Math.max(...nodes.map((node) => node.position.y + (node.height ?? NODE_HEIGHT)));
  const contentWidth = maxX - minX;
  const contentHeight = maxY - minY;

  const usableWidth = paneWidth * (1 - PADDING * 2);
  const usableHeight = paneHeight * (1 - PADDING * 2);
  const zoom = Math.min(usableWidth / contentWidth, usableHeight / contentHeight, MAX_ZOOM);

  return {
    x: (paneWidth - contentWidth * zoom) / 2 - minX * zoom,
    y: (paneHeight - contentHeight * zoom) / 2 - minY * zoom,
    zoom,
  };
}
