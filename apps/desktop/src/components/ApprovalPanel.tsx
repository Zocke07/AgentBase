import { useEffect, useRef, useState } from "react";

import { awaitingPerson, type ApprovalRecord } from "../state/reducer";

/**
 * The approval gate's other half — §5 Phase 7's "Approval dialogs surfaced
 * modally with the human-legible text from Phase 6" — as a docked panel.
 *
 * **Docked, not modal, and that is a recorded deviation from the spec.** The
 * first version was a full-window modal, and it had the problem a modal
 * always has here: the question is "may this agent overwrite notes.txt?", and
 * the thing a person needs in order to answer is the log and the graph
 * *behind* the backdrop. It also trapped the user — the backdrop covered the
 * scrubber and the tabs, so dragging the replay slider into an approval span
 * of a finished run left no way to drag it back out. This panel sits above
 * the log, is impossible to miss, and hides nothing.
 *
 * **The sentence is the backend's; only the buttons are ours.** The prompt
 * rendered here is `approval.requested.prompt`, composed by the sidecar from
 * the *resolved* call and written into the event log. A panel that built its
 * own wording from the raw arguments could describe a different call from the
 * one about to run, which is where a confused-deputy bug lives — and it would
 * put the UI's account of the run at odds with the log's, which §2 rules out.
 *
 * **It shows the history, not just what is outstanding.** Watched live in Phase
 * 6: a user denied a write, the worker gave up, the supervisor spawned a second
 * copy of the same agent, and it asked for the identical write again. A panel
 * that only ever renders the current question makes those look like one event
 * and gives the user no way to see they are being asked twice.
 *
 * **Two halves, on the two sides of the identity boundary.** The question and
 * its history are a pure function of the log and render byte-identically live
 * and replayed — `replayIdentity.test.tsx` compares them at every position.
 * Whether it can be *answered* is a fact about where the viewer is standing:
 * live at the head, yes; scrubbed back on the same run, no. So the action row
 * is transport, like the scrubber, and is excluded from the comparison for the
 * same honest reason.
 */

export interface ApprovalPanelProps {
  /** Every approval this run has raised, oldest first. */
  approvals: readonly ApprovalRecord[];
  /** Resolve one. Rejects if somebody else already answered it (a 409). */
  onResolve: (id: string, approved: boolean) => Promise<void>;
  /**
   * Why an answer cannot be given here, or null when it can.
   *
   * `"finished"`: the run is over. `"replay"`: the viewer has scrubbed back
   * from the head — the question was, or will be, answered at the head.
   */
  readOnly: "finished" | "replay" | null;
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

        {/* Verbatim from the event log — see the note above. */}
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
                  {approval.automatic && <span className="approval-history__auto">by policy</span>}
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
