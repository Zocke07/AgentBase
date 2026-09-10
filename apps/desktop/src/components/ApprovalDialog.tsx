import { useState } from "react";

import type { ApprovalRecord } from "../state/reducer";

/**
 * The approval gate's other half — §5 Phase 7's "Approval dialogs surfaced
 * modally with the human-legible text from Phase 6".
 *
 * **The sentence is the backend's; only the buttons are ours.** The prompt
 * rendered here is `approval.requested.prompt`, composed by the sidecar from
 * the *resolved* call and written into the event log. A dialog that built its
 * own wording from the raw arguments could describe a different call from the
 * one about to run, which is where a confused-deputy bug lives — and it would
 * put the UI's account of the run at odds with the log's, which §2 rules out.
 *
 * **It shows the history, not just what is outstanding.** Watched live in Phase
 * 6: a user denied a write, the worker gave up, the supervisor spawned a second
 * copy of the same agent, and it asked for the identical write again. A dialog
 * that only ever renders the current question makes those look like one event
 * and gives the user no way to see they are being asked twice.
 */

export interface ApprovalDialogProps {
  /** Every approval this run has raised, oldest first. */
  approvals: readonly ApprovalRecord[];
  /** Resolve one. Rejects if somebody else already answered it (a 409). */
  onResolve: (id: string, approved: boolean) => Promise<void>;
  /** True while the run is replayed rather than live — answers are impossible. */
  readOnly: boolean;
}

export function ApprovalDialog({ approvals, onResolve, readOnly }: ApprovalDialogProps) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const pending = approvals.filter((approval) => approval.status === "pending");
  const settled = approvals.filter((approval) => approval.status !== "pending");
  const current = pending[0];

  if (current === undefined) {
    return null;
  }

  const answer = async (approved: boolean) => {
    setBusy(current.id);
    setError(null);
    try {
      await onResolve(current.id, approved);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="modal-backdrop" role="presentation">
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="approval-prompt"
        data-testid="approval-dialog"
      >
        <header className="modal__header">
          <span className={`risk risk--${current.risk}`} data-testid="approval-risk">
            {current.risk} risk
          </span>
          {pending.length > 1 && (
            <span className="modal__queue">{pending.length - 1} more waiting</span>
          )}
        </header>

        {/* Verbatim from the event log — see the note above. */}
        <p className="modal__prompt" id="approval-prompt" data-testid="approval-prompt">
          {current.prompt}
        </p>

        <p className="modal__agent">
          Requested by <strong>{current.agent}</strong> · {current.tool}
        </p>

        {settled.length > 0 && (
          <details className="modal__history" data-testid="approval-history">
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
                  {approval.automatic && <span className="approval-history__auto">by policy</span>}
                </li>
              ))}
            </ul>
          </details>
        )}

        {error !== null && (
          <p className="modal__error" role="alert">
            {error}
          </p>
        )}

        {readOnly ? (
          <p className="modal__readonly">
            This run has already finished. Its approvals can be read, not answered.
          </p>
        ) : (
          <div className="modal__actions">
            <button
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

        <p className="modal__note">
          Denying stops this call, not the run. The supervisor may delegate the
          work again and ask a second time.
        </p>
      </div>
    </div>
  );
}
