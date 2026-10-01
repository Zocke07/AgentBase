

import type { ApprovalResponse, Event } from "@agentbase/schemas";
import { useCallback, useEffect, useRef, useState } from "react";

import * as api from "../lib/api";
import type { RunOrigin } from "../lib/api";
import { captureText } from "../state/describe";
import { hasMore, unfinished, useRunList } from "../state/runList";
import { useRunStore } from "../state/runStore";
import { useRunStream } from "../state/useRunStream";
import { useStoredSize } from "../state/useStoredSize";

import { ErrorBoundary } from "./ErrorBoundary";
import { RunCard } from "./RunCard";
import { RunPanel } from "./RunPanel";
import { Skeleton } from "./Skeleton";
import { Splitter } from "./Splitter";

/**
 * Runs picker, live/replay shell, connection status, cancel/delete actions, and
 * approval answers. `RunPanel` owns run rendering.
 */

export interface RunsViewProps {
  /** Shell bump after possible spend changes, refreshing the meter. */
  onRunChanged: () => void;
  /** All pending approvals, so cards identify blocked runs. */
  pendingApprovals: readonly ApprovalResponse[];
  /** Shell-owned open run, retained across section switches. */
  runId: string | null;
  onSelectRun: (runId: string | null) => void;
  /** Navigate Home to start a run. */
  onNewRun: () => void;
  /** Open cited Knowledge note. */
  onOpenNote?: ((path: string, heading: string | null) => void) | undefined;
  /** Open a run memory beside Knowledge inbox. */
  onOpenMemory?: ((path: string) => void) | undefined;
  /** Run memory status changed; reload inbox. */
  onMemoryChanged?: (() => void) | undefined;
}

function connectionLabel(
  connection: ReturnType<typeof useRunStore.getState>["connection"],
  gaps: number,
): string {
  // Surface any violation of server no-gap/no-repeat event delivery.
  const suffix = gaps === 0 ? "" : ` · ${String(gaps)} step${gaps === 1 ? "" : "s"} missing from the record`;
  switch (connection.kind) {
    case "idle":
      return "No task selected";
    case "connecting":
      return `Connecting…${suffix}`;
    case "live":
      return `Live: updates as it happens${suffix}`;
    case "closed":
      return `Finished${suffix}`;
    case "error":
      return `${connection.message}${suffix}`;
  }
}

/** State tagged to one run and empty for all others. */
/** Run-list width, starting from CSS 19rem, and bounds. */
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
  /** Run with accepted cancellation; it stops at its next check. */
  const [stopping, setStopping] = useState<string | null>(null);
  // Run-tagged selection and cancellation errors clear naturally on switching.
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

  // Retain prior projection, dimmed, until next run history arrives.
  const loading = runId !== null && loadedRunId !== runId;

  const runs = useRunList((state) => state.runs);
  const runsLoading = useRunList((state) => state.loading);
  const runsLoaded = useRunList((state) => state.loaded);
  const runsError = useRunList((state) => state.error);
  const limit = useRunList((state) => state.limit);
  const reloadRuns = useRunList((state) => state.load);
  const ensureRuns = useRunList((state) => state.ensure);
  const loadMore = useRunList((state) => state.loadMore);
  const origin = useRunList((state) => state.origin);
  const setOrigin = useRunList((state) => state.setOrigin);

  useEffect(() => {
    ensureRuns();
  }, [ensureRuns]);

  const finished =
    view.status === "completed" || view.status === "failed" || view.status === "cancelled";

  // Approval actions depend on viewer position; scrubbed pending is historical.
  const approvalReadOnly = loading ? "loading" : finished ? "finished" : following ? null : "replay";

  // Refetch stale rows from head status, not scrubbed history, avoiding replay
  // refetches across terminal events.
  const waitingRuns = new Set(pendingApprovals.map((approval) => approval.run_id));

  const selectedRow = runs.find((run) => run.id === runId);
  // Tag result to its run so switch clears it.
  const [captureNotice, setCaptureNotice] = useState<{ runId: string; text: string } | null>(null);
  // Viewer-set width; CSS applies until then.
  const [listWidth, setListWidth] = useStoredSize("runs.list");
  const side = useRef<HTMLElement>(null);

  // User note stays outside automatic run memories to avoid app overwrites.
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
      // Head status avoids looping while table writes lag the log.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [headStatus, onRunChanged]);

  // Stop eligibility follows nonterminal log status, not stream connection.
  const cancellable = runId !== null && headStatus !== null && unfinished({ status: headStatus });

  const cancel = async () => {
    if (runId === null) return;
    setCancelling(true);
    setCancelError(null);
    try {
      await api.cancelRun(runId);
      // Streamed `run.cancelled` changes state; accepted cancellation may wait
      // for an in-flight model call.
      setStopping(runId);
    } catch (failure) {
      setCancelError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setCancelling(false);
    }
  };

  // Delete only ended runs; prefer log status then table row.
  const settledStatus = headStatus ?? (loading ? null : (selectedRow?.status ?? null));
  const deletable = runId !== null && settledStatus !== null && !unfinished({ status: settledStatus });

  const remove = async () => {
    if (runId === null) return;
    setDeleting(true);
    setCancelError(null);
    try {
      await api.deleteRun(runId);
      // Close deleted run and refresh picker/meter; placeholder hides retained fold.
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
    // Stream events, not local state, apply the answer (§2).
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
        <label className="runs-view__filter">
          <span className="sr-only">Show</span>
          <select
            value={origin ?? ""}
            aria-label="Which runs to list"
            data-testid="runs-origin"
            onChange={(changed) => {
              const chosen = changed.target.value;
              setOrigin(chosen === "" ? undefined : (chosen as RunOrigin));
            }}
          >
            <option value="">All runs</option>
            <option value="ui">Started by you</option>
            <option value="automation">Run now</option>
            <option value="schedule">Scheduled</option>
            <option value="discord">From Discord</option>
          </select>
        </label>

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
          {runs.length === 0 && (
            <li className="run-list__empty">
              {!runsLoaded ? (
                <Skeleton label="Loading your runs" cards={3} />
              ) : origin === undefined ? (
                "No runs yet. Start one from Home."
              ) : (
                "No runs of this kind yet."
              )}
            </li>
          )}
        </ul>
      </aside>

      <section className="runs-view__main">
        {runId === null ? (
          <p className="runs-view__placeholder">Pick a run to watch it or replay it.</p>
        ) : (
          <>
            <div className="runs-view__strip">
              <p
                className={`runs-view__connection runs-view__connection--${loading ? "loading" : connection.kind}`}
                data-testid="connection-status"
              >
                {loading ? "Loading…" : connectionLabel(connection, gaps)}
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
                <div className="runs-view__loading">
                  <Skeleton label="Opening the run" title lines={4} />
                </div>
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
      </section>
    </div>
  );
}
