import type { BudgetResponse, UsageBucket, UsageReport } from "@agentbase/schemas";
import { useCallback, useEffect, useRef, useState } from "react";

import * as api from "../lib/api";
import { modelLabel, moneyShort, periodLabel } from "../lib/format";
import { useFetched } from "../state/useFetched";
import { usePresence } from "../state/usePresence";

import { Skeleton } from "./Skeleton";

/**
 * Month-to-date cap usage from `GET /budget`, not a single run-log projection;
 * exclude from identity comparison. Backend supplies display strings and rounding.
 *
 * The chip opens a breakdown: this space's share, runs and their average, the
 * models and spaces the money went to, and the per-run limit, read from
 * `GET /usage` each time it opens so it is never a stale copy.
 */

export interface BudgetMeterProps {
  budget: BudgetResponse | null;
  /** The window's space, named beside its share. */
  spaceName?: string | null | undefined;
  /** The per-run ceiling that applies here, in micros: 0 is off, null unknown. */
  runLimitMicros?: number | null | undefined;
  onOpenUsage?: (() => void) | undefined;
  onOpenSettings?: (() => void) | undefined;
}

/** How many models and spaces the breakdown names before "and N more". */
const TOP = 3;

/** Whole cents, and never "$0" for a sum that is not nothing. */
function money(micros: number): string {
  return micros > 0 && micros < 5_000 ? "under 1¢" : moneyShort(micros);
}

export function BudgetMeter({ budget, spaceName, runLimitMicros, onOpenUsage, onOpenSettings }: BudgetMeterProps) {
  const [open, setOpen] = useState(false);
  const panel = usePresence(open, 140);
  const anchor = useRef<HTMLDivElement>(null);
  const toggle = useRef<HTMLButtonElement>(null);
  const dialog = useRef<HTMLDivElement>(null);

  const close = useCallback((refocus: boolean) => {
    setOpen(false);
    if (refocus) toggle.current?.focus();
  }, []);

  // Escape or a click elsewhere closes it, like any other popover here.
  useEffect(() => {
    if (!open) return undefined;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") close(true);
    };
    const onPointer = (event: PointerEvent) => {
      if (!(event.target instanceof Node) || anchor.current?.contains(event.target) !== true) close(false);
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onPointer);
    dialog.current?.focus();
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onPointer);
    };
  }, [open, close]);

  if (budget === null) {
    return (
      <div className="budget budget--unknown" data-testid="budget-meter">
        <span className="budget__figure">-</span>
        <span className="budget__label">this month</span>
      </div>
    );
  }

  const level = budget.percent_used >= 100 ? "over" : budget.percent_used >= 80 ? "warn" : "ok";
  const go = (then: (() => void) | undefined) =>
    then === undefined
      ? undefined
      : () => {
          close(false);
          then();
        };

  // Glance rounding; tooltip retains ledger precision.
  return (
    <div className="budget-anchor" ref={anchor}>
      <div
        className={`budget budget--${level}${open ? " budget--open" : ""}`}
        data-testid="budget-meter"
        title={`${budget.spent_display} of your ${budget.cap_display} monthly limit, ${periodLabel(budget.period)}. Click for the breakdown.`}
      >
        {/* The whole chip is the button's target (a stretched `::after`); the
            meter stays outside it, since a button's content is not read as
            separate controls. */}
        <button
          type="button"
          ref={toggle}
          className="budget__toggle"
          aria-expanded={open}
          aria-haspopup="dialog"
          aria-controls="cost-panel"
          onClick={() => {
            setOpen((current) => !current);
          }}
        >
          <span className="budget__figure">
            <b>{moneyShort(budget.spent_micros)}</b> of {moneyShort(budget.cap_micros)}
          </span>
          <span className="sr-only"> spent this month. Show the breakdown.</span>
        </button>
        <span
          className="budget__bar"
          role="meter"
          aria-valuenow={budget.percent_used}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label="Spent this month, out of your monthly limit"
        >
          <span className="budget__fill" style={{ width: `${String(Math.min(100, budget.percent_used))}%` }} />
        </span>
        <span className="budget__label" aria-hidden="true">
          this month
        </span>
        <span className="budget__chevron" aria-hidden="true" />
        {level === "over" && <span className="budget__note">Monthly limit reached: new tasks will not start.</span>}
      </div>

      {panel.mounted && (
        <div
          id="cost-panel"
          ref={dialog}
          className={`cost-panel${panel.closing ? " cost-panel--closing" : ""}`}
          role="dialog"
          aria-label="Spending this month"
          tabIndex={-1}
          data-testid="cost-panel"
        >
          <CostBreakdown
            budget={budget}
            spaceName={spaceName ?? null}
            runLimitMicros={runLimitMicros ?? null}
            onOpenUsage={go(onOpenUsage)}
            onOpenSettings={go(onOpenSettings)}
          />
        </div>
      )}
    </div>
  );
}

