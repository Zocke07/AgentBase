import type { BudgetResponse } from "@agentbase/schemas";

import { moneyShort, periodLabel } from "../lib/format";

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
        <span className="budget__figure">-</span>
        <span className="budget__label">this month</span>
      </div>
    );
  }

  const level = budget.percent_used >= 100 ? "over" : budget.percent_used >= 80 ? "warn" : "ok";

  // Rounded for the glance; the ledger's exact figures are in the tooltip.
  return (
    <div
      className={`budget budget--${level}`}
      data-testid="budget-meter"
      title={`${budget.spent_display} of your ${budget.cap_display} monthly limit, ${periodLabel(budget.period)}. Change the limit in Settings.`}
    >
      <span className="budget__figure">
        <b>{moneyShort(budget.spent_micros)}</b> of {moneyShort(budget.cap_micros)}
      </span>
      <span
        className="budget__bar"
        role="meter"
        aria-valuenow={budget.percent_used}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label="Spent this month, out of your monthly limit"
      >
        <span
          className="budget__fill"
          style={{ width: `${String(Math.min(100, budget.percent_used))}%` }}
        />
      </span>
      <span className="budget__label">this month</span>
      {level === "over" && (
        <span className="budget__note">Monthly limit reached: new tasks will not start.</span>
      )}
    </div>
  );
}
