import type { Event } from "@agentspace/schemas";

import { nowLine } from "../state/describe";
import type { RunView } from "../state/reducer";

import { ApprovalPanel, type ApprovalPanelProps } from "./ApprovalPanel";
import { EventLog } from "./EventLog";
import { RunGraph } from "./RunGraph";
import { RunSummary } from "./RunSummary";

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
        <RunSummary view={view} />

        {/* One sentence about the run at this cursor. Derived from the fold,
            so it is the same sentence live and on replay, and it is the
            first thing a person reads, above a graph that takes longer. */}
        <p className="now-line" data-testid="now-line">
          {nowLine(view)}
        </p>

        <div className="run-panel__canvas">
          <RunGraph view={view} selectedAgent={selectedName} onSelectAgent={onSelectAgent} />

          {selected !== null && (
            <aside className="agent-detail" data-testid="agent-detail">
              <h3>{selected.name}</h3>
              <p className="agent-detail__role">{selected.role ?? "-"}</p>
              <dl>
                <div>
                  <dt>Definition</dt>
                  <dd>{selected.definitionName ?? "built into the orchestrator"}</dd>
                </div>
                <div>
                  <dt>Model</dt>
                  <dd>
                    {selected.provider ?? "?"} · {selected.model ?? "?"}
                  </dd>
                </div>
                <div>
                  <dt>Steps</dt>
                  <dd>
                    {selected.steps}
                    {selected.maxSteps === null ? "" : ` of ${String(selected.maxSteps)}`}
                  </dd>
                </div>
                <div>
                  <dt>Tools it may call</dt>
                  <dd>
                    {selected.allowedTools.length === 0 ? "none" : selected.allowedTools.join(", ")}
                  </dd>
                </div>
              </dl>

              {selected.systemPrompt !== null && (
                <details className="agent-detail__prompt">
                  {/* In the log since Phase 5, and the most load-bearing fact
                      about why two runs of the same goal behaved differently. */}
                  <summary>System prompt</summary>
                  <pre>{selected.systemPrompt}</pre>
                </details>
              )}

              {selected.streamedText !== "" && (
                <details className="agent-detail__stream">
                  <summary>Streamed output</summary>
                  <pre>{selected.streamedText}</pre>
                </details>
              )}
            </aside>
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
