import {
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  Position,
  ReactFlow,
  useReactFlow,
} from "@xyflow/react";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { ellipsise } from "../lib/format";
import { activityLabel, STATUS_LABEL } from "../state/describe";
import {
  layout,
  SUPERVISOR,
  viewportFor,
  workflowEdges,
  type AgentNodeData,
  type GoalNodeData,
  type OutcomeNodeData,
  type WorkflowNode,
} from "../state/graph";
import type { Activity, RunView } from "../state/reducer";

import "@xyflow/react/dist/style.css";

/**
 * The workflow canvas: goal, supervisor, workers and outcome as cards, joined
 * by the handoffs. Nodes, edges and camera derive from `view` and nothing
 * else, so live and replay render the same DOM. Layout is computed, not
 * solved: an iterative auto-layout would move nodes between two renders of
 * the same run. A card says what its agent is doing and what it has done
 * with its tools; clicking one opens the detail beside the canvas.
 */

export interface RunGraphProps {
  view: RunView;
  selectedAgent: string | null;
  onSelectAgent: (name: string | null) => void;
}

const STATE_WORD: Record<Activity, string> = {
  spawned: "ready",
  thinking: "thinking",
  calling: "model",
  executing: "tool",
  waiting: "approval",
  completed: "done",
};

function Ports() {
  return (
    <>
      {/* Without handles React Flow silently draws no edge touching this node.
          The side ports carry the flow rightward; the bottom ones carry a
          handoff back or across, drawn beneath the cards. */}
      <Handle type="target" position={Position.Left} id="in" />
      <Handle type="source" position={Position.Right} id="out" />
      <Handle type="source" position={Position.Bottom} id="back-out" className="flow-node__back-port" />
      <Handle type="target" position={Position.Bottom} id="back-in" className="flow-node__back-port" />
    </>
  );
}

function AgentCard({ data }: { data: AgentNodeData }) {
  const { agent, selected, ghost, tools, delegated } = data;
  const supervisor = agent.name === SUPERVISOR;
  const flags =
    (selected ? " agent-node--selected" : "") +
    (ghost ? " agent-node--ghost" : "") +
    (agent.lastError !== null ? " agent-node--errored" : "");

  return (
    <div
      className={`flow-node agent-node agent-node--${agent.activity}${flags}`}
      data-testid={`agent-node-${agent.name}`}
    >
      <Ports />
      <div className="flow-node__head">
        <span className={`flow-node__icon flow-node__icon--${supervisor ? "supervisor" : "worker"}`} aria-hidden="true">
          {supervisor ? <SupervisorGlyph /> : <WorkerGlyph />}
        </span>
        <span className="flow-node__title">{agent.name}</span>
        {!ghost && (
          <span className={`flow-node__state flow-node__state--${agent.activity}`}>{STATE_WORD[agent.activity]}</span>
        )}
      </div>
      {ghost ? (
        <div className="agent-node__role">handed off to, but never spawned</div>
      ) : (
        <>
          <div className="agent-node__role">{agent.role ?? "-"}</div>
          {agent.lastError !== null ? (
            <div className="agent-node__error" title={agent.lastError}>
              error · {ellipsise(agent.lastError, 44)}
            </div>
          ) : (
            <div className="agent-node__activity">{activityLabel(agent)}</div>
          )}
          <div className="agent-node__foot">
            <span className="agent-node__meta" title={agent.model ?? "no model"}>
              {agent.model ?? "no model"}
              {delegated > 0 && ` · delegated ${String(delegated)}`}
            </span>
            {tools.length > 0 && (
              <span className="agent-node__tools" aria-label="Tools used">
                {tools.map((use) => (
                  <span
                    key={use.tool}
                    className={`agent-node__tool${use.denied > 0 ? " agent-node__tool--denied" : ""}${use.running ? " agent-node__tool--running" : ""}`}
                    title={`${use.tool}: ${String(use.calls)} executed, ${String(use.denied)} denied`}
                  >
                    {use.tool}
                    {use.calls > 0 && <b>{use.calls}</b>}
                    {use.denied > 0 && <i>{use.denied}</i>}
                  </span>
                ))}
              </span>
            )}
          </div>
        </>
      )}
    </div>
  );
}

