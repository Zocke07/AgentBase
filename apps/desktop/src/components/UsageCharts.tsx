import type { UsageBucket } from "@agentbase/schemas";
import type { ReactNode } from "react";

import { formatCount, formatMicros, modelLabel, providerLabel } from "../lib/format";

/**
 * Usage's charts (Phase 20, brief 8): spend by day, and a breakdown with
 * each row's share. They draw what they are given, so the workbench shows
 * them from made-up spend; figures are the ledger's, never re-derived.
 */

/**
 * Cost bars in a slot for every day of the period, so a bar sits at its date;
 * a day with no ledger rows is an empty slot, a gap rather than a zero. Days
 * are the ledger's, in UTC.
 *
 * Drawn by the dataviz skill's rules: one series, so one hue (`--viz-1`);
 * thin bars with rounded data-ends and a gap between days; recessive
 * gridlines at the axis's three ticks; the busiest day labelled directly;
 * the platform's own tooltip on each bar, which no container clips and no
 * hidden section leaves behind; and the same figures as a table one fold
 * away, for the keyboard and for anyone the colour does not reach.
 */
export function DayChart({ period, days }: { period: string; days: readonly UsageBucket[] }) {
  const most = Math.max(1, ...days.map((day) => day.cost_micros));
  const midpoint = Math.round(most / 2);
  const byDay = new Map(days.map((day) => [day.key, day]));
  const peak = days.reduce<UsageBucket | null>((best, day) => (best === null || day.cost_micros > best.cost_micros ? day : best), null);
  const describe = (day: UsageBucket) =>
    `${String(day.calls)} call${day.calls === 1 ? "" : "s"} · ${formatCount(day.input_tokens)} in · ${formatCount(day.output_tokens)} out`;
  return (
    <>
      <div className="usage__chart-frame">
        <div className="usage__y-axis" aria-hidden="true" data-testid="usage-y-axis">
          <span>{formatMicros(most)}</span>
          <span>{formatMicros(midpoint)}</span>
          <span>{formatMicros(0)}</span>
        </div>
        <div
          className="usage__chart"
          role="img"
          aria-label={`Spend by day. Y axis ${formatMicros(0)} to ${formatMicros(most)}: ${days.map((day) => `${day.label} ${day.cost_display}`).join(", ")}`}
        >
          {daysOf(period, days).map((key, index, all) => {
            const day = byDay.get(key);
            const edge = index < 4 ? " usage__bar--start" : index >= all.length - 4 ? " usage__bar--end" : "";
            const date = index + 1;
            const height = day === undefined ? 0 : Math.max(2, Math.round((day.cost_micros * 100) / most));
            return (
              <div
                key={key}
                className={`usage__bar${edge}${day === undefined ? "" : " usage__bar--spent"}${day !== undefined && day.key === peak?.key ? " usage__bar--peak" : ""}`}
                title={day === undefined ? `${key}: nothing spent` : `${day.label}: ${day.cost_display} · ${describe(day)}`}
                data-testid={`usage-day-${key}`}
              >
                <span className="usage__bar-track">
                  {day !== undefined && (
                    <span className="usage__bar-fill" style={{ height: `${String(height)}%` }}>
                      {day.key === peak?.key && (
                        <span className="usage__bar-value" aria-hidden="true">
                          {day.cost_display}
                        </span>
                      )}
                    </span>
                  )}
                </span>
                <span className="usage__bar-label">{day !== undefined || date === 1 || date % 5 === 0 ? date : ""}</span>
              </div>
            );
          })}
        </div>
      </div>
      {peak !== null && (
        <p className="usage__chart-note">
          Most in one day: {peak.cost_display} on {peak.label}. Days are counted in UTC.
        </p>
      )}
      <details className="usage__days">
        <summary>The days as a table</summary>
        <BucketTable rows={days} empty="" testId="usage-days-table" heading="Day" share={false} />
      </details>
    </>
  );
}

/** `YYYY-MM-DD` for every day of a `YYYY-MM` period, or the ledger's own days if it does not parse. */
function daysOf(period: string, days: readonly UsageBucket[]): string[] {
  const match = /^(\d{4})-(\d{2})$/.exec(period);
  if (match === null) return days.map((day) => day.key);
  const [, year = "", month = ""] = match;
  const count = new Date(Date.UTC(Number(year), Number(month), 0)).getUTCDate();
  return Array.from({ length: count }, (_unused, index) => `${period}-${String(index + 1).padStart(2, "0")}`);
}

/**
 * A model row by the name the header uses ("GPT-5.6 Terra"), its provider
 * beside it; the ledger's own identifier stays on the row's tooltip.
 */
export function ModelName({ row }: { row: UsageBucket }) {
  const slash = row.key.indexOf("/");
  if (slash < 0) return <>{row.label}</>;
  return (
    <span title={row.label}>
      {modelLabel(row.key.slice(slash + 1))}
      <span className="usage__origin"> · {providerLabel(row.key.slice(0, slash))}</span>
    </span>
  );
}

export function BucketTable({
  rows,
  empty,
  testId,
  name = (row) => row.label,
  heading = " ",
  share: withShare = true,
}: {
  rows: readonly UsageBucket[];
  empty: string;
  testId: string;
  name?: (row: UsageBucket) => ReactNode;
  /** The first column's header; the rows' names need none in a breakdown. */
  heading?: string;
  /** Each row's part of the whole, as a bar and in words. */
  share?: boolean;
}) {
  if (rows.length === 0) return <p className="usage__empty">{empty}</p>;
  // Each row's part of the cost; the bar beside it shows the same in length.
  const total = rows.reduce((sum, row) => sum + row.cost_micros, 0);
  return (
    // A table wider than its card scrolls inside it, never the section.
    <div className="usage__table-scroll">
      <table className="usage__table" data-testid={testId}>
        <thead>
          <tr>
            <th scope="col">{heading}</th>
            <th scope="col" className="usage__num">
              Calls
            </th>
            <th scope="col" className="usage__num">
              In
            </th>
            <th scope="col" className="usage__num">
              Out
            </th>
            <th scope="col" className="usage__num">
              Cost
            </th>
            {withShare && (
              <th scope="col" className="usage__share-head">
                Share
              </th>
            )}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const part = total === 0 ? 0 : (row.cost_micros * 100) / total;
            // Something spent never reads as nothing: under half a percent is "<1%".
            const words = part > 0 && part < 0.5 ? "<1%" : `${String(Math.round(part))}%`;
            return (
              <tr key={row.key}>
                <td>{name(row)}</td>
                <td className="usage__num">{formatCount(row.calls)}</td>
                <td className="usage__num">{formatCount(row.input_tokens)}</td>
                <td className="usage__num">{formatCount(row.output_tokens)}</td>
                <td className="usage__num">{row.cost_display}</td>
                {withShare && (
                  <td>
                    <span className="usage__share">
                      <span className="usage__share-track" aria-hidden="true">
                        <span className="usage__share-fill" style={{ width: part > 0 ? `max(2px, ${String(part)}%)` : 0 }} />
                      </span>
                      <span className="num">{words}</span>
                    </span>
                  </td>
                )}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

