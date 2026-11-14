import type { Event } from "@agentbase/schemas";
import { useEffect, useMemo, useRef, useState, type RefObject } from "react";

import { ellipsise, formatCount, formatMicros, summariseArgs } from "../lib/format";
import { activityLabel, nowLine } from "../state/describe";
import { writtenFiles, type WrittenFile } from "../state/files";
import { officeOf } from "../state/office";
import type { AgentNode, Denial, Handoff, RunView, ToolCall } from "../state/reducer";
import { useMotionMode } from "../state/useMotionMode";
import { useStoredFlag } from "../state/useStoredFlag";
import { useStoredSize } from "../state/useStoredSize";

import { ApprovalPanel, type ApprovalPanelProps } from "./ApprovalPanel";
import { EventLog } from "./EventLog";
import { Markdown } from "./Markdown";
import { RunSummary, type RunSummaryProps } from "./RunSummary";
import { Scrubber } from "./Scrubber";
import { Splitter } from "./Splitter";
import { OfficeScene } from "./office/OfficeScene";
import { Inspector, InspectorGroup } from "./ui/Inspector";

/**
 * Run dashboard splits pure `run-projection` from scrubber transport. Given the
 * same `view` and cursor prefix, it produces byte-identical DOM (tested by
 * `replayIdentity.test.tsx`). Approval question projects history; actions are
 * transport.
 */

/** Viewer panel-size bounds; CSS defaults apply until set. */
const SUMMARY_HEIGHT_MIN = 96;
const SUMMARY_HEIGHT_MAX = 1200;
const CANVAS_HEIGHT_MIN = 160;
const CANVAS_HEIGHT_MAX = 1600;
const LOG_HEIGHT_MIN = 144;
const DETAIL_WIDTH_FALLBACK = 315;
const DETAIL_WIDTH_MIN = 240;

export interface RunPanelProps {
  view: RunView;
  /** See {@link RunSummaryProps.title}. */
  title?: RunSummaryProps["title"];
  events: readonly Event[];
  cursor: number;
  selectedAgent: string | null;
  onSelectAgent: (agent: string | null) => void;
  onCursorChange: (cursor: number) => void;
  /** See {@link ApprovalPanelProps.readOnly}. */
  approvalReadOnly: ApprovalPanelProps["readOnly"];
  onResolveApproval: ApprovalPanelProps["onResolve"];
  /** Previous run stays dimmed while next history loads. */
  loading?: boolean;
  onCapture?: ((event: Event) => void) | undefined;
  /** See {@link RunSummaryProps.onOpenNote}. */
  onOpenNote?: RunSummaryProps["onOpenNote"];
  /** See {@link RunSummaryProps.onOpenFile}. */
  onOpenFile?: RunSummaryProps["onOpenFile"];
  /** See linked `RunSummaryProps` memory fields. */
  spaceId?: RunSummaryProps["spaceId"];
  onOpenMemory?: RunSummaryProps["onOpenMemory"];
  onMemoryChanged?: RunSummaryProps["onMemoryChanged"];
  /**
   * New events can still arrive: the run is going and its stream is
   * followed. Only the caller knows; a log that ends mid-run may be a run
   * that stopped without saying so.
   */
  live?: boolean | undefined;
}

