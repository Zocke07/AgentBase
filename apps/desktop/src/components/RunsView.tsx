

import type { ApprovalResponse, Run } from "@agentspace/schemas";
import { useCallback, useEffect, useState } from "react";

import * as api from "../lib/api";
import { clockDate } from "../lib/format";
import { useRunStore } from "../state/runStore";
import { useFetched } from "../state/useFetched";
import { useRunStream } from "../state/useRunStream";

import { ErrorBoundary } from "./ErrorBoundary";
import { RunPanel } from "./RunPanel";

/**
 * The run tab: start a run, pick a past one, watch or replay it.
 *
 * Everything about the *run* comes from `RunPanel`, which is a pure projection
 * of the event log. What lives here is the chrome around it — the picker, the
 * goal box, the connection indicator — plus the one genuinely two-way piece of
 * the dashboard: answering an approval.
 */

export interface RunsViewProps {
  /** Bumped by the shell whenever spend may have changed, to refresh the meter. */
  onRunChanged: () => void;
  /** Why a run started now would be refused, or null when one can start. */
  blocker: string | null;
  /** Every approval waiting anywhere, so a row can say its run is stuck on one. */
  pendingApprovals: readonly ApprovalResponse[];
  /**
   * Which run is open. Owned by the shell so that it survives a tab switch
   * and so the header's "approval waiting" badge can open the run it names.
   */
  runId: string | null;
  onSelectRun: (runId: string | null) => void;
  /** Take the user to the settings tab — offered beside a pre-flight refusal. */
  onOpenSettings: () => void;
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
      return `run finished — stream closed${suffix}`;
    case "error":
      return `${connection.message}${suffix}`;
  }
}

const NO_RUNS: Run[] = [];

const TERMINAL_STATUSES: ReadonlySet<Run["status"]> = new Set(["completed", "failed", "cancelled"]);

/** How many runs the picker asks for at a time. */
const PAGE = 50;

/** How often to re-read the picker and the meter while some run is unfinished. */
const BACKGROUND_REFRESH_MS = 5_000;

/** A piece of state that belongs to one run: read as empty for any other. */
interface PerRun<T> {
  runId: string | null;
  value: T;
}

