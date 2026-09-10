import { formatCount } from "../lib/format";
import type { RunView } from "../state/reducer";

/**
 * The run's header and outcome.
 *
 * The one thing this component exists to get right: **a terminal event's
 * `summary` is a model's claim, not a record of what happened.** CLAUDE.md
 * records three separate live runs whose `run.completed` announced work the log
 * shows never occurred — a file "saved to notes.txt" by a run containing three
 * control calls and no file tool at all.
 *
 * So the summary is labelled as the supervisor's account and rendered beside a
 * count of what the log actually contains. A user reading "saved to notes.txt"
 * learns nothing; a user seeing that sentence next to "2 tool calls, 1 denied"
 * has everything they need to notice the disagreement.
 */

export interface RunSummaryProps {
  view: RunView;
}

const STATUS_LABEL: Record<RunView["status"], string> = {
  pending: "not started",
  running: "running",
  paused: "paused",
  completed: "completed",
  failed: "failed",
  cancelled: "cancelled",
};

export function RunSummary({ view }: RunSummaryProps) {
  const denied = view.denials.length;
  const sandboxed = view.denials.filter((denial) => denial.blockedBy === "sandbox").length;

  return (
    <section className="run-summary" data-testid="run-summary">
      <header className="run-summary__head">
        <span className={`status status--${view.status}`} data-testid="run-status">
          {STATUS_LABEL[view.status]}
        </span>
        <h2 className="run-summary__goal">{view.goal ?? "No goal recorded yet"}</h2>
      </header>

      <dl className="run-summary__facts">
        <div>
          <dt>Agents</dt>
          <dd data-testid="fact-agents">{view.agentOrder.length}</dd>
        </div>
        <div>
          <dt>Tool calls</dt>
          {/* `tool.called`, not `tool.requested`: what executed, not what was asked. */}
          <dd data-testid="fact-tool-calls">{view.toolCalls.length}</dd>
        </div>
        <div>
          <dt>Denied</dt>
          <dd data-testid="fact-denied">
            {denied}
            {sandboxed > 0 && <span className="run-summary__sandboxed"> ({sandboxed} sandbox)</span>}
          </dd>
        </div>
        <div>
          <dt>Tokens</dt>
          <dd data-testid="fact-tokens">
            {formatCount(view.inputTokens)} in / {formatCount(view.outputTokens)} out
          </dd>
        </div>
      </dl>

      {view.claim !== null && (
        <div className={`claim claim--${view.claim.kind}`} data-testid="run-claim">
          <span className="claim__label">
            {view.claim.kind === "summary"
              ? "The supervisor's account of the run"
              : "Why the run stopped"}
          </span>
          <p className="claim__text">{view.claim.text}</p>
          {view.claim.kind === "summary" && (
            <p className="claim__caveat">
              This is what the agent said it did. What it actually did is the{" "}
              {view.toolCalls.length} tool {view.toolCalls.length === 1 ? "call" : "calls"} in the
              log below.
            </p>
          )}
        </div>
      )}

      {view.unrecognised.length > 0 && (
        <p className="run-summary__unknown" role="alert" data-testid="unrecognised-events">
          This build does not recognise {view.unrecognised.length} event type
          {view.unrecognised.length === 1 ? "" : "s"}: {[...new Set(view.unrecognised)].join(", ")}.
          The dashboard is out of date with the sidecar.
        </p>
      )}
    </section>
  );
}
