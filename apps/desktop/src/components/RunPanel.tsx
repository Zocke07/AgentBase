import type { Event } from "@agentspace/schemas";

import type { RunView } from "../state/reducer";

import { ApprovalPanel, type ApprovalPanelProps } from "./ApprovalPanel";
import { EventLog } from "./EventLog";
import { RunGraph } from "./RunGraph";
import { RunSummary } from "./RunSummary";

/**
 * Everything the dashboard shows about a run.
 *
 * The panel has two halves and the split is the whole point.
 *
 * **The projection** (`run-projection`) is a pure function of the log: the
 * summary, the graph, the agent detail and the event rows. Its entire input is
 * `view` and `events.slice(0, cursor)`. It fetches nothing, reads no clock and
 * keeps no state about the run, so given the same log and the same cursor it
 * renders byte-identical DOM. That is BUILD_SPEC §5 Phase 7's acceptance
 * criterion — "replaying a completed run produces pixel-identical UI state to
 * what was shown live" — and `replayIdentity.test.tsx` checks it directly.
 *
 * **The transport** (the scrubber) is deliberately *outside* that boundary,
 * because it honestly differs. Watching live at event 12, the log has 12 events
 * in it. Replaying the same run at event 12, the log has 28 and you are
 * standing at 12 of them. The projection is identical in both cases; the
 * control that says where you are standing cannot be, and pretending otherwise
 * would mean hiding the length of the run being replayed.
 *
 * **The approval panel straddles the line, on purpose.** Its question and
 * history are a projection of the log and are compared live against replay
 * like everything in `run-projection`. Whether it can be *answered* is a fact
 * about where the viewer stands — live at the head, yes; scrubbed back, no —
 * so its action row is transport, and `readOnly` is decided by the caller from
 * the store's `following`, never from the folded view.
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
  /**
   * The run on screen is the previous one while the next one's history is
   * fetched. The projection stays — dimmed, its controls disabled — rather than
   * collapsing to an empty run and back, which read as a flash on every
   * switch. Transport, like the scrubber: replay never sets it.
   */
  loading?: boolean;
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
}: RunPanelProps) {
  const scrubbed = cursor < events.length;
  // Room for the widest reading the counter will show — "28 / 28" — so the
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

        <div className="run-panel__canvas">
          <RunGraph view={view} selectedAgent={selectedName} onSelectAgent={onSelectAgent} />

          {selected !== null && (
            <aside className="agent-detail" data-testid="agent-detail">
              <h3>{selected.name}</h3>
              <p className="agent-detail__role">{selected.role ?? "—"}</p>
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
        />
      </div>
    </div>
  );
}