export function RunsView({
  onRunChanged,
  blocker,
  pendingApprovals,
  runId,
  onSelectRun,
  onOpenSettings,
}: RunsViewProps) {
  const [limit, setLimit] = useState(PAGE);
  const [goal, setGoal] = useState("");
  const [starting, setStarting] = useState(false);
  const [demoError, setDemoError] = useState<string | null>(null);
  const [startError, setStartError] = useState<string | null>(null);
  const [cancelling, setCancelling] = useState(false);
  /** The run the sidecar accepted a cancel for; it stops at its next check. */
  const [stopping, setStopping] = useState<string | null>(null);
  // State that is about one run — the selected agent, a failed cancel's
  // message — is tagged with the run it belongs to and reads as empty for any
  // other, so switching runs needs no reset and no effect.
  const [selection, setSelection] = useState<PerRun<string | null>>({ runId: null, value: null });
  const [cancelFailure, setCancelFailure] = useState<PerRun<string | null>>({ runId: null, value: null });
  const selectedAgent = selection.runId === runId ? selection.value : null;
  const cancelError = cancelFailure.runId === runId ? cancelFailure.value : null;
  const setSelectedAgent = (value: string | null) => {
    setSelection({ runId, value });
  };
  const setCancelError = (value: string | null) => {
    setCancelFailure({ runId, value });
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
  // everything on screen that is *about* the run — the head status, the
  // approval buttons, the cancel button, the scrubber — is about the old one
  // and is withheld; the projection stays, dimmed, as the loading state.
  const loading = runId !== null && loadedRunId !== runId;

  const loadRuns = useCallback(() => api.listRuns(limit), [limit]);
  const runList = useFetched(loadRuns, NO_RUNS);
  const runs = runList.data;

  const finished =
    view.status === "completed" || view.status === "failed" || view.status === "cancelled";

  // Whether an approval can be answered is about where the viewer stands, not
  // about the fold. Scrubbed back on a finished run, the fold says "running"
  // and the approval says "pending" — both true of that moment, neither a
  // reason to offer buttons. `following` is the store's word for "at the head".
  const approvalReadOnly = loading ? "loading" : finished ? "finished" : following ? null : "replay";

  // The picker's row for the selected run is a snapshot of the `runs` table;
  // the log knows more the moment an event arrives. When the two disagree the
  // row is stale, and so — if the run just ended — is the month's spend. Keyed
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
      runList.reload();
    }
    // Deliberately keyed on the head status alone: a row still stale after the
    // reload (the table lags the log by a write) must not loop until it agrees.
    // `runList.reload` is stable; depending on the whole object would refire
    // this on every fetch it triggers.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [headStatus, onRunChanged]);

  // Runs that happen elsewhere. The stream covers the selected run; a run
  // started from Discord, or left going in the background, only reaches the
  // picker — and only moves the meter — if something re-reads the table. A
  // light poll while any listed run is unfinished, and nothing at all once
  // they all are: an idle window makes no requests.
  const { reload } = runList;
  const anyUnfinished = runs.some((run) => !TERMINAL_STATUSES.has(run.status));
  useEffect(() => {
    if (!anyUnfinished) return;
    const timer = setInterval(() => {
      reload();
      onRunChanged();
    }, BACKGROUND_REFRESH_MS);
    return () => {
      clearInterval(timer);
    };
  }, [anyUnfinished, reload, onRunChanged]);

  // And when the window comes back into view: a setting changed from a browser
  // tab, or a run that ended while this window was behind something.
  useEffect(() => {
    const onVisible = () => {
      if (!document.hidden) {
        reload();
        onRunChanged();
      }
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [reload, onRunChanged]);

  const start = async () => {
    const trimmed = goal.trim();
    if (trimmed === "" || blocker !== null) return;

    setStarting(true);
    setStartError(null);
    try {
      const run = await api.createRun(trimmed);
      setGoal("");
      onSelectRun(run.id);
      runList.reload();
    } catch (failure) {
      setStartError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setStarting(false);
    }
  };

  // Whether the selected run is one that can still be stopped: the log says
  // it has not ended. Not the connection — a run whose stream is between
  // reconnects is still a run.
  const cancellable =
    runId !== null && headStatus !== null && !TERMINAL_STATUSES.has(headStatus);

  const cancel = async () => {
    if (runId === null) return;
    setCancelling(true);
    setCancelError(null);
    try {
      await api.cancelRun(runId);
      // Deliberately no change to the run's state: it writes `run.cancelled`
      // itself and that arrives over the stream (§2). Until then it is still
      // running, and the badge should say so — but the button has to say the
      // cancel was accepted, because a cooperative stop lands before the
      // *next* model call and the one in flight can take half a minute.
      setStopping(runId);
    } catch (failure) {
      setCancelError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setCancelling(false);
    }
  };

  // The scripted run: twenty events, no model, no key. It is what the graph
  // can show before any provider is configured, and its payloads speak the
  // reducer's dialect so it renders like a real one.
  const demo = async () => {
    setDemoError(null);
    try {
      const run = await api.startDebugRun();
      onSelectRun(run.id);
      runList.reload();
    } catch (failure) {
      setDemoError(failure instanceof Error ? failure.message : String(failure));
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
        <form
          className="new-run"
          onSubmit={(submitted) => {
            submitted.preventDefault();
            void start();
          }}
        >
          <label>
            <span>New run</span>
            <textarea
              rows={3}
              value={goal}
              placeholder="What should the agents do?"
              onChange={(changed) => {
                setGoal(changed.target.value);
              }}
              data-testid="goal-input"
            />
          </label>
          {blocker !== null && (
            <div className="new-run__preflight" role="status" data-testid="preflight">
              <p>{blocker}</p>
              <div className="new-run__preflight-actions">
                <button type="button" className="button button--small" onClick={onOpenSettings}>
                  Open settings
                </button>
                <button type="button" className="button button--small" onClick={() => void demo()}>
                  Try a demo run
                </button>
              </div>
              {demoError !== null && <p className="runs-view__strip-error">{demoError}</p>}
            </div>
          )}
          <button
            type="submit"
            className="button button--primary"
            disabled={starting || goal.trim() === "" || blocker !== null}
          >
            {starting ? "Starting…" : "Start run"}
          </button>
        </form>

        {(startError ?? runList.error) !== null && (
          <p className="runs-view__error" role="alert">
            {startError ?? runList.error}
          </p>
        )}

        <h3 className="runs-view__heading">Runs</h3>
        <ul className="run-list" data-testid="run-list">
          {runs.map((run) => (
            <li key={run.id}>
              <button
                type="button"
                className={`run-list__item${run.id === runId ? " run-list__item--selected" : ""}`}
                onClick={() => {
                  setStartError(null);
                  onSelectRun(run.id);
                }}
              >
                {/* The log is the authority on the selected run; the row is a
                    snapshot that says "pending" for the whole of a live run. */}
                {run.id === runId && headStatus !== null ? (
                  <span className={`status status--${headStatus}`}>{headStatus}</span>
                ) : (
                  <span className={`status status--${run.status}`}>{run.status}</span>
                )}
                <span className="run-list__goal">{run.goal}</span>
                <span className="run-list__time">{clockDate(run.created_at)}</span>
                {waitingRuns.has(run.id) && (
                  <span
                    className="run-list__waiting"
                    data-testid={`run-needs-approval-${run.id}`}
                  >
                    needs your approval
                  </span>
                )}
              </button>
            </li>
          ))}
          {runs.length >= limit && (
            <li className="run-list__more">
              <button
                type="button"
                className="button button--small"
                onClick={() => {
                  setLimit((current) => current + PAGE);
                }}
              >
                Load more
              </button>
            </li>
          )}
          {runs.length === 0 && (
            <li className="run-list__empty">{runList.loading ? "Loading…" : "No runs yet."}</li>
          )}
        </ul>
      </aside>

      <main className="runs-view__main">
        {runId === null ? (
          <p className="runs-view__placeholder">
            Start a run, or pick one from the list to replay it.
          </p>
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
            </div>
            {/* Reset on the run so a panel that threw on one run does not
                stay in its fallback when another is opened — without
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
