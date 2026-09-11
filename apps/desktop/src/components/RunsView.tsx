

import type { Run } from "@agentspace/schemas";
import { useCallback, useEffect, useState } from "react";

import * as api from "../lib/api";
import { clockTime } from "../lib/format";
import { useRunStore } from "../state/runStore";
import { useFetched } from "../state/useFetched";
import { useRunStream } from "../state/useRunStream";

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
}

function connectionLabel(connection: ReturnType<typeof useRunStore.getState>["connection"]): string {
  switch (connection.kind) {
    case "idle":
      return "no run selected";
    case "connecting":
      return "connecting…";
    case "live":
      return "live";
    case "closed":
      return "run finished — stream closed";
    case "error":
      return connection.message;
  }
}

const NO_RUNS: Run[] = [];

export function RunsView({ onRunChanged }: RunsViewProps) {
  const [runId, setRunId] = useState<string | null>(null);
  const [goal, setGoal] = useState("");
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);
  const [selectedAgent, setSelectedAgent] = useState<string | null>(null);

  const view = useRunStore((state) => state.view);
  const events = useRunStore((state) => state.events);
  const cursor = useRunStore((state) => state.cursor);
  const following = useRunStore((state) => state.following);
  const connection = useRunStore((state) => state.connection);
  const setCursor = useRunStore((state) => state.setCursor);

  useRunStream(runId);

  const loadRuns = useCallback(() => api.listRuns(), []);
  const runList = useFetched(loadRuns, NO_RUNS);
  const runs = runList.data;

  // A run that has just reached a terminal event is one whose spend is final
  // and whose row in the picker is out of date, so this is the moment both are
  // worth re-reading. Keyed on the status rather than on a timer.
  const finished =
    view.status === "completed" || view.status === "failed" || view.status === "cancelled";

  // Whether an approval can be answered is about where the viewer stands, not
  // about the fold. Scrubbed back on a finished run, the fold says "running"
  // and the approval says "pending" — both true of that moment, neither a
  // reason to offer buttons. `following` is the store's word for "at the head".
  const approvalReadOnly = finished ? "finished" : following ? null : "replay";

  useEffect(() => {
    if (finished) {
      onRunChanged();
      runList.reload();
    }
    // `runList.reload` is stable; depending on the whole object would refire
    // this on every fetch it triggers.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [finished, onRunChanged]);

  const start = async () => {
    const trimmed = goal.trim();
    if (trimmed === "") return;

    setStarting(true);
    setStartError(null);
    try {
      const run = await api.createRun(trimmed);
      setGoal("");
      setSelectedAgent(null);
      setRunId(run.id);
      runList.reload();
    } catch (failure) {
      setStartError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setStarting(false);
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
          <button
            type="submit"
            className="button button--primary"
            disabled={starting || goal.trim() === ""}
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
                  setSelectedAgent(null);
                  setRunId(run.id);
                }}
              >
                <span className={`status status--${run.status}`}>{run.status}</span>
                <span className="run-list__goal">{run.goal}</span>
                <span className="run-list__time">{clockTime(run.created_at)}</span>
              </button>
            </li>
          ))}
          {runs.length === 0 && <li className="run-list__empty">No runs yet.</li>}
        </ul>
      </aside>

      <main className="runs-view__main">
        {runId === null ? (
          <p className="runs-view__placeholder">
            Start a run, or pick one from the list to replay it.
          </p>
        ) : (
          <>
            <p className="runs-view__connection" data-testid="connection-status">
              {connectionLabel(connection)}
            </p>
            <RunPanel
              view={view}
              events={events}
              cursor={cursor}
              selectedAgent={selectedAgent}
              onSelectAgent={setSelectedAgent}
              onCursorChange={setCursor}
              approvalReadOnly={approvalReadOnly}
              onResolveApproval={resolveApproval}
            />
          </>
        )}
      </main>
    </div>
  );
}
