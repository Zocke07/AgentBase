import type { Event } from "@agentspace/schemas";

import { ellipsise, summariseArgs } from "../lib/format";
import { activityLabel, nowLine } from "../state/describe";
import type { AgentNode, Denial, Handoff, RunView, ToolCall } from "../state/reducer";

import { ApprovalPanel, type ApprovalPanelProps } from "./ApprovalPanel";
import { EventLog } from "./EventLog";
import { Markdown } from "./Markdown";
import { RunGraph } from "./RunGraph";
import { RunSummary, type RunSummaryProps } from "./RunSummary";

/**
 * Everything the dashboard shows about a run, in two halves. The projection
 * (`run-projection`) is a pure function of `view` and `events.slice(0,
 * cursor)`: given the same log and cursor it renders byte-identical DOM, which
 * `replayIdentity.test.tsx` checks at every position. The transport (the
 * scrubber) sits outside it, because at event 12 of a finished run you are
 * standing somewhere and live you were at the end. The approval panel's
 * question is projection; its action row is transport.
 */

export interface RunPanelProps {
  view: RunView;
  events: readonly Event[];
  cursor: number;
  selectedAgent: string | null;
  onSelectAgent: (agent: string | null) => void;
  onCursorChange: (cursor: number) => void;
  /** See {@link ApprovalPanelProps.readOnly}. */
  approvalReadOnly: ApprovalPanelProps["readOnly"];
  onResolveApproval: ApprovalPanelProps["onResolve"];
  /** The previous run stays on screen, dimmed, while the next one's history is fetched. */
  loading?: boolean;
  onCapture?: ((event: Event) => void) | undefined;
  /** See {@link RunSummaryProps.onOpenNote}. */
  onOpenNote?: RunSummaryProps["onOpenNote"];
}

export function RunPanel({
  view,
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
}: RunPanelProps) {
  const scrubbed = cursor < events.length;
  // Room for the widest reading the counter will show ("28 / 28") so the
  // track beside it does not move as the number changes under the thumb.
  const counterWidth = `${String(String(events.length).length * 2 + 3)}ch`;

  // The selection is the caller's and survives a scrub; the agent it names may
  // not exist yet at this cursor. One decision here, handed to the graph, the
  // aside and the log alike, so they cannot disagree about who is selected.
  const selected = selectedAgent === null ? null : (view.agents[selectedAgent] ?? null);
  const selectedName = selected === null ? null : selectedAgent;

  return (
    <div
      className={`run-panel${loading ? " run-panel--loading" : ""}`}
      data-testid="run-panel"
      aria-busy={loading}
    >
      <div className="scrubber" data-testid="scrubber">
        <label className="scrubber__control">
          <span className="scrubber__label">Replay</span>
          <input
            type="range"
            min={0}
            max={events.length}
            value={cursor}
            disabled={loading}
            aria-label="Position in the event log"
            onChange={(changed) => {
              onCursorChange(Number(changed.target.value));
            }}
          />
        </label>
        <span className="scrubber__position" data-testid="scrub-position" style={{ minWidth: counterWidth }}>
          {cursor} / {events.length}
        </span>
        {/* Always rendered, fixed width. The range input shares this flex row
            and takes what is left of it: a slot that came and went with the
            scrub state changed the track's length under the pointer mid-drag. */}
        <span className="scrubber__state" data-testid="scrub-state">
          {scrubbed ? (
            <>
              <span className="scrubber__notice" data-testid="scrub-notice">
                Showing an earlier point in this run.
              </span>
              <button
                type="button"
                className="button button--small"
                disabled={loading}
                onClick={() => {
                  onCursorChange(events.length);
                }}
              >
                Jump to end
              </button>
            </>
          ) : (
            <span className="scrubber__latest">Showing the latest event.</span>
          )}
        </span>
      </div>

      <ApprovalPanel
        approvals={view.approvals}
        onResolve={onResolveApproval}
        readOnly={approvalReadOnly}
      />

      <div className="run-projection" data-testid="run-projection">
        <RunSummary view={view} onOpenNote={onOpenNote} />

        {/* One sentence about the run at this cursor. Derived from the fold,
            so it is the same sentence live and on replay, and it is the
            first thing a person reads, above a graph that takes longer. */}
        <p className="now-line" data-testid="now-line">
          {nowLine(view)}
        </p>

        <div className="run-panel__canvas">
          <RunGraph view={view} selectedAgent={selectedName} onSelectAgent={onSelectAgent} />

          {selected !== null && selectedName !== null && (
            <AgentDetail
              agent={selected}
              calls={view.toolCalls.filter((call) => call.agent === selectedName)}
              denials={view.denials.filter((denial) => denial.agent === selectedName)}
              handoffs={view.handoffs.filter((handoff) => handoff.from === selectedName)}
              onClose={() => {
                onSelectAgent(null);
              }}
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
        />
      </div>
    </div>
  );
}

/**
 * The inspector for one agent: what it is, what it said, what it did with
 * its tools and whom it handed work to. Everything here is read off `view`
 * for the same cursor as the canvas, so it is the same live and on replay.
 */
function AgentDetail({
  agent,
  calls,
  denials,
  handoffs,
  onClose,
}: {
  agent: AgentNode;
  calls: readonly ToolCall[];
  denials: readonly Denial[];
  handoffs: readonly Handoff[];
  onClose: () => void;
}) {
  const activity = [
    ...calls.map((call) => ({ seq: call.seq, kind: "call" as const, call, denial: null })),
    ...denials.map((denial) => ({ seq: denial.seq, kind: "denial" as const, call: null, denial })),
  ].sort((left, right) => left.seq - right.seq);

  return (
    <aside className="agent-detail" data-testid="agent-detail">
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
