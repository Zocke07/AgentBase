import {
  Background,
  Controls,
  Handle,
  Position,
  ReactFlow,
  useReactFlow,
  type Node,
} from "@xyflow/react";
import { useEffect, useMemo, useRef, useState } from "react";

import { ellipsise } from "../lib/format";
import { activityLabel } from "../state/describe";
import { edgesFor, layout, viewportFor, type AgentNodeData } from "../state/graph";
import type { RunView } from "../state/reducer";

import "@xyflow/react/dist/style.css";

/**
 * The agent graph: nodes, edges and camera derived from `view` and nothing
 * else, so live and replay render the same DOM. Layout is computed, not
 * solved: an iterative auto-layout would move nodes between two renders of
 * the same run.
 */

export interface RunGraphProps {
  view: RunView;
  selectedAgent: string | null;
  onSelectAgent: (name: string | null) => void;
}

function AgentCard({ data }: { data: AgentNodeData }) {
  const { agent, selected, ghost } = data;
  const flags =
    (selected ? " agent-node--selected" : "") +
    (ghost ? " agent-node--ghost" : "") +
    (agent.lastError !== null ? " agent-node--errored" : "");

  return (
    <div
      className={`agent-node agent-node--${agent.activity}${flags}`}
      data-testid={`agent-node-${agent.name}`}
    >
      {/* Without handles React Flow silently draws no edge touching this node. */}
      <Handle type="target" position={Position.Top} />
      <Handle type="source" position={Position.Bottom} />
      <div className="agent-node__name">{agent.name}</div>
      {ghost ? (
        <div className="agent-node__role">handed off to, but never spawned</div>
      ) : (
        <>
          <div className="agent-node__role">{agent.role ?? "-"}</div>
          <div className="agent-node__activity">{activityLabel(agent)}</div>
          {agent.lastError !== null ? (
            <div className="agent-node__error" title={agent.lastError}>
              error · {ellipsise(agent.lastError, 40)}
            </div>
          ) : (
            <div className="agent-node__meta">
              {agent.model ?? "no model"}
              {agent.allowedTools.length > 0 && (
                <span className="agent-node__tools"> · {agent.allowedTools.length} tools</span>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}

const nodeTypes = { agent: AgentCard };

/**
 * Put the camera where {@link viewportFor} says, recomputed on pane resize as
 * well as on the node set: the summary above the canvas grows when the run
 * ends, and without the resize half live and replay framed the graph differently.
 */
function Camera({ nodes, userMoved }: { nodes: Node<AgentNodeData>[]; userMoved: boolean }) {
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
  const graphEdges = useMemo(() => edgesFor(view), [view]);
  // Set the first time the *user* moves the camera. React Flow reports a
  // programmatic `setViewport` with a null event, so the fit itself does not
  // count. State rather than a ref so `Camera` re-renders when it flips.
  const [userMoved, setUserMoved] = useState(false);
  const moved = useRef(false);

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
        onMoveStart={(event) => {
          if (event !== null && !moved.current) {
            moved.current = true;
            setUserMoved(true);
          }
        }}
      >
        <Camera nodes={nodes} userMoved={userMoved} />
        <Background />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}
