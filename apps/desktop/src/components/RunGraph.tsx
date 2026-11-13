import {
  Background,
  BackgroundVariant,
  BaseEdge,
  ControlButton,
  Controls,
  EdgeLabelRenderer,
  getSmoothStepPath,
  Handle,
  Position,
  ReactFlow,
  useReactFlow,
  type EdgeProps,
} from "@xyflow/react";
import { useEffect, useMemo, useState, type ReactNode } from "react";

import { ellipsise } from "../lib/format";
import { toolInfo } from "../lib/tools";
import { activityLabel, STATUS_LABEL } from "../state/describe";
import {
  layout,
  SUPERVISOR,
  viewportFor,
  workflowEdges,
  type AgentNodeData,
  type GoalNodeData,
  type HandoffEdge as HandoffEdgeType,
  type OutcomeNodeData,
  type WorkflowNode,
} from "../state/graph";
import type { Activity, RunView } from "../state/reducer";

import { Icon } from "./icons/Icon";

import "@xyflow/react/dist/style.css";

/**
 * Workflow canvas of goal, supervisor, workers, outcome, and handoffs. Nodes,
 * edges, and camera derive only from `view`, ensuring live/replay DOM parity.
 * Computed layout avoids iterative drift; cards show activity/tool counts and
 * open adjacent detail on click.
 */

export interface RunGraphProps {
  view: RunView;
  selectedAgent: string | null;
  onSelectAgent: (name: string | null) => void;
  /** Whether canvas fills window; undefined when expansion is unavailable. */
  expanded?: boolean | undefined;
  onToggleExpand?: (() => void) | undefined;
}

const STATE_WORD: Record<Activity, string> = {
  spawned: "ready",
  thinking: "thinking",
  calling: "model",
  executing: "tool",
  waiting: "approval",
  completed: "done",
};

/** How many tool chips a card shows before folding the rest into "+n". */
const CHIP_LIMIT = 3;

/** Maximum card tooltip summary; panel retains full text. */
const TOOLTIP_CHARS = 600;

/**
 * Shorten built-in tool chips to distinguishing verbs; tooltips and inspector
 * retain full names. Keep unknown names unchanged.
 */
