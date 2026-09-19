

import type { ApprovalResponse, Event } from "@agentspace/schemas";
import { useCallback, useEffect, useRef, useState } from "react";

import * as api from "../lib/api";
import { captureText } from "../state/describe";
import { hasMore, unfinished, useRunList } from "../state/runList";
import { useRunStore } from "../state/runStore";
import { useRunStream } from "../state/useRunStream";
import { useStoredSize } from "../state/useStoredSize";

import { ErrorBoundary } from "./ErrorBoundary";
import { RunCard } from "./RunCard";
import { RunPanel } from "./RunPanel";
import { Splitter } from "./Splitter";

/**
 * The Runs section: pick a run, watch or replay it. Everything about the run
 * is `RunPanel`'s; this is the chrome around it (picker, connection indicator,
 * cancel and delete) plus the one two-way piece: answering an approval.
 */

export interface RunsViewProps {
  /** Bumped by the shell whenever spend may have changed, to refresh the meter. */
  onRunChanged: () => void;
  /** Every approval waiting anywhere, so a card can say its run is stuck on one. */
  pendingApprovals: readonly ApprovalResponse[];
  /** Which run is open. Owned by the shell so it survives a section switch. */
  runId: string | null;
  onSelectRun: (runId: string | null) => void;
  /** Take the user to the Home screen, where a run is started. */
  onNewRun: () => void;
  /** Open a cited note in the Knowledge section. */
  onOpenNote?: ((path: string, heading: string | null) => void) | undefined;
  /** Open a run's memory beside the Knowledge inbox. */
  onOpenMemory?: ((path: string) => void) | undefined;
  /** A memory's status was changed from a run; the inbox should reload. */
  onMemoryChanged?: (() => void) | undefined;
}

function connectionLabel(
  connection: ReturnType<typeof useRunStore.getState>["connection"],
  gaps: number,
): string {
  // A gap is the server's "no gaps, no repeats" contract failing on the client
  // side. It should never show; if it does, it is the most important thing on
  // this line.
  const suffix = gaps === 0 ? "" : ` · ${String(gaps)} gap${gaps === 1 ? "" : "s"} in the log`;
  switch (connection.kind) {
    case "idle":
      return "no run selected";
    case "connecting":
      return `connecting…${suffix}`;
    case "live":
      return `live${suffix}`;
    case "closed":
      return `run finished: stream closed${suffix}`;
    case "error":
      return `${connection.message}${suffix}`;
  }
}

/** A piece of state that belongs to one run: read as empty for any other. */
/** The run list's width: the stylesheet's 19rem, and how far it may go. */
const LIST_WIDTH_FALLBACK = 304;
const LIST_WIDTH_MIN = 200;

interface PerRun<T> {
  runId: string | null;
  value: T;
}