function GoalCard({ data }: { data: GoalNodeData }) {
  return (
    <div className={`flow-node end-node end-node--goal end-node--${data.status}`} data-testid="goal-node">
      <Ports />
      <div className="flow-node__head">
        <span className="flow-node__icon flow-node__icon--goal" aria-hidden="true">
          <GoalGlyph />
        </span>
        <span className="flow-node__title">Goal</span>
      </div>
      <div className="end-node__text">{data.goal ?? "Waiting for the run to start"}</div>
      <div className="end-node__foot">
        {data.channel !== null ? `from ${data.channel}` : "from this window"}
        {data.excerpts > 0 && ` · ${String(data.excerpts)} vault excerpt${data.excerpts === 1 ? "" : "s"}`}
      </div>
    </div>
  );
}

function GoalGlyph() {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <path d="M5 3v14h1.5v-5.5H15l-2-3 2-3H6.5V3z" />
    </svg>
  );
}

function OutcomeCard({ data }: { data: OutcomeNodeData }) {
  const settled = data.status === "completed" || data.status === "failed" || data.status === "cancelled";
  const text =
    data.claim !== null
      ? ellipsise(data.claim.text.replace(/\s+/g, " "), 96)
      : settled
        ? "The run ended without a summary."
        : data.status === "pending"
          ? "Nothing has happened yet."
          : "Still in progress.";
  return (
    <div className={`flow-node end-node end-node--outcome end-node--${data.status}`} data-testid="outcome-node">
      <Ports />
      <div className="flow-node__head">
        <span className={`flow-node__icon flow-node__icon--${data.status}`} aria-hidden="true">
          {data.status === "completed" ? <DoneGlyph /> : data.status === "failed" ? <FailedGlyph /> : <ClockGlyph />}
        </span>
        <span className="flow-node__title">Outcome</span>
        <span className={`flow-node__state flow-node__state--${data.status}`}>{STATUS_LABEL[data.status]}</span>
      </div>
      <div className="end-node__text">{text}</div>
      <div className="end-node__foot">
        {data.agents} agent{data.agents === 1 ? "" : "s"} · {data.toolCalls} tool call
        {data.toolCalls === 1 ? "" : "s"}
        {data.errors > 0 && ` · ${String(data.errors)} error${data.errors === 1 ? "" : "s"}`}
        {data.memoryPath !== null && " · saved as memory"}
      </div>
    </div>
  );
}

function DoneGlyph() {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <path d="M4 10.5 8.2 14.5 16 6.5 14.6 5 8.2 11.6 5.4 9z" />
    </svg>
  );
}

function FailedGlyph() {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <path d="M5.5 4 10 8.5 14.5 4 16 5.5 11.5 10l4.5 4.5-1.5 1.5-4.5-4.5L5.5 16 4 14.5 8.5 10 4 5.5z" />
    </svg>
  );
}

function ClockGlyph() {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <path d="M10 2.5a7.5 7.5 0 1 0 0 15 7.5 7.5 0 0 0 0-15zm0 1.6a5.9 5.9 0 1 1 0 11.8 5.9 5.9 0 0 1 0-11.8zM9.2 6h1.6v4.2l3 1.8-.8 1.3-3.8-2.3z" />
    </svg>
  );
}

function SupervisorGlyph() {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <path d="M10 3a2.2 2.2 0 1 1 0 4.4A2.2 2.2 0 0 1 10 3zM4 12.6a2.2 2.2 0 1 1 0 4.4 2.2 2.2 0 0 1 0-4.4zm12 0a2.2 2.2 0 1 1 0 4.4 2.2 2.2 0 0 1 0-4.4zM9.3 7.8h1.4v2.4l4.2 2.4-.7 1.2L10 11.4l-4.2 2.4-.7-1.2 4.2-2.4z" />
    </svg>
  );
}

