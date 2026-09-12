

import type { ApprovalResponse } from "@agentspace/schemas";
import { useCallback, useEffect, useState } from "react";

import * as api from "../lib/api";
import { hasMore, unfinished, useRunList } from "../state/runList";
import { useRunStore } from "../state/runStore";
import { useRunStream } from "../state/useRunStream";

import { ErrorBoundary } from "./ErrorBoundary";
import { RunCard } from "./RunCard";
import { RunPanel } from "./RunPanel";

/**
 * The Runs section: pick a run, watch or replay it.
 *
 * Everything about the *run* comes from `RunPanel`, which is a pure projection
 * of the event log. What lives here is the chrome around it (the picker, the
 * connection indicator, the cancel and delete buttons) plus the one genuinely
 * two-way piece of the dashboard: answering an approval. Starting a run moved
 * to the Home screen with the redesign; the picker offers the way there.
 */

export interface RunsViewProps {
  /** Bumped by the shell whenever spend may have changed, to refresh the meter. */
  onRunChanged: () => void;
  /** Every approval waiting anywhere, so a card can say its run is stuck on one. */
  pendingApprovals: readonly ApprovalResponse[];
  /**
   * Which run is open. Owned by the shell so that it survives a section
   * switch and so the header's "approval waiting" badge can open the run it
   * names.
   */
  runId: string | null;
  onSelectRun: (runId: string | null) => void;
  /** Take the user to the Home screen, where a run is started. */
  onNewRun: () => void;
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
interface PerRun<T> {
  runId: string | null;
  value: T;
}

export function RunsView({ onRunChanged, pendingApprovals, runId, onSelectRun, onNewRun }: RunsViewProps) {
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

  // The store holds the previous run until the next one's history arrives, so
  // that a switch never passes through an empty panel. While the two disagree,
  // everything on screen that is *about* the run (the head status, the
  // approval buttons, the cancel button, the scrubber) is about the old one
  // and is withheld; the projection stays, dimmed, as the loading state.
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

  // Whether an approval can be answered is about where the viewer stands, not
  // about the fold. Scrubbed back on a finished run, the fold says "running"
  // and the approval says "pending": both true of that moment, neither a
  // reason to offer buttons. `following` is the store's word for "at the head".
  const approvalReadOnly = loading ? "loading" : finished ? "finished" : following ? null : "replay";

  // The picker's row for the selected run is a snapshot of the `runs` table;
  // the log knows more the moment an event arrives. When the two disagree the
  // row is stale, and so, if the run just ended, is the month's spend. Keyed
  // on the *head's* status, not the scrubbed view's: opening a finished run or
  // dragging the slider across its terminal event changes nothing about the
  // run, and used to refetch three endpoints anyway.
  const waitingRuns = new Set(pendingApprovals.map((approval) => approval.run_id));

  const selectedRow = runs.find((run) => run.id === runId);
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
      // Deliberately no change to the run's state: it writes `run.cancelled`
      // itself and that arrives over the stream (§2). Until then it is still
      // running, and the badge should say so, but the button has to say the
      // cancel was accepted, because a cooperative stop lands before the
      // *next* model call and the one in flight can take half a minute.
      setStopping(runId);
    } catch (failure) {
      setCancelError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setCancelling(false);
    }
  };

  // Whether the selected run is one that can be deleted: it has ended. The
  // log's word when it has one; the row's for a run with no events yet. Only
  // the complement of `cancellable` in the common case: a run that has not
  // loaded is neither.
  const settledStatus = headStatus ?? (loading ? null : (selectedRow?.status ?? null));
  const deletable = runId !== null && settledStatus !== null && !unfinished({ status: settledStatus });

  const remove = async () => {
    if (runId === null) return;
    setDeleting(true);
    setCancelError(null);
    try {
      await api.deleteRun(runId);
      // The run is gone: close it, and tell the picker and the meter. The
      // store still holds its fold until the next run is opened, which the
      // placeholder hides, clearing it here would be a second way for the
      // panel to empty, and the switch is built to never pass through one.
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

  const resolveApproval = useCallback(async (id: string, approved: boolean) => {
    await api.resolveApproval(id, approved);
    // Deliberately no local state change: the answer produces `approval.resolved`
    // and `tool.approved`/`tool.denied` in the log, and those arrive over the
    // stream like everything else. Updating the UI here would be the UI telling
    // itself what happened instead of reading it (§2).
  }, []);

  return (
    <div className="runs-view">
      <aside className="runs-view__side">
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
                />
              )}
            </ErrorBoundary>
          </>
        )}
      </main>
    </div>
  );
}
