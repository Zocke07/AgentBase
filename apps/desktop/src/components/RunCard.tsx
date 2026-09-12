import type { Run } from "@agentspace/schemas";

import { clockDate, formatDuration } from "../lib/format";
import { STATUS_LABEL } from "../state/describe";

/**
 * One run, as something to pick: BUILD_SPEC §5 Phase 11, "cards for runs,
 * rows for events".
 *
 * A card is a snapshot of the `runs` table: status, goal, when it started, how
 * long it took. For the run that is *open*, the table lags the log (a row
 * says "pending" for the whole of a live run), so the caller may hand in the
 * status the fold knows, and that wins. Nothing else about a run is decided
 * here; the card is a door to the run panel, which is the fold.
 *
 * Duration comes from the row's own two timestamps, never from a clock: a
 * running run shows none rather than a figure that changes on every render.
 */
export interface RunCardProps {
  run: Run;
  /** The status the open run's log reports, when it knows more than the row. */
  liveStatus?: Run["status"] | null;
  selected?: boolean;
  /** An approval is waiting on this run, wherever the viewer is looking. */
  needsApproval?: boolean;
  /** The picker's narrow variant: one line of goal, the facts on one row. */
  compact?: boolean;
  onOpen: (runId: string) => void;
}

export function RunCard({
  run,
  liveStatus = null,
  selected = false,
  needsApproval = false,
  compact = false,
  onOpen,
}: RunCardProps) {
  const status = liveStatus ?? run.status;
  // Two variants can show the same run at once (the Home screen's card and
  // the picker's row), so the test ids say which.
  const kind = compact ? "run-row" : "run-card";
  const finishedAt = run.finished_at ?? null;
  const duration =
    finishedAt === null ? null : formatDuration(Date.parse(finishedAt) - Date.parse(run.created_at));

  return (
    <button
      type="button"
      className={`run-card${compact ? " run-card--compact" : ""}${selected ? " run-card--selected" : ""}`}
      aria-current={selected ? "true" : undefined}
      onClick={() => {
        onOpen(run.id);
      }}
      data-testid={`${kind}-${run.id}`}
    >
      <span className="run-card__head">
        <span className={`status status--${status}`}>{STATUS_LABEL[status]}</span>
        {run.origin !== "ui" && <span className="run-card__origin">from {run.origin}</span>}
        <span className="run-card__time">{clockDate(run.created_at)}</span>
      </span>
      <span className="run-card__goal">{run.goal}</span>
      <span className="run-card__facts">
        {duration !== null && <span className="run-card__duration">{duration}</span>}
        {needsApproval && (
          <span className="run-card__waiting" data-testid={`${kind}-needs-approval-${run.id}`}>
            needs your approval
          </span>
        )}
      </span>
    </button>
  );
}
