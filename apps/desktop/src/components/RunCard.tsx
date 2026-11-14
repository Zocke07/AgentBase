import type { Run } from "@agentbase/schemas";

import { clockDate, formatDuration, runOriginLabel } from "../lib/format";
import { STATUS_LABEL } from "../state/describe";

import { Status } from "./ui/Status";

/**
 * Selectable `runs`-table snapshot. For open runs, fold status overrides lagging
 * rows; duration uses row timestamps, never a clock. An automation's run is
 * named by its title, with its goal (a paragraph of instructions) beneath.
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
  const originLabel = runOriginLabel(run.origin);
  const title = run.title ?? null;

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
        <Status kind={status}>{STATUS_LABEL[status]}</Status>
        <span className="run-card__meta">
          {originLabel !== null && <span className="run-card__origin">{originLabel}</span>}
          <span className="run-card__time">{clockDate(run.created_at)}</span>
        </span>
      </span>
      {title !== null && <span className="run-card__title">{title}</span>}
      <span
        className={`run-card__goal${title !== null ? " run-card__goal--under" : ""}`}
        title={compact || title !== null ? run.goal : undefined}
      >
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
