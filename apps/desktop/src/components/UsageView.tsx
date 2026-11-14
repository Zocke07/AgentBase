import type { SpaceResponse, UsageReport, UsageRun } from "@agentbase/schemas";
import { useCallback, useEffect, useRef, useState } from "react";

import * as api from "../lib/api";
import {
  clockDate,
  ellipsise,
  formatCount,
  moneyShort,
  periodLabel,
  runOriginLabel,
} from "../lib/format";
import { useFetched } from "../state/useFetched";

import { Skeleton } from "./Skeleton";
import { BucketTable, DayChart, ModelName } from "./UsageCharts";

/**
 * Ledger-backed monthly model usage by day, model, space, and run, including
 * peak context. Every figure is cap-enforced ledger data, matching header meter.
 */

export interface UsageViewProps {
  /** Selected space; may narrow view or show all. */
  space: SpaceResponse | null;
  /** Section visibility, triggering report reload on open. */
  active: boolean;
  /** Open run, switching space if needed. */
  onOpenRun: (runId: string) => void;
  /** Where the cap is changed. */
  onOpenSettings: () => void;
  /**
   * The app-wide month-to-date spend the header meter shows. When it moves
   * while this section is open, a run has spent since the report was read,
   * so the report is read again and agrees with the meter.
   */
  ledgerMicros?: number | null | undefined;
}

type Scope = "space" | "all";

export function UsageView({ space, active, onOpenRun, onOpenSettings, ledgerMicros = null }: UsageViewProps) {
  const [scope, setScope] = useState<Scope>("space");
  const [period, setPeriod] = useState<string | null>(null);
  const spaceId = scope === "space" ? (space?.id ?? null) : null;

  const load = useCallback(() => api.getUsage(period, spaceId), [period, spaceId]);
  const fetched = useFetched<UsageReport | null>(load, null);
  const report = fetched.data;
  const { error, loading, reload } = fetched;

  // Reload on opening to include ledger entries since previous view.
  const wasActive = useRef(active);
  useEffect(() => {
    if (active && !wasActive.current) reload();
    wasActive.current = active;
  }, [active, reload]);
  const seenLedger = useRef(ledgerMicros);
  useEffect(() => {
    if (seenLedger.current === ledgerMicros) return;
    seenLedger.current = ledgerMicros;
    // A closed section catches up when it is opened, above.
    if (active) reload();
  }, [active, ledgerMicros, reload]);

  const periods = report === null ? [] : report.periods.includes(report.period) ? report.periods : [report.period, ...report.periods];
  const cap = report?.cap_micros ?? 0;
  const spent = report?.totals.cost_micros ?? 0;
  const percent = cap > 0 ? Math.min(100, Math.round((spent * 100) / cap)) : 0;

  return (
    <div className="usage" data-testid="usage">
      <header className="usage__head">
        <div>
          <h2 className="usage__title">Usage</h2>
          <p className="usage__hint">
            Every model call the app has made, from the ledger the monthly cap is enforced on. A call&apos;s
            input tokens are the context it sent; a run&apos;s peak is the most any one of its calls carried.
          </p>
        </div>
        <div className="usage__controls">
          <label>
            <span className="sr-only">Period</span>
            <select
              value={report?.period ?? ""}
              onChange={(changed) => {
                setPeriod(changed.target.value);
              }}
              aria-label="Period"
              data-testid="usage-period"
            >
              {periods.map((choice) => (
                <option key={choice} value={choice}>
                  {periodLabel(choice)}
                </option>
              ))}
            </select>
          </label>
          <div className="usage__scope" role="radiogroup" aria-label="Scope">
            <button
              type="button"
              className={`usage__scope-choice${scope === "space" ? " usage__scope-choice--on" : ""}`}
              aria-pressed={scope === "space"}
              onClick={() => {
                setScope("space");
              }}
            >
              {space === null ? "This space" : space.name}
            </button>
            <button
              type="button"
              className={`usage__scope-choice${scope === "all" ? " usage__scope-choice--on" : ""}`}
              aria-pressed={scope === "all"}
              onClick={() => {
                setScope("all");
              }}
            >
              All spaces
            </button>
          </div>
        </div>
      </header>

      {error !== null && (
        <p className="field-error" role="alert">
          {error}
        </p>
      )}

      {report === null ? (
        loading ? (
          <Skeleton label="Adding up this month's use" cards={4} />
        ) : (
          <p className="usage__loading">No report yet.</p>
        )
      ) : (
        <div className={`usage__body${loading ? " usage__body--stale" : ""}`}>
          <section className="usage__cards" aria-label="Totals">
            <div className="usage__card usage__card--spend" data-testid="usage-spent">
              <span className="usage__card-label">Spent in {periodLabel(report.period)}</span>
              <span className="usage__card-value">{report.totals.cost_display}</span>
              <span className="usage__card-note">
                {scope === "all" ? (
                  <>
                    of the {moneyShort(cap)} monthly limit · {percent}%
                    <span className="usage__meter" aria-hidden="true">
                      <span style={{ width: `${String(percent)}%` }} />
                    </span>
                  </>
                ) : (
                  <>
                    the {moneyShort(cap)} monthly limit is shared by every space; see All spaces for its use
                  </>
                )}
              </span>
            </div>
            <Card label="Model calls" value={formatCount(report.totals.calls)} note={`across ${String(report.totals.runs)} run${report.totals.runs === 1 ? "" : "s"}`} testId="usage-calls" />
            <Card label="Input tokens" value={formatCount(report.totals.input_tokens)} note="context sent to models" testId="usage-input" />
            <Card label="Output tokens" value={formatCount(report.totals.output_tokens)} note="text models wrote back" testId="usage-output" />
          </section>

          {report.by_day.length > 0 && (
            <section className="usage__section">
              <h3>By day</h3>
              <DayChart period={report.period} days={report.by_day} />
            </section>
          )}

          <div className="usage__columns">
            <section className="usage__section">
              <h3>By model</h3>
              <BucketTable rows={report.by_model} empty="No model calls in this period." testId="usage-models" name={(row) => <ModelName row={row} />} />
            </section>
            {scope === "all" && (
              <section className="usage__section">
                <h3>By space</h3>
                <BucketTable rows={report.by_space} empty="No model calls in this period." testId="usage-spaces" />
              </section>
            )}
          </div>

          <section className="usage__section">
            <h3>Costliest runs</h3>
            <RunTable rows={report.runs} onOpenRun={onOpenRun} />
          </section>

          <p className="usage__hint">
            The monthly cap is shared by every space and set in{" "}
            <button type="button" className="link-button" onClick={onOpenSettings}>
              Settings
            </button>
            . Deleting a run keeps its spend, with the run cleared, so this total never shrinks by deletion.
          </p>
        </div>
      )}
    </div>
  );
}