const NO_REPORT: UsageReport | null = null;

function CostBreakdown({
  budget,
  spaceName,
  runLimitMicros,
  onOpenUsage,
  onOpenSettings,
}: {
  budget: BudgetResponse;
  spaceName: string | null;
  runLimitMicros: number | null;
  onOpenUsage: (() => void) | undefined;
  onOpenSettings: (() => void) | undefined;
}) {
  const load = useCallback(() => api.getUsage(budget.period, null), [budget.period]);
  const usage = useFetched<UsageReport | null>(load, NO_REPORT);
  const report = usage.data;
  const left = Math.max(0, budget.cap_micros - budget.spent_micros);

  return (
    <>
      <header className="cost-panel__head">
        <h2 className="cost-panel__title">Spending in {periodLabel(budget.period)}</h2>
        <p className="cost-panel__total">
          <b>{money(budget.spent_micros)}</b> of your {moneyShort(budget.cap_micros)} monthly limit
        </p>
        <p className="cost-panel__sub">
          {budget.percent_used}% used · {money(left)} left · resets on the 1st
        </p>
      </header>

      <dl className="cost-panel__facts">
        {budget.space_spent_micros !== undefined && budget.space_spent_micros !== null && (
          <div>
            <dt>{spaceName === null ? "This space" : `In ${spaceName}`}</dt>
            <dd>{money(budget.space_spent_micros)}</dd>
          </div>
        )}
        {report !== null && (
          <div>
            <dt>Runs</dt>
            <dd>
              {report.totals.runs}
              {report.totals.runs > 0 && ` · about ${money(Math.round(report.totals.cost_micros / report.totals.runs))} each`}
            </dd>
          </div>
        )}
        {runLimitMicros !== null && (
          <div>
            <dt>Limit per run</dt>
            <dd>{runLimitMicros === 0 ? "none" : moneyShort(runLimitMicros)}</dd>
          </div>
        )}
      </dl>

      {usage.error !== null && (
        <p className="cost-panel__error" role="alert">
          Could not read the breakdown: {usage.error}
        </p>
      )}
      {report === null && usage.error === null && <Skeleton label="Reading this month's spending" lines={4} />}
      {report !== null && (
        <>
          <Split
            title="By model"
            rows={report.by_model}
            total={report.totals.cost_micros}
            // Keys are "provider/model"; the model's own name is what a person knows.
            name={(row) => modelLabel(row.key.slice(row.key.indexOf("/") + 1))}
            testId="cost-by-model"
          />
          <Split title="By space" rows={report.by_space} total={report.totals.cost_micros} testId="cost-by-space" />
        </>
      )}

      <footer className="cost-panel__actions">
        {onOpenUsage !== undefined && (
          <button type="button" className="button button--small" onClick={onOpenUsage}>
            See all usage
          </button>
        )}
        {onOpenSettings !== undefined && (
          <button type="button" className="link-button" onClick={onOpenSettings}>
            Change limits
          </button>
        )}
      </footer>
    </>
  );
}

/** A few named shares of the month, largest first, as bars against the total. */
function Split({
  title,
  rows,
  total,
  name = (row) => row.label,
  testId,
}: {
  title: string;
  rows: readonly UsageBucket[];
  total: number;
  name?: (row: UsageBucket) => string;
  testId: string;
}) {
  if (rows.length === 0) return null;
  const shown = [...rows].sort((left, right) => right.cost_micros - left.cost_micros).slice(0, TOP);
  const rest = rows.length - shown.length;
  return (
    <section className="cost-panel__split" data-testid={testId}>
      <h3>{title}</h3>
      <ul>
        {shown.map((row) => (
          <li key={row.key} title={`${row.label}: ${row.cost_display}, ${String(row.calls)} model calls`}>
            <span className="cost-panel__name">{name(row)}</span>
            <span className="cost-panel__amount">{money(row.cost_micros)}</span>
            <span className="cost-panel__share" aria-hidden="true">
              <span style={{ width: `${String(total > 0 ? Math.round((row.cost_micros / total) * 100) : 0)}%` }} />
            </span>
          </li>
        ))}
      </ul>
      {rest > 0 && <p className="cost-panel__more">and {rest} more</p>}
    </section>
  );
}
