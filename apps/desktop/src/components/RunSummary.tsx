import { ellipsise, formatCount, formatDuration, formatMicros } from "../lib/format";
import { STATUS_LABEL } from "../state/describe";
import type { RunView } from "../state/reducer";

/**
 * The run's header and outcome. A terminal `summary` is a model's claim, not a
 * record of what happened, so it is labelled as the supervisor's account and
 * rendered beside a count of what the log actually contains.
 */

export interface RunSummaryProps {
  view: RunView;
}

export function RunSummary({ view }: RunSummaryProps) {
  const denied = view.denials.length;
  const sandboxed = view.denials.filter((denial) => denial.blockedBy === "sandbox").length;
  // From the log's own stamps, so a replay shows the duration the live view
  // did. A live run's figure grows as events arrive, which is the same rule.
  const duration =
    view.startedTs !== null && view.latestTs !== null
      ? formatDuration(Date.parse(view.latestTs) - Date.parse(view.startedTs))
      : null;

  return (
    <section className="run-summary" data-testid="run-summary">
      <header className="run-summary__head">
        <span className={`status status--${view.status}`} data-testid="run-status">
          {STATUS_LABEL[view.status]}
        </span>
        <h2 className="run-summary__goal">{view.goal ?? "No goal recorded yet"}</h2>
        {view.origin !== null && (
          // A run started from Discord is the same fold; the viewer needs to know who started it.
          <p className="run-summary__origin" data-testid="run-origin">
            Started from {view.origin.channel} by {view.origin.identity ?? "an unknown identity"}
            {view.origin.displayName !== null && ` (${view.origin.displayName})`}
          </p>
        )}
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
        {duration !== null && (
          <div>
            <dt>Duration</dt>
            <dd data-testid="fact-duration">{duration}</dd>
          </div>
        )}
        <div>
          <dt>Cost</dt>
          {/* Summed from the ledger's figure on each `llm.response`: the same
              integer the budget meter is built from, never a float here. */}
          <dd data-testid="fact-cost">{formatMicros(view.costMicros)}</dd>
        </div>
        <div>
          <dt>Errors</dt>
          {/* `llm.error` and `tool.error`. Folded from the start, rendered
              nowhere until now: an agent that hit five provider errors in
              a row looked exactly like an agent that was thinking. */}
          <dd data-testid="fact-errors">{view.errors.length}</dd>
        </div>
      </dl>

      {view.budgetExceeded && (
        <p className="run-summary__cap" role="alert" data-testid="budget-exceeded">
          This run hit the monthly cap. Nothing past this point called a model.
        </p>
      )}

      {view.errors.length > 0 && (
        <ul className="run-summary__errors" data-testid="run-errors">
          {view.errors.map((error) => (
            <li key={error.seq} className={`run-summary__error run-summary__error--${error.kind}`}>
              <span className="run-summary__error-who">
                {error.agent ?? "run"} · {error.kind === "llm" ? "model" : "tool"}
              </span>
              <span className="run-summary__error-text">{ellipsise(error.message, 160)}</span>
            </li>
          ))}
        </ul>
      )}

      {(view.knowledge.length > 0 || view.knowledgeExclusions.length > 0) && (
        <details className="run-summary__context" data-testid="run-context">
          <summary>
            Retrieved context: {view.knowledge.length} excerpt
            {view.knowledge.length === 1 ? "" : "s"}, about{" "}
            {formatCount(
              view.knowledge.reduce((total, hit) => total + (hit.estimatedTokens ?? 0), 0),
            )}{" "}
            tokens
            {view.knowledgeExclusions.length > 0 &&
              `, ${String(view.knowledgeExclusions.length)} excluded by you`}
          </summary>
          <p className="run-summary__context-note">
            {/* The excerpts are what `run.started` recorded for the supervisor;
                each worker's own retrieval is in its `llm.request` message. */}
            These excerpts were sent to the supervisor with the goal as untrusted reference
            material. Workers retrieved their own for each handoff; see their model requests
            in the log.
          </p>
          <ul className="run-summary__excerpts">
            {view.knowledge.map((hit) => (
              <li key={hit.citation}>
                <code>{hit.citation}</code>
                <small>
                  {hit.score !== null && `${String(Math.round(hit.score * 100))}% relevance`}
                  {hit.estimatedTokens !== null && ` · ${String(hit.estimatedTokens)} tokens`}
                  {hit.matchedTerms.length > 0 && ` · matched ${hit.matchedTerms.join(", ")}`}
                  {hit.reasons.length > 0 && ` · ${hit.reasons.join(" · ")}`}
                </small>
              </li>
            ))}
            {view.knowledgeExclusions.map((citation) => (
              <li key={`excluded:${citation}`} className="run-summary__excluded">
                <code>{citation}</code>
                <small>excluded before the run started</small>
              </li>
            ))}
          </ul>
        </details>
      )}

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
          {view.memoryPath !== null && (
            <p className="claim__memory" data-testid="run-memory">
              Saved as a proposed memory at <code>{view.memoryPath}</code>. Approve it in the
              Knowledge section's inbox before later runs can retrieve it.
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