function chipLabel(tool: string): string {
  return toolInfo(tool).chip;
}

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
          {supervisor ? <Icon name="network" size={16} /> : <Icon name="user-round" size={16} />}
        </span>
        <span className="flow-node__title" title={agent.name}>
          {agent.name}
        </span>
        {!ghost && (
          <span className={`flow-node__state flow-node__state--${agent.activity}`}>{STATE_WORD[agent.activity]}</span>
        )}
      </div>
      {ghost ? (
        <div className="agent-node__role">handed off to, but never spawned</div>
      ) : (
        <>
          <div className="agent-node__role" title={agent.role ?? undefined}>
            {agent.role ?? "-"}
          </div>
          {agent.lastError !== null ? (
            <div className="agent-node__error" title={agent.lastError}>
              error · {ellipsise(agent.lastError, 44)}
            </div>
          ) : (
            <div className="agent-node__activity" title={activityLabel(agent)}>
              {activityLabel(agent)}
            </div>
          )}
          <div className="agent-node__foot">
            <span className="agent-node__meta" title={agent.model ?? "no model"}>
              {agent.model ?? "no model"}
              {delegated > 0 && ` · delegated ${String(delegated)}`}
            </span>
            {tools.length > 0 && (
              <span className="agent-node__tools" aria-label="Tools used">
                {tools.slice(0, CHIP_LIMIT).map((use) => (
                  <span
                    key={use.tool}
                    className={`agent-node__tool${use.denied > 0 ? " agent-node__tool--denied" : ""}${use.running ? " agent-node__tool--running" : ""}`}
                    title={`${use.tool}: ${String(use.calls)} executed, ${String(use.denied)} denied`}
                  >
                    {chipLabel(use.tool)}
                    {use.calls > 0 && <b>{use.calls}</b>}
                    {use.denied > 0 && <i>{use.denied}</i>}
                  </span>
                ))}
                {tools.length > CHIP_LIMIT && (
                  <span
                    className="agent-node__tool"
                    title={tools
                      .slice(CHIP_LIMIT)
                      .map((use) => `${use.tool}: ${String(use.calls)} executed, ${String(use.denied)} denied`)
                      .join("\n")}
                  >
                    +{tools.length - CHIP_LIMIT}
                  </span>
                )}
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
          <Icon name="flag" size={16} />
        </span>
        <span className="flow-node__title">Goal</span>
      </div>
      <div className="end-node__text" title={data.goal ?? undefined}>
        {data.goal ?? "Waiting for the run to start"}
      </div>
      <div className="end-node__foot">
        {data.channel !== null ? `from ${data.channel}` : "from this window"}
        {data.excerpts > 0 && ` · ${String(data.excerpts)} vault excerpt${data.excerpts === 1 ? "" : "s"}`}
      </div>
    </div>
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
          {data.status === "completed" ? <Icon name="check" size={16} /> : data.status === "failed" ? <Icon name="x" size={16} /> : <Icon name="clock" size={16} />}
        </span>
        <span className="flow-node__title">Outcome</span>
        <span className={`flow-node__state flow-node__state--${data.status}`}>{STATUS_LABEL[data.status]}</span>
      </div>
      <div className="end-node__text" title={data.claim === null ? undefined : ellipsise(data.claim.text, TOOLTIP_CHARS)}>
        {text}
      </div>
      <div className="end-node__foot">
        {data.agents} agent{data.agents === 1 ? "" : "s"} · {data.toolCalls} tool call
        {data.toolCalls === 1 ? "" : "s"}
        {data.errors > 0 && ` · ${String(data.errors)} error${data.errors === 1 ? "" : "s"}`}
        {data.memoryPath !== null && " · saved as memory"}
      </div>
    </div>
  );
}

const nodeTypes = { agent: AgentCard, goal: GoalCard, outcome: OutcomeCard };

/** How far in from the target card a forward label's right edge sits. */
const LABEL_INSET = 10;
/** How far above its line a label sits, so the arrow stays legible beneath it. */
const LABEL_LIFT = 11;

/**
 * Draw handoff labels in HTML above paths. Forward labels sit over each edge's
 * final segment to avoid sibling crossings; return labels sit by their bottom
 * departure port. Tooltips retain full tasks.
 */
function HandoffEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  markerEnd,
  style,
  label,
  data,
}: EdgeProps<HandoffEdgeType>) {
  const [path] = getSmoothStepPath({
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition,
  });
  const forward = data?.forward ?? false;
  const x = forward ? targetX - LABEL_INSET : sourceX + LABEL_INSET;
  const y = forward ? targetY - LABEL_LIFT : sourceY + LABEL_LIFT;
  const task = data?.task ?? "";
  return (
    <>
      <BaseEdge
        id={id}
        path={path}
        {...(markerEnd === undefined ? {} : { markerEnd })}
        {...(style === undefined ? {} : { style })}
      />
      {label !== undefined && label !== "" && (
        <EdgeLabelRenderer>
          <div
            className={`flow-edge__label nodrag nopan${forward ? " flow-edge__label--forward" : ""}`}
            style={{ transform: `translate(${forward ? "-100%" : "0"}, -50%) translate(${String(x)}px, ${String(y)}px)` }}
            title={task === "" ? undefined : task}
            data-testid={`edge-label-${id}`}
          >
            {label}
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  );
}

const edgeTypes = { handoff: HandoffEdge };

/**
 * Apply {@link viewportFor} on node-set and pane-size changes; terminal summary
 * growth otherwise makes live/replay framing diverge.
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
    // Preserve user camera across node and pane changes.
    if (userMoved) return;
    void flow.setViewport(viewportFor(nodes, pane.width, pane.height));
    // Node IDs, not array identity, determine camera changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [flow, signature, pane, userMoved]);

  return null;
}

export function RunGraph({ view, selectedAgent, onSelectAgent, expanded, onToggleExpand }: RunGraphProps) {
  const nodes = useMemo(() => layout(view, selectedAgent), [view, selectedAgent]);
  const graphEdges = useMemo(() => workflowEdges(view), [view]);
  // Mark user-originated camera changes (programmatic events are null). State
  // rerenders `Camera`; full-window changes reframe the new pane.
  const [userMoved, setUserMoved] = useState(false);
  const [seenExpanded, setSeenExpanded] = useState(expanded);
  if (seenExpanded !== expanded) {
    setSeenExpanded(expanded);
    setUserMoved(false);
  }

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
        edgeTypes={edgeTypes}
        // Log projection, not editable diagram; dragging implies unsupported meaning.
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
          if (event !== null) setUserMoved(true);
        }}
      >
        <Camera nodes={nodes} userMoved={userMoved} />
        <Background variant={BackgroundVariant.Dots} gap={22} size={1.2} />
        <Controls showInteractive={false}>
          {onToggleExpand !== undefined && (
            <ControlButton
              onClick={onToggleExpand}
              title={expanded ? "Leave full screen (Esc)" : "Full screen"}
              aria-label={expanded ? "Leave full screen" : "Full screen"}
              aria-pressed={expanded ?? false}
              data-testid="graph-expand"
            >
              {expanded ? <Icon name="minimize-2" size={16} /> : <Icon name="maximize-2" size={16} />}
            </ControlButton>
          )}
        </Controls>
      </ReactFlow>
      {legend}
    </div>
  );
}