export function RunPanel({
  view,
  title,
  events,
  cursor,
  selectedAgent,
  onSelectAgent,
  onCursorChange,
  approvalReadOnly,
  onResolveApproval,
  loading = false,
  onCapture,
  onOpenNote,
  onOpenFile,
  spaceId,
  onOpenMemory,
  onMemoryChanged,
  live = false,
}: RunPanelProps) {
  const scrubbed = cursor < events.length;

  // Caller selection survives scrubbing even before its agent exists; share it
  // across the office, inspector, and log.
  const selected = selectedAgent === null ? null : (view.agents[selectedAgent] ?? null);
  const selectedName = selected === null ? null : selectedAgent;

  // Viewer controls summary/canvas heights and inspector width; sized summaries
  // scroll without folding.
  const [summaryHeight, setSummaryHeight] = useStoredSize("runs.summary");
  const [canvasHeight, setCanvasHeight] = useStoredSize("runs.canvas");
  const [detailWidth, setDetailWidth] = useStoredSize("runs.detail");
  // The run drawn as a room (decision D8 retired the diagram on 2026-11-14).
  const office = useMemo(() => officeOf(view), [view]);
  // The selected agent's files, found again only when the calls change.
  const toolCalls = view.toolCalls;
  const selectedFiles = useMemo(() => (selectedName === null ? [] : writtenFiles({ toolCalls }, selectedName)), [toolCalls, selectedName]);
  // A step forward may animate; anything else settles at once (transport).
  const motion = useMotionMode(events, cursor);
  // A viewer can fold the log to its latest step; the canvas takes the room.
  // It starts folded, because a room needs about half its width in height
  // and the room already says what the latest step is. The key is the one
  // the office used beside the diagram, so a viewer's choice carries over.
  const [logCollapsed, setLogCollapsed] = useStoredFlag("runs.office.log.collapsed", true);
  const projection = useRef<HTMLDivElement>(null);
  const summary = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLDivElement>(null);
  const detail = useRef<HTMLElement>(null);
  // Canvas can fill window; Escape restores it.
  const [expanded, setExpanded] = useState(false);
  useEffect(() => {
    if (!expanded) return undefined;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setExpanded(false);
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
    };
  }, [expanded]);
  const canvasMax = () => {
    // Preserve log minimum height so divider cannot hide it.
    const box = projection.current;
    const pane = canvas.current;
    if (box === null || pane === null) return CANVAS_HEIGHT_MAX;
    const top = pane.getBoundingClientRect().top - box.getBoundingClientRect().top;
    return Math.max(CANVAS_HEIGHT_MIN, Math.round(box.clientHeight - top - LOG_HEIGHT_MIN));
  };

  return (
    <div
      className={`run-panel${loading ? " run-panel--loading" : ""}`}
      data-testid="run-panel"
      aria-busy={loading}
    >
      <Scrubber
        events={events}
        cursor={cursor}
        onCursorChange={onCursorChange}
        loading={loading}
        live={live && !scrubbed}
      />

      <ApprovalPanel
        approvals={view.approvals}
        onResolve={onResolveApproval}
        readOnly={approvalReadOnly}
      />

      <div
        className={`run-projection${logCollapsed ? " run-projection--log-collapsed" : ""}`}
        data-testid="run-projection"
        ref={projection}
        style={
          canvasHeight === null || logCollapsed
            ? undefined
            : { gridTemplateRows: `auto auto minmax(${String(CANVAS_HEIGHT_MIN)}px, ${String(canvasHeight)}px) minmax(${String(LOG_HEIGHT_MIN)}px, 1fr)` }
        }
      >
        <div
          className="run-panel__summary"
          ref={summary}
          style={summaryHeight === null ? undefined : { height: `${String(summaryHeight)}px` }}
        >
          <RunSummary
            view={view}
            title={title}
            onOpenNote={onOpenNote}
            onOpenFile={onOpenFile}
            spaceId={spaceId}
            onOpenMemory={onOpenMemory}
            onMemoryChanged={onMemoryChanged}
            unfolded={summaryHeight !== null}
          />
          <Splitter
            axis="y"
            side="end"
            value={summaryHeight}
            measure={() => summary.current?.offsetHeight ?? SUMMARY_HEIGHT_MIN}
            min={SUMMARY_HEIGHT_MIN}
            max={() => SUMMARY_HEIGHT_MAX}
            onChange={setSummaryHeight}
            label="Resize the summary"
          />
        </div>

        {/* One sentence about the run at this cursor. Derived from the fold,
            so it is the same sentence live and on replay, and it is the
            first thing a person reads, above a room that takes longer. */}
        <p className="now-line" data-testid="now-line">
          {nowLine(view)}
        </p>

        <div className={`run-panel__canvas${expanded ? " run-panel__canvas--expanded" : ""}`} ref={canvas}>
          <OfficeScene
            model={office}
            description={nowLine(view)}
            selectedAgent={selectedName}
            onSelectAgent={onSelectAgent}
            onOpenFile={onOpenFile === undefined ? undefined : (path) => { onOpenFile(path); }}
            motion={motion}
            expanded={expanded}
            onToggleExpand={() => {
              setExpanded((current) => !current);
            }}
          />

          {selected !== null && selectedName !== null && (
            <AgentDetail
              agent={selected}
              calls={view.toolCalls.filter((call) => call.agent === selectedName)}
              denials={view.denials.filter((denial) => denial.agent === selectedName)}
              handoffs={view.handoffs.filter((handoff) => handoff.from === selectedName)}
              files={selectedFiles}
              onOpenNote={onOpenNote}
              onOpenFile={onOpenFile}
              onClose={() => {
                onSelectAgent(null);
              }}
              width={detailWidth}
              onResize={setDetailWidth}
              panelRef={detail}
              measure={() => detail.current?.offsetWidth ?? DETAIL_WIDTH_FALLBACK}
              max={() => Math.max(DETAIL_WIDTH_MIN, Math.round((canvas.current?.offsetWidth ?? 900) * 0.7))}
            />
          )}

          {!expanded && !logCollapsed && (
            <Splitter
              axis="y"
              side="end"
              value={canvasHeight}
              measure={() => canvas.current?.offsetHeight ?? CANVAS_HEIGHT_MIN}
              min={CANVAS_HEIGHT_MIN}
              max={canvasMax}
              onChange={setCanvasHeight}
              label="Resize the canvas"
            />
          )}
        </div>

        <EventLog
          events={events}
          cursor={cursor}
          agents={view.agentOrder}
          selectedAgent={selectedName}
          onSelectAgent={onSelectAgent}
          onCapture={onCapture}
          collapsed={logCollapsed}
          onCollapsedChange={setLogCollapsed}
        />
      </div>
    </div>
  );
}