export function RunsView({
  onRunChanged,
  pendingApprovals,
  runId,
  onSelectRun,
  onNewRun,
  onOpenNote,
  onOpenMemory,
  onMemoryChanged,
}: RunsViewProps) {
  const [cancelling, setCancelling] = useState(false);
  /** The run the sidecar accepted a cancel for; it stops at its next check. */
  const [stopping, setStopping] = useState<string | null>(null);
  // State that is about one run (the selected agent, a failed cancel's
  // message) is tagged with the run it belongs to and reads as empty for any
  // other, so switching runs needs no reset and no effect.
  const [selection, setSelection] = useState<PerRun<string | null>>({ runId: null, value: null });
  const [cancelFailure, setCancelFailure] = useState<PerRun<string | null>>({ runId: null, value: null });
  const [deleteAsked, setDeleteAsked] = useState<PerRun<boolean>>({ runId: null, value: false });
  const [deleting, setDeleting] = useState(false);
  const selectedAgent = selection.runId === runId ? selection.value : null;
  const cancelError = cancelFailure.runId === runId ? cancelFailure.value : null;
  const confirmingDelete = deleteAsked.runId === runId && deleteAsked.value;
  const setSelectedAgent = (value: string | null) => {
    setSelection({ runId, value });
  };
  const setCancelError = (value: string | null) => {
    setCancelFailure({ runId, value });
  };
  const setConfirmingDelete = (value: boolean) => {
    setDeleteAsked({ runId, value });
  };

  const view = useRunStore((state) => state.view);
  const loadedRunId = useRunStore((state) => state.runId);
  const headView = useRunStore((state) => state.headView);
  const events = useRunStore((state) => state.events);
  const cursor = useRunStore((state) => state.cursor);
  const following = useRunStore((state) => state.following);
  const connection = useRunStore((state) => state.connection);
  const gaps = useRunStore((state) => state.gaps);
  const setCursor = useRunStore((state) => state.setCursor);

  useRunStream(runId);

  // The store holds the previous run until the next one's history arrives.
  // While the two disagree, everything about the run is withheld and the
  // projection stays, dimmed, as the loading state.
  const loading = runId !== null && loadedRunId !== runId;

  const runs = useRunList((state) => state.runs);
  const runsLoading = useRunList((state) => state.loading);
  const runsLoaded = useRunList((state) => state.loaded);
  const runsError = useRunList((state) => state.error);
  const limit = useRunList((state) => state.limit);
  const reloadRuns = useRunList((state) => state.load);
  const ensureRuns = useRunList((state) => state.ensure);
  const loadMore = useRunList((state) => state.loadMore);

  useEffect(() => {
    ensureRuns();
  }, [ensureRuns]);

  const finished =
    view.status === "completed" || view.status === "failed" || view.status === "cancelled";

  // Whether an approval can be answered depends on where the viewer stands,
  // not on the fold: scrubbed back, "pending" is true of that moment only.
  const approvalReadOnly = loading ? "loading" : finished ? "finished" : following ? null : "replay";

  // When the log's status disagrees with the picker's row, the row is stale
  // and so may be the month's spend. Keyed on the head's status, not the
  // scrubbed view's, so scrubbing across the terminal event refetches nothing.
  const waitingRuns = new Set(pendingApprovals.map((approval) => approval.run_id));

  const selectedRow = runs.find((run) => run.id === runId);
  // Keyed on the run it was written for, so switching runs drops it.
  const [captureNotice, setCaptureNotice] = useState<{ runId: string; text: string } | null>(null);
  // The list's width is the viewer's to set; the stylesheet's applies until they do.
  const [listWidth, setListWidth] = useStoredSize("runs.list");
  const side = useRef<HTMLElement>(null);

  // A person's own note from an agent's words: written where automatic run
  // memories never go, so nothing app-owned overwrites it.
  const capture = async (event: Event) => {
    const prose = captureText(event);
    if (prose === null || selectedRow === undefined) return;
    const path = `captures/${selectedRow.id}-${String(event.seq)}.md`;
    const who = event.agent_id ?? "run";
    const content =
      `---\ntype: capture\nrun_id: ${selectedRow.id}\nevent_seq: ${String(event.seq)}\n` +
      `agent: ${who}\ncreated: ${event.ts.slice(0, 10)}\ntags:\n  - capture\n---\n` +
      `# ${who}: ${event.type}\n\n${prose}\n`;
    try {
      await api.saveKnowledgeNote(selectedRow.space_id, path, content);
      setCaptureNotice({ runId: selectedRow.id, text: `Saved ${path} to this space's Knowledge.` });
    } catch (failure) {
      setCaptureNotice({
        runId: selectedRow.id,
        text: failure instanceof Error ? failure.message : String(failure),
      });
    }
  };
  const headStatus = !loading && headView.eventCount > 0 ? headView.status : null;
  const rowStale = selectedRow !== undefined && headStatus !== null && selectedRow.status !== headStatus;

  useEffect(() => {
    if (rowStale) {
      onRunChanged();
      void reloadRuns();
    }
    // Deliberately keyed on the head status alone: a row still stale after the
    // reload (the table lags the log by a write) must not loop until it agrees.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [headStatus, onRunChanged]);

  // Whether the selected run is one that can still be stopped: the log says
  // it has not ended. Not the connection: a run whose stream is between
  // reconnects is still a run.
  const cancellable = runId !== null && headStatus !== null && unfinished({ status: headStatus });

  const cancel = async () => {
    if (runId === null) return;
    setCancelling(true);
    setCancelError(null);
    try {
      await api.cancelRun(runId);
      // No change to the run's state: `run.cancelled` arrives over the stream.
      // The button says the cancel was accepted, since a cooperative stop can
      // take as long as the model call in flight.
      setStopping(runId);
    } catch (failure) {
      setCancelError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setCancelling(false);
    }
  };

  // Deletable means ended: the log's word when it has one, else the row's.
  const settledStatus = headStatus ?? (loading ? null : (selectedRow?.status ?? null));
  const deletable = runId !== null && settledStatus !== null && !unfinished({ status: settledStatus });

  const remove = async () => {
    if (runId === null) return;
    setDeleting(true);
    setCancelError(null);
    try {
      await api.deleteRun(runId);
      // The run is gone: close it, and tell the picker and the meter. The
      // store keeps its fold until the next run opens; the placeholder hides it.
      onSelectRun(null);
      onRunChanged();
      void reloadRuns();
    } catch (failure) {
      setConfirmingDelete(false);
      setCancelError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setDeleting(false);
    }
  };

  const resolveApproval = useCallback(async (id: string, approved: boolean, scope: "call" | "run" = "call") => {
    await api.resolveApproval(id, approved, scope);
    // No local state change: the answer arrives over the stream as events (§2).
  }, []);

  return (
    <div
      className="runs-view"
      style={listWidth === null ? undefined : { gridTemplateColumns: `${String(listWidth)}px minmax(0, 1fr)` }}
    >
      <aside className="runs-view__side" ref={side}>
        <Splitter
          axis="x"
          side="end"
          value={listWidth}
          measure={() => side.current?.offsetWidth ?? LIST_WIDTH_FALLBACK}
          min={LIST_WIDTH_MIN}
          max={() => Math.max(LIST_WIDTH_MIN, Math.round(window.innerWidth * 0.5))}
          onChange={setListWidth}
          label="Resize the run list"
        />
        <header className="runs-view__head">
          <h2>Runs</h2>
          <button type="button" className="button button--small" onClick={onNewRun}>
            New run
          </button>
        </header>

        {runsError !== null && (
          <p className="field-error" role="alert">
            {runsError}
          </p>
        )}

        <ul className="run-list" data-testid="run-list">
          {runs.map((run) => (
            <li key={run.id}>
              {/* The log is the authority on the selected run; the row is a
                  snapshot that says "pending" for the whole of a live run. */}
              <RunCard
                run={run}
                compact
                selected={run.id === runId}
                liveStatus={run.id === runId ? headStatus : null}
                needsApproval={waitingRuns.has(run.id)}
                onOpen={onSelectRun}
              />
            </li>
          ))}
          {hasMore({ runs, limit }) && (
            <li className="run-list__more">
              <button type="button" className="button button--small" disabled={runsLoading} onClick={loadMore}>
                Load more
              </button>
            </li>
          )}
          {runs.length === 0 && <li className="run-list__empty">{runsLoaded ? "No runs yet." : "Loading…"}</li>}
        </ul>
      </aside>

      <main className="runs-view__main">
        {runId === null ? (
          <p className="runs-view__placeholder">Pick a run to watch it or replay it.</p>
        ) : (
          <>
            <div className="runs-view__strip">
              <p className="runs-view__connection" data-testid="connection-status">
                {loading ? "loading…" : connectionLabel(connection, gaps)}
              </p>
              {cancelError !== null && (
                <p className="runs-view__strip-error" role="alert">
                  {cancelError}
                </p>
              )}
              {captureNotice !== null && captureNotice.runId === runId && (
                <p className="runs-view__connection" role="status" data-testid="capture-notice">
                  {captureNotice.text}
                </p>
              )}
              {cancellable && (
                <button
                  type="button"
                  className="button button--small button--danger"
                  disabled={cancelling || stopping === runId}
                  onClick={() => void cancel()}
                >
                  {stopping === runId ? "Stopping…" : cancelling ? "Cancelling…" : "Cancel run"}
                </button>
              )}
              {deletable &&
                (confirmingDelete ? (
                  <span className="roster__confirm">
                    <span>Delete this run and its log? Its spend stays in the month's total.</span>
                    <button
                      type="button"
                      className="button button--small button--danger"
                      disabled={deleting}
                      onClick={() => void remove()}
                    >
                      {deleting ? "Deleting…" : "Delete"}
                    </button>
                    <button
                      type="button"
                      className="button button--small"
                      disabled={deleting}
                      onClick={() => {
                        setConfirmingDelete(false);
                      }}
                    >
                      Keep
                    </button>
                  </span>
                ) : (
                  <button
                    type="button"
                    className="button button--small button--danger"
                    onClick={() => {
                      setConfirmingDelete(true);
                    }}
                  >
                    Delete run…
                  </button>
                ))}
            </div>
            {/* Reset on the run so a panel that threw on one run does not
                stay in its fallback when another is opened, without
                remounting a healthy panel, which rebuilt the graph canvas on
                every switch. */}
            <ErrorBoundary resetKey={runId} label="the run view">
              {loadedRunId === null ? (
                // Nothing to keep on screen yet: the very first open.
                <p className="runs-view__placeholder">Loading the run…</p>
              ) : (
                <RunPanel
                  view={view}
                  events={events}
                  cursor={cursor}
                  selectedAgent={selectedAgent}
                  onSelectAgent={setSelectedAgent}
                  onCursorChange={setCursor}
                  approvalReadOnly={approvalReadOnly}
                  onResolveApproval={resolveApproval}
                  loading={loading}
                  onCapture={(event) => void capture(event)}
                  onOpenNote={onOpenNote}
                  spaceId={selectedRow?.space_id ?? null}
                  onOpenMemory={onOpenMemory}
                  onMemoryChanged={onMemoryChanged}
                />
              )}
            </ErrorBoundary>
          </>
        )}
      </main>
    </div>
  );
}
