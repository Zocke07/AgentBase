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
import { RunGraph } from "./RunGraph";
import { RunSummary, type RunSummaryProps } from "./RunSummary";
import { Scrubber } from "./Scrubber";
import { Splitter } from "./Splitter";
import { OfficeScene } from "./office/OfficeScene";
import { Segmented } from "./ui/controls";

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
const DETAIL_WIDTH_FALLBACK = 336;
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
   * Which drawing of the run to show, whatever the viewer last chose: the
   * workbench and tests use it. Left out, the viewer's choice applies.
   */
  canvas?: "office" | "diagram" | undefined;
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
  canvas: canvasChoice,
  live = false,
}: RunPanelProps) {
  const scrubbed = cursor < events.length;

  // Caller selection survives scrubbing even before its agent exists; share it
  // across graph, inspector, and log.
  const selected = selectedAgent === null ? null : (view.agents[selectedAgent] ?? null);
  const selectedName = selected === null ? null : selectedAgent;

  // Viewer controls summary/canvas heights and inspector width; sized summaries
  // scroll without folding.
  const [summaryHeight, setSummaryHeight] = useStoredSize("runs.summary");
  const [canvasHeight, setCanvasHeight] = useStoredSize("runs.canvas");
  const [detailWidth, setDetailWidth] = useStoredSize("runs.detail");
  // Office or Diagram (decision D8): the viewer's choice, kept on this
  // computer. The office is what a run opens on; the diagram stays one
  // press away until D8 is settled.
  const [officeChosen, setOfficeChosen] = useStoredFlag("runs.office", true);
  // Where a caller names the drawing, that is where this panel starts, and
  // the switch then changes this panel alone, not the viewer's stored choice.
  const [officeHere, setOfficeHere] = useState(canvasChoice === "office");
  const showOffice = canvasChoice === undefined ? officeChosen : officeHere;
  // Projected only when it is shown: the diagram needs none of it.
  const office = useMemo(() => (showOffice ? officeOf(view) : null), [showOffice, view]);
  // The selected agent's files, found again only when the calls change.
  const toolCalls = view.toolCalls;
  const selectedFiles = useMemo(() => (selectedName === null ? [] : writtenFiles({ toolCalls }, selectedName)), [toolCalls, selectedName]);
  // A step forward may animate; anything else settles at once (transport).
  const motion = useMotionMode(events, cursor);
  // A viewer can fold the log to its latest step; the canvas takes the room.
  // Beside the office it starts folded, because a room needs about half its
  // width in height and the room already says what the latest step is. Each
  // drawing keeps its own choice, so opening the log here does not open it
  // under the diagram.
  const [diagramLogCollapsed, setDiagramLogCollapsed] = useStoredFlag("runs.log.collapsed");
  const [officeLogCollapsed, setOfficeLogCollapsed] = useStoredFlag("runs.office.log.collapsed", true);
  const logCollapsed = showOffice ? officeLogCollapsed : diagramLogCollapsed;
  const setLogCollapsed = showOffice ? setOfficeLogCollapsed : setDiagramLogCollapsed;
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
        className={`run-projection${showOffice ? " run-projection--office" : ""}${logCollapsed ? " run-projection--log-collapsed" : ""}`}
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
            compact={showOffice}
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
            first thing a person reads, above a graph that takes longer. */}
        <p className="now-line" data-testid="now-line">
          {nowLine(view)}
        </p>

        <div className={`run-panel__canvas${expanded ? " run-panel__canvas--expanded" : ""}`} ref={canvas}>
          <div className="run-panel__view-switch">
            <Segmented
              label="How the run is drawn"
              value={showOffice ? "office" : "diagram"}
              options={[
                { value: "office", label: "Office", icon: "users" },
                { value: "diagram", label: "Diagram", icon: "network" },
              ]}
              onChange={(next) => {
                if (canvasChoice === undefined) setOfficeChosen(next === "office");
                else setOfficeHere(next === "office");
              }}
              testId="run-view-switch"
            />
          </div>
          {office !== null ? (
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
          ) : (
            <RunGraph
              view={view}
              selectedAgent={selectedName}
              onSelectAgent={onSelectAgent}
              expanded={expanded}
              onToggleExpand={() => {
                setExpanded((current) => !current);
              }}
            />
          )}

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

  // On a narrow canvas the panel covers the drawing (graph.css), so the
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
    <aside
      className="agent-detail"
      data-testid="agent-detail"
      ref={panelRef}
      tabIndex={-1}
      style={width === null ? undefined : { width: `${String(width)}px` }}
      onKeyDown={(event) => {
        // Escape closes the panel and nothing else: a full-screen canvas
        // stays full screen until the next one.
        if (event.key !== "Escape") return;
        event.stopPropagation();
        onClose();
      }}
    >
      <Splitter
        axis="x"
        side="start"
        value={width}
        measure={measure}
        min={DETAIL_WIDTH_MIN}
        max={max}
        onChange={onResize}
        label="Resize the agent detail"
      />
      <header className="agent-detail__head">
        <div>
          <h3>{agent.name}</h3>
          <p className="agent-detail__role">{agent.role ?? "-"}</p>
        </div>
        <button type="button" className="agent-detail__close" aria-label="Close the agent detail" onClick={onClose}>
          {"✕"}
        </button>
      </header>

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
        <section className="agent-detail__section" data-testid="agent-last-message">
          <h4>Last message</h4>
          <Markdown source={agent.lastMessage} className="md--compact" />
        </section>
      )}

      {handoffs.length > 0 && (
        <section className="agent-detail__section">
          <h4>Handed off</h4>
          <ul className="agent-detail__list">
            {handoffs.map((handoff) => (
              <li key={handoff.seq}>
                <strong>{handoff.to}</strong>
                {handoff.task !== "" && <span>{ellipsise(handoff.task, 120)}</span>}
              </li>
            ))}
          </ul>
        </section>
      )}

      {files.length > 0 && (
        <section className="agent-detail__section" data-testid="agent-files">
          <h4>Files it wrote</h4>
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
        </section>
      )}

      {activity.length > 0 && (
        <section className="agent-detail__section" data-testid="agent-tool-calls">
          <h4>Tool calls</h4>
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
        </section>
      )}

      {agent.systemPrompt !== null && (
        <details className="agent-detail__prompt">
          {/* In the log since Phase 5, and the most load-bearing fact
              about why two runs of the same goal behaved differently. */}
          <summary>System prompt</summary>
          <pre>{agent.systemPrompt}</pre>
        </details>
      )}

      {agent.streamedText !== "" && (
        <details className="agent-detail__stream">
          <summary>Streamed output</summary>
          <Markdown source={agent.streamedText} className="md--compact agent-detail__stream-text" />
        </details>
      )}
    </aside>
  );
}