/**
 * Agent inspector: identity, speech, tools, and handoffs from the same cursor
 * `view` as canvas, keeping live/replay identical.
 */
function AgentDetail({
  agent,
  calls,
  denials,
  handoffs,
  files,
  onOpenNote,
  onOpenFile,
  onClose,
  width,
  onResize,
  panelRef,
  measure,
  max,
}: {
  agent: AgentNode;
  calls: readonly ToolCall[];
  denials: readonly Denial[];
  handoffs: readonly Handoff[];
  /** Files this agent's calls wrote; each opens in Knowledge, a note as a note, as the run summary's do. */
  files: readonly WrittenFile[];
  onOpenNote?: RunSummaryProps["onOpenNote"];
  onOpenFile?: RunSummaryProps["onOpenFile"];
  onClose: () => void;
  /** The viewer's width for the panel, or null for the stylesheet's. */
  width: number | null;
  onResize: (width: number | null) => void;
  panelRef: RefObject<HTMLElement | null>;
  measure: () => number;
  max: () => number;
}) {
  const activity = [
    ...calls.map((call) => ({ seq: call.seq, kind: "call" as const, call, denial: null })),
    ...denials.map((denial) => ({ seq: denial.seq, kind: "denial" as const, call: null, denial })),
  ].sort((left, right) => left.seq - right.seq);

  // On a narrow canvas the panel covers the drawing (run-canvas.css), so the
  // control that opened it is hidden: whenever the panel comes to cover it,
  // on opening or as the window narrows, it takes the focus, and gives it
  // back when it closes. Beside the drawing it leaves the focus where it is.
  useEffect(() => {
    const panel = panelRef.current;
    const host = panel?.parentElement ?? null;
    if (panel === null || host === null) return undefined;
    let opener: HTMLElement | null = null;
    let covering = false;
    const check = () => {
      const covers = getComputedStyle(panel).position === "absolute";
      if (covers && !covering && !panel.contains(document.activeElement)) {
        const active = document.activeElement;
        if (active instanceof HTMLElement && active !== document.body) opener = active;
        panel.focus({ preventScroll: true });
      }
      covering = covers;
    };
    check();
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(check);
    observer?.observe(host);
    return () => {
      observer?.disconnect();
      const now = document.activeElement;
      if (now === null || now === document.body || panel.contains(now)) opener?.focus();
    };
  }, [panelRef]);

  return (
    <Inspector
      label="Agent detail"
      className="agent-detail"
      testId="agent-detail"
      panelRef={panelRef}
      title={agent.name}
      subtitle={agent.role ?? "-"}
      onClose={onClose}
      closeLabel="Close the agent detail"
      width={width}
      onResize={onResize}
      defaultWidth={DETAIL_WIDTH_FALLBACK}
      minWidth={DETAIL_WIDTH_MIN}
      maxWidth={max}
      measure={measure}
      resizeLabel="Resize the agent detail"
      onKeyDown={(event) => {
        // Escape closes the panel and nothing else: a full-screen canvas
        // stays full screen until the next one.
        if (event.key !== "Escape") return;
        event.stopPropagation();
        onClose();
      }}
    >
      <p className={`agent-detail__state agent-detail__state--${agent.activity}`}>
        {agent.lastError === null ? activityLabel(agent) : `error · ${agent.lastError}`}
      </p>

      <dl>
        <div>
          <dt>Definition</dt>
          <dd>{agent.definitionName ?? "built into the orchestrator"}</dd>
        </div>
        <div>
          <dt>Model</dt>
          <dd>
            {agent.provider ?? "?"} · {agent.model ?? "?"}
          </dd>
        </div>
        <div>
          <dt>Steps</dt>
          <dd>
            {agent.steps}
            {agent.maxSteps === null ? "" : ` of ${String(agent.maxSteps)}`}
          </dd>
        </div>
        <div>
          <dt>Tools it may call</dt>
          <dd>{agent.allowedTools.length === 0 ? "none" : agent.allowedTools.join(", ")}</dd>
        </div>
        {agent.calls > 0 && (
          <>
            <div>
              <dt>Model calls</dt>
              <dd data-testid="agent-usage">
                {agent.calls} · {formatCount(agent.inputTokens)} in, {formatCount(agent.outputTokens)} out ·{" "}
                {formatMicros(agent.costMicros)}
              </dd>
            </div>
            <div>
              <dt>Context</dt>
              <dd data-testid="agent-context">
                {formatCount(agent.lastContext ?? 0)} tokens on the last call
                {agent.peakContext > (agent.lastContext ?? 0) && `, ${formatCount(agent.peakContext)} at most`}
              </dd>
            </div>
          </>
        )}
      </dl>

      {agent.lastMessage !== null && (
        <InspectorGroup title="Last message" testId="agent-last-message">
          <Markdown source={agent.lastMessage} className="md--compact" />
        </InspectorGroup>
      )}

      {handoffs.length > 0 && (
        <InspectorGroup title="Handed off">
          <ul className="agent-detail__list">
            {handoffs.map((handoff) => (
              <li key={handoff.seq}>
                <strong>{handoff.to}</strong>
                {handoff.task !== "" && <span>{ellipsise(handoff.task, 120)}</span>}
              </li>
            ))}
          </ul>
        </InspectorGroup>
      )}

      {files.length > 0 && (
        <InspectorGroup title="Files it wrote" testId="agent-files">
          <ul className="agent-detail__list">
            {files.map((file) => {
              const open =
                file.kind === "note"
                  ? onOpenNote &&
                    (() => {
                      onOpenNote(file.path, null);
                    })
                  : onOpenFile &&
                    (() => {
                      onOpenFile(file.path);
                    });
              return (
                <li key={file.path}>
                  {open === undefined ? (
                    <span className="agent-detail__file">{file.path}</span>
                  ) : (
                    <button type="button" className="link agent-detail__file" onClick={open}>
                      {file.path}
                    </button>
                  )}
                </li>
              );
            })}
          </ul>
        </InspectorGroup>
      )}

      {activity.length > 0 && (
        <InspectorGroup title="Tool calls" testId="agent-tool-calls">
          <ul className="agent-detail__list">
            {activity.map((entry) =>
              entry.kind === "call" ? (
                <li key={entry.seq} className="agent-detail__call">
                  <strong>
                    {entry.call.tool}
                    <span className="agent-detail__args">{summariseArgs(entry.call.args)}</span>
                  </strong>
                  <span>
                    {entry.call.result === null ? "no result yet" : ellipsise(entry.call.result.replace(/\s+/g, " "), 140)}
                  </span>
                </li>
              ) : (
                <li key={entry.seq} className="agent-detail__call agent-detail__call--denied">
                  <strong>{entry.denial.tool}</strong>
                  <span>
                    {entry.denial.blockedBy === "sandbox" ? "refused by the sandbox: " : "denied: "}
                    {ellipsise(entry.denial.reason, 140)}
                  </span>
                </li>
              ),
            )}
          </ul>
        </InspectorGroup>
      )}

      {agent.systemPrompt !== null && (
        // In the log since Phase 5, and the most load-bearing fact about why
        // two runs of the same goal behaved differently.
        <InspectorGroup title="System prompt" folded className="agent-detail__prompt">
          <pre>{agent.systemPrompt}</pre>
        </InspectorGroup>
      )}

      {agent.streamedText !== "" && (
        <InspectorGroup title="Streamed output" folded className="agent-detail__stream">
          <Markdown source={agent.streamedText} className="md--compact agent-detail__stream-text" />
        </InspectorGroup>
      )}
    </Inspector>
  );
}