function Card({ label, value, note, testId }: { label: string; value: string; note: string; testId: string }) {
  return (
    <div className="usage__card" data-testid={testId}>
      <span className="usage__card-label">{label}</span>
      <span className="usage__card-value">{value}</span>
      <span className="usage__card-note">{note}</span>
    </div>
  );
}

function RunTable({ rows, onOpenRun }: { rows: readonly UsageRun[]; onOpenRun: (runId: string) => void }) {
  if (rows.length === 0) return <p className="usage__empty">No runs made a model call in this period.</p>;
  return (
    <table className="usage__table" data-testid="usage-runs">
      <thead>
        <tr>
          <th scope="col">Run</th>
          <th scope="col">When</th>
          <th scope="col" className="usage__num">
            Calls
          </th>
          <th scope="col" className="usage__num">
            In
          </th>
          <th scope="col" className="usage__num">
            Out
          </th>
          <th scope="col" className="usage__num" title="The most tokens one call sent, and the mean per call">
            Context
          </th>
          <th scope="col" className="usage__num">
            Cost
          </th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.run_id ?? "deleted"}>
            <td className="usage__goal">
              {row.run_id === null ? (
                <span className="usage__deleted">deleted runs</span>
              ) : (
                <button
                  type="button"
                  className="link-button"
                  title={row.goal ?? row.run_id}
                  onClick={() => {
                    onOpenRun(row.run_id ?? "");
                  }}
                >
                  {ellipsise(row.goal ?? row.run_id, 56)}
                </button>
              )}
              {runOriginLabel(row.origin) !== null && (
                <span className="usage__origin"> {runOriginLabel(row.origin)}</span>
              )}
            </td>
            <td>{row.created_at === null ? "-" : clockDate(row.created_at)}</td>
            <td className="usage__num">{formatCount(row.calls)}</td>
            <td className="usage__num">{formatCount(row.input_tokens)}</td>
            <td className="usage__num">{formatCount(row.output_tokens)}</td>
            <td className="usage__num">
              {formatCount(row.peak_context)}
              <span className="usage__mean"> · {formatCount(row.mean_context)} mean</span>
            </td>
            <td className="usage__num">{row.cost_display}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
