import { Background, Controls, ReactFlow, type Edge, type Node } from "@xyflow/react";
import { useMemo } from "react";

import type { AgentNode, RunView } from "../state/reducer";

import "@xyflow/react/dist/style.css";

/**
 * The live agent graph — §5 Phase 7's "React Flow canvas: supervisor and
 * workers as nodes, handoffs as edges, live status colour".
 *
 * Every node and edge is derived from `view`, which is the fold of the event
 * log and nothing else. The component holds no state of its own and fetches
 * nothing, which is what lets replay and live share it: given the same
 * `RunView` it renders the same DOM, so a replayed run at cursor N is
 * indistinguishable from the live run when event N arrived.
 *
 * **Layout is computed, not solved.** Positions come from each agent's index in
 * `agentOrder`, so they are a deterministic function of the log. An
 * auto-layout pass that iterated to a solution would move nodes between two
 * renders of the same run, which is the acceptance criterion failing for a
 * reason that has nothing to do with the events.
 */

const SUPERVISOR = "supervisor";

/** Node geometry. Fixed so the layout is arithmetic rather than measurement. */
const NODE_WIDTH = 200;
const COLUMN_GAP = 40;
const ROW_HEIGHT = 160;

export interface RunGraphProps {
  view: RunView;
  selectedAgent: string | null;
  onSelectAgent: (name: string | null) => void;
}

interface AgentNodeData extends Record<string, unknown> {
  agent: AgentNode;
  selected: boolean;
}

/** How an agent's current activity reads to a person, and how it is coloured. */
function activityLabel(agent: AgentNode): string {
  switch (agent.activity) {
    case "spawned":
      return "ready";
    case "thinking":
      return `thinking · step ${String(agent.steps)}`;
    case "calling":
      return "calling the model";
    case "waiting":
      return "waiting for approval";
    case "completed":
      return agent.finishedReason === null ? "done" : `done · ${agent.finishedReason}`;
  }
}

function AgentCard({ data }: { data: AgentNodeData }) {
  const { agent, selected } = data;

  return (
    <div
      className={`agent-node agent-node--${agent.activity}${selected ? " agent-node--selected" : ""}`}
      data-testid={`agent-node-${agent.name}`}
    >
      <div className="agent-node__name">{agent.name}</div>
      <div className="agent-node__role">{agent.role ?? "—"}</div>
      <div className="agent-node__activity">{activityLabel(agent)}</div>
      <div className="agent-node__meta">
        {agent.model ?? "no model"}
        {agent.allowedTools.length > 0 && (
          <span className="agent-node__tools"> · {agent.allowedTools.length} tools</span>
        )}
      </div>
    </div>
  );
}

const nodeTypes = { agent: AgentCard };

/**
 * Place the supervisor on the top row and every worker on the row below.
 *
 * The supervisor is found by name because `SUPERVISOR_NAME` is fixed in the
 * orchestrator precisely so a replay can find the root of the graph without
 * inferring it.
 */
function layout(view: RunView, selected: string | null): Node<AgentNodeData>[] {
  const workers = view.agentOrder.filter((name) => name !== SUPERVISOR);
  const width = Math.max(workers.length, 1) * (NODE_WIDTH + COLUMN_GAP);

  return view.agentOrder.flatMap((name) => {
    const agent = view.agents[name];
    if (agent === undefined) return [];

    const isSupervisor = name === SUPERVISOR;
    const column = isSupervisor ? 0 : workers.indexOf(name);

    return [
      {
        id: name,
        type: "agent",
        position: isSupervisor
          ? { x: width / 2 - NODE_WIDTH / 2, y: 0 }
          : { x: column * (NODE_WIDTH + COLUMN_GAP), y: ROW_HEIGHT },
        data: { agent, selected: selected === name },
      },
    ];
  });
}

/**
 * One edge per ordered pair, labelled with how many handoffs it carries.
 *
 * A separate edge per handoff would draw several identical lines on top of each
 * other in the common case — a supervisor delegating twice to the same worker —
 * and lose the count that makes it interesting.
 */
function edges(view: RunView): Edge[] {
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
    animated: false,
    label: edge.count > 1 ? `${String(edge.count)} handoffs` : "handoff",
  }));
}

export function RunGraph({ view, selectedAgent, onSelectAgent }: RunGraphProps) {
  const nodes = useMemo(() => layout(view, selectedAgent), [view, selectedAgent]);
  const graphEdges = useMemo(() => edges(view), [view]);

  if (view.agentOrder.length === 0) {
    return (
      <div className="graph graph--empty" data-testid="run-graph">
        <p>No agents yet. The graph fills in as the supervisor spawns them.</p>
      </div>
    );
  }

  return (
    <div className="graph" data-testid="run-graph">
      <ReactFlow
        nodes={nodes}
        edges={graphEdges}
        nodeTypes={nodeTypes}
        fitView
        // The graph is a view of the log, not a diagram the user edits: dragging
        // a node would imply the layout means something the events do not say.
        nodesDraggable={false}
        nodesConnectable={false}
        edgesFocusable={false}
        proOptions={{ hideAttribution: false }}
        onNodeClick={(_event, node) => {
          onSelectAgent(node.id === selectedAgent ? null : node.id);
        }}
        onPaneClick={() => {
          onSelectAgent(null);
        }}
      >
        <Background />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}