function WorkerGlyph() {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <path d="M10 3a3.2 3.2 0 1 1 0 6.4A3.2 3.2 0 0 1 10 3zm0 7.6c3.6 0 6.5 2 6.5 4.6V17h-13v-1.8c0-2.6 2.9-4.6 6.5-4.6z" />
    </svg>
  );
}

const nodeTypes = { agent: AgentCard, goal: GoalCard, outcome: OutcomeCard };

/**
 * Put the camera where {@link viewportFor} says, recomputed on pane resize as
 * well as on the node set: the summary above the canvas grows when the run
 * ends, and without the resize half live and replay framed the graph differently.
 */
function Camera({ nodes, userMoved }: { nodes: WorkflowNode[]; userMoved: boolean }) {
  const flow = useReactFlow();
  const [pane, setPane] = useState<{ width: number; height: number } | null>(null);
  const signature = nodes.map((node) => node.id).join(",");

  useEffect(() => {
    const element = document.querySelector(".react-flow__viewport")?.parentElement;
    if (element === null || element === undefined) return undefined;

    const observer = new ResizeObserver(([entry]) => {
      if (entry === undefined) return;
      setPane({ width: entry.contentRect.width, height: entry.contentRect.height });
    });
    observer.observe(element);

    return () => {
      observer.disconnect();
    };
  }, []);

  useEffect(() => {
    if (pane === null) return;
    // Once the user has panned or zoomed, the camera is theirs: a new agent
    // spawning or the pane resizing must not yank it back to the fit.
    if (userMoved) return;
    void flow.setViewport(viewportFor(nodes, pane.width, pane.height));
    // `nodes` changes identity every render; the ids are what decide the camera.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [flow, signature, pane, userMoved]);

  return null;
}

export function RunGraph({ view, selectedAgent, onSelectAgent }: RunGraphProps) {
  const nodes = useMemo(() => layout(view, selectedAgent), [view, selectedAgent]);
  const graphEdges = useMemo(() => workflowEdges(view), [view]);
  // Set the first time the *user* moves the camera. React Flow reports a
  // programmatic `setViewport` with a null event, so the fit itself does not
  // count. State rather than a ref so `Camera` re-renders when it flips.
  const [userMoved, setUserMoved] = useState(false);
  const moved = useRef(false);

  if (view.goal === null && view.agentOrder.length === 0) {
    return (
      <div className="graph graph--empty" data-testid="run-graph">
        <p>No agents yet. The workflow fills in as the supervisor spawns them.</p>
      </div>
    );
  }

  let legend: ReactNode = null;
  if (view.agentOrder.length > 0) {
    legend = (
      <div className="graph__legend" aria-hidden="true">
        <span className="graph__legend-item graph__legend-item--thinking">working</span>
        <span className="graph__legend-item graph__legend-item--waiting">needs you</span>
        <span className="graph__legend-item graph__legend-item--completed">done</span>
        <span className="graph__legend-item graph__legend-item--errored">error</span>
      </div>
    );
  }

  return (
    <div className="graph" data-testid="run-graph">
      <ReactFlow
        nodes={nodes}
        edges={graphEdges}
        nodeTypes={nodeTypes}
        // The canvas is a view of the log, not a diagram the user edits: dragging
        // a node would imply the layout means something the events do not say.
        nodesDraggable={false}
        nodesConnectable={false}
        edgesFocusable={false}
        proOptions={{ hideAttribution: false }}
        onNodeClick={(_event, node) => {
          if (node.type !== "agent") {
            onSelectAgent(null);
            return;
          }
          onSelectAgent(node.id === selectedAgent ? null : node.id);
        }}
        onPaneClick={() => {
          onSelectAgent(null);
        }}
        onMoveStart={(event) => {
          if (event !== null && !moved.current) {
            moved.current = true;
            setUserMoved(true);
          }
        }}
      >
        <Camera nodes={nodes} userMoved={userMoved} />
        <Background variant={BackgroundVariant.Dots} gap={22} size={1.2} />
        <Controls showInteractive={false} />
      </ReactFlow>
      {legend}
    </div>
  );
}
