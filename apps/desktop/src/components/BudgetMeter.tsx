import type { BudgetResponse } from "@agentspace/schemas";

/**
 * Month-to-date spend against the cap. The one panel that is not a projection
 * of a run's log: the cap spans every run, so it comes from `GET /budget` and
 * sits outside the identity comparison. The display strings come from the
 * backend, so the rounding rule lives in one place.
 */

export interface BudgetMeterProps {
  budget: BudgetResponse | null;
}

export function BudgetMeter({ budget }: BudgetMeterProps) {
  if (budget === null) {
    return (
      <div className="budget budget--unknown" data-testid="budget-meter">
        <span className="budget__label">Budget</span>
        <span className="budget__figure">-</span>
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
        <span className="budget__note">Cap reached: further runs are refused.</span>
      )}
    </div>
  );
}
