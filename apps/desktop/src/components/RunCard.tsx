import type { Run } from "@agentbase/schemas";

import { clockDate, formatDuration } from "../lib/format";
import { STATUS_LABEL } from "../state/describe";

/**
 * Selectable `runs`-table snapshot. For open runs, fold status overrides lagging
 * rows; duration uses row timestamps, never a clock.
 */
export interface RunCardProps {
  run: Run;
  /** Open-run log status when newer than row. */
  liveStatus?: Run["status"] | null;
  selected?: boolean;
  /** Approval waiting on this run, regardless of current view. */
  needsApproval?: boolean;
  /** Narrow picker: single-line goal and facts row. */
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
  // Home card and picker row can coexist; differentiate test IDs.
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
        <span className="run-card__meta">
          {run.origin !== "ui" && <span className="run-card__origin">from {run.origin}</span>}
          <span className="run-card__time">{clockDate(run.created_at)}</span>
        </span>
      </span>
      <span className="run-card__goal" title={compact ? run.goal : undefined}>
        {run.goal}
      </span>
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
