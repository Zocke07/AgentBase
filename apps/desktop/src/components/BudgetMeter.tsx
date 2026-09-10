import type { BudgetResponse } from "@agentspace/schemas";

/**
 * Month-to-date spend against the cap — §5 Phase 7's budget meter.
 *
 * This is the one panel that is *not* a projection of a run's event log, and
 * deliberately so: the cap is a workspace fact spanning every run in the month,
 * so it comes from `GET /budget`. It sits outside the run view for that reason,
 * and the replay-identity test excludes it — a replayed run must render like the
 * live one did, and the month's spend has legitimately moved on since.
 *
 * The display strings come from the backend (`format_micros`), so the rounding
 * rule lives in one place. §5 Phase 3 is explicit that money is integer micros
 * and never a float; formatting it here in JavaScript would put a second,
 * floating-point opinion on the screen.
 */

export interface BudgetMeterProps {
  budget: BudgetResponse | null;
}

export function BudgetMeter({ budget }: BudgetMeterProps) {
  if (budget === null) {
    return (
      <div className="budget budget--unknown" data-testid="budget-meter">
        <span className="budget__label">Budget</span>
        <span className="budget__figure">—</span>
      </div>
    );
  }

  const level = budget.percent_used >= 100 ? "over" : budget.percent_used >= 80 ? "warn" : "ok";

  return (
    <div className={`budget budget--${level}`} data-testid="budget-meter">
      <span className="budget__label">{budget.period}</span>
      <span
        className="budget__bar"
        role="meter"
        aria-valuenow={budget.percent_used}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label="Month-to-date spend against the monthly cap"
      >
        <span
          className="budget__fill"
          style={{ width: `${String(Math.min(100, budget.percent_used))}%` }}
        />
      </span>
      <span className="budget__figure">
        {budget.spent_display} / {budget.cap_display}
      </span>
      {level === "over" && (
        <span className="budget__note">Cap reached — further runs are refused.</span>
      )}
    </div>
  );
}
