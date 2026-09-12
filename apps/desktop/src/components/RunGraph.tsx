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
 * The live agent graph: §5 Phase 7's "React Flow canvas: supervisor and
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
      {/* Without these, React Flow silently refuses to draw any edge touching
          this node: it logs a warning and renders nothing, so the graph looks
          finished while every handoff is missing. Found by running a real run
          and reading the browser console; no unit test noticed, because they
          all asserted node content. */}
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
 * Put the camera where {@link viewportFor} says.
 *
 * Deliberately not React Flow's `fitView`: that frames what it has *measured*,
 * so the result depends on when it ran. See `viewportFor` for the measurements
 * that made this necessary.
 *
 * Recomputed on pane resize as well as on the node set, and the resize half is
 * not defensive. The run summary above the canvas grows when the terminal event
 * adds its claim block, which shortens the pane, so a run watched live
 * computed its camera against a *taller* pane than the same run replayed, and
 * the two framed the graph differently for a reason that had nothing to do with
 * either the nodes or the log.
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
