import { useEffect, useRef, useState } from "react";

import { awaitingPerson, type ApprovalRecord } from "../state/reducer";

/**
 * The approval gate's other half, as a docked panel rather than the modal
 * §5 Phase 7 names (a recorded deviation): a person needs the log and the
 * graph behind the question to answer it, and a modal trapped the scrubber.
 *
 * The sentence is the backend's (`approval.requested.prompt`, from the
 * resolved call); only the buttons are ours. The run's decision history is
 * shown too, because a supervisor will ask the same question twice. The
 * question and history are a projection of the log; whether it can be
 * answered depends on where the viewer stands, so the action row is
 * transport and sits outside the identity comparison.
 */

export interface ApprovalPanelProps {
  /** Every approval this run has raised, oldest first. */
  approvals: readonly ApprovalRecord[];
  /** Resolve one. Rejects if somebody else already answered it (a 409). */
  onResolve: (id: string, approved: boolean) => Promise<void>;
  /** Why an answer cannot be given here (`"finished"`, `"replay"`), or null when it can. */
  readOnly: "finished" | "replay" | "loading" | null;
}

export function ApprovalPanel({ approvals, onResolve, readOnly }: ApprovalPanelProps) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<{ id: string; message: string } | null>(null);
  const denyButton = useRef<HTMLButtonElement>(null);

  const pending = approvals.filter(awaitingPerson);
  const settled = approvals.filter((approval) => approval.status !== "pending");
  const current = pending[0];

  // Focus the safer answer when a question appears, so a keyboard user is not
  // left somewhere behind it. Keyed on the id so a second question refocuses.
  useEffect(() => {
    if (current !== undefined && readOnly === null) denyButton.current?.focus();
  }, [current?.id, readOnly]); // eslint-disable-line react-hooks/exhaustive-deps

  if (current === undefined) {
    return null;
  }

  const answer = async (approved: boolean) => {
    setBusy(current.id);
    setError(null);
    try {
      await onResolve(current.id, approved);
    } catch (failure) {
      setError({ id: current.id, message: failure instanceof Error ? failure.message : String(failure) });
    } finally {
      setBusy(null);
    }
  };

  return (
    <section
      className={`approval approval--${current.risk}`}
      role="region"
      aria-live="assertive"
      aria-labelledby="approval-prompt"
      data-testid="approval-panel"
    >
      {/* Pure function of the log. Compared live against replay. */}
      <div className="approval__question" data-testid="approval-question">
        <header className="approval__header">
          <span className={`risk risk--${current.risk}`} data-testid="approval-risk">
            {current.risk} risk
          </span>
          <span className="approval__title">Approval needed</span>
          {pending.length > 1 && (
            <span className="approval__queue">{pending.length - 1} more waiting</span>
          )}
        </header>

        {/* Verbatim from the event log: see the note above. */}
        <p className="approval__prompt" id="approval-prompt" data-testid="approval-prompt">
          {current.prompt}
        </p>

        <p className="approval__agent">
          Requested by <strong>{current.agent}</strong> · {current.tool}
        </p>

        {settled.length > 0 && (
          <details className="approval__history" data-testid="approval-history">
            <summary>
              Earlier in this run: {settled.length}{" "}
              {settled.length === 1 ? "decision" : "decisions"}
            </summary>
            <ul>
              {settled.map((approval) => (
                <li key={approval.id} className={`approval-history__item approval-history__item--${approval.status}`}>
                  <span className="approval-history__status">{approval.status}</span>
                  <span className="approval-history__agent">{approval.agent}</span>
                  <span className="approval-history__tool">{approval.tool}</span>
                  {approval.automatic && (
                    <span className="approval-history__auto">
                      {/* A policy only ever says yes; an automatic no is the
                          person's own earlier answer, repeated for the run. */}
                      {approval.status === "denied" ? "by your earlier answer" : "by policy"}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </details>
        )}
      </div>

      {/* Transport: depends on where the viewer stands, not on the log. */}
      <div className="approval__actions" data-testid="approval-actions">
        {error !== null && error.id === current.id && (
          <p className="approval__error" role="alert">
            {error.message}
          </p>
        )}

        {readOnly === "finished" && (
          <p className="approval__readonly">
            This run has already finished. Its approvals can be read, not answered.
          </p>
        )}
        {readOnly === "replay" && (
          <p className="approval__readonly">
            You are looking at an earlier point in this run. Jump to the end to answer.
          </p>
        )}
        {readOnly === null && (
          <div className="approval__buttons">
            <button
              ref={denyButton}
              type="button"
              className="button button--deny"
              disabled={busy !== null}
              onClick={() => void answer(false)}
            >
              Deny
            </button>
            <button
              type="button"
              className="button button--allow"
              disabled={busy !== null}
              onClick={() => void answer(true)}
            >
              Allow
            </button>
          </div>
        )}

        <p className="approval__note">
          Denying stops this call, not the run. The supervisor may delegate the
          work again and ask a second time.
        </p>
      </div>
    </section>
  );
}
