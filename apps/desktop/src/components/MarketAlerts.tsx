import type { MarketAlert } from "@agentbase/schemas";

import { whenLabel } from "../lib/format";
import { alertBatches, moveBasis } from "../state/alerts";

/**
 * Home's list of a space's recent market alerts (Phase 18), newest first:
 * what moved, from what, and what the explaining run found. Alerts that were
 * unseen when Home opened stay marked as new while it is shown.
 */

export interface MarketAlertsProps {
  alerts: readonly MarketAlert[];
  /** Alert ids that were unseen when this list was opened. */
  fresh: ReadonlySet<string>;
  onOpenNote?: ((path: string) => void) | undefined;
  onOpenRun?: ((runId: string) => void) | undefined;
  onOpenAutomations?: (() => void) | undefined;
}

/** A few checks' worth; older alerts are a click away in the Journal. */
const BATCHES_SHOWN = 6;

const STATUS_WORDS: Readonly<Record<MarketAlert["explanation_status"], string>> = {
  queued: "Looking for the reason shortly; it waits while another run in this space finishes.",
  running: "Looking for the reason now.",
  done: "",
  failed: "The explanation could not be completed; its run shows why.",
  skipped: "Not explained: today's explanation limit was reached.",
  off: "Explanations are off for this space.",
};

export function MarketAlerts({ alerts, fresh, onOpenNote, onOpenRun, onOpenAutomations }: MarketAlertsProps) {
  if (alerts.length === 0) return null;
  const batches = alertBatches(alerts).slice(0, BATCHES_SHOWN);
  return (
    <section className="market-alerts" aria-label="Market alerts" data-testid="market-alerts">
      <div className="market-alerts__head">
        <h2>Market alerts</h2>
        {onOpenAutomations !== undefined && (
          <button type="button" className="link" onClick={onOpenAutomations}>
            Market watch settings
          </button>
        )}
      </div>
      <ul className="market-alerts__list">
        {batches.map((batch) => {
          const isNew = batch.alerts.some((alert) => fresh.has(alert.id));
          return (
            <li key={batch.batchId} className={`market-alerts__item${isNew ? " market-alerts__item--new" : ""}`}>
              <div className="market-alerts__when">
                {whenLabel(batch.alerts[0]?.quoted_at ?? batch.createdAt)} · {newYorkTime(batch.alerts[0]?.quoted_at ?? batch.createdAt)}
                {isNew && <span className="market-alerts__badge">New</span>}
              </div>
              <ul className="market-alerts__moves">
                {batch.alerts.map((alert) => (
                  <li key={alert.id} className={`market-alerts__move market-alerts__move--${alert.direction}`}>
                    <strong>
                      {alert.symbol} {alert.direction === "up" ? "▲" : "▼"} {Math.abs(alert.change_pct).toFixed(2)}%
                    </strong>{" "}
                    <span>
                      {moveBasis(alert)}, at {alert.price.toLocaleString(undefined, { maximumFractionDigits: 2 })}
                      {alert.instrument === "index" ? "" : " USD"}
                      {alert.name !== null ? ` · ${alert.name}` : ""}
                    </span>
                  </li>
                ))}
              </ul>
              <p className="market-alerts__why">
                {batch.status === "done" && batch.explanation !== null ? (
                  <>
                    <span className="market-alerts__label">Likely reason:</span> {batch.explanation}
                  </>
                ) : (
                  STATUS_WORDS[batch.status]
                )}
              </p>
              <div className="market-alerts__actions">
                {batch.status === "done" && batch.notePath !== null && onOpenNote !== undefined && (
                  <button
                    type="button"
                    className="button button--small"
                    onClick={() => {
                      if (batch.notePath !== null) onOpenNote(batch.notePath);
                    }}
                  >
                    Read the sources
                  </button>
                )}
                {batch.runId !== null && onOpenRun !== undefined && (
                  <button
                    type="button"
                    className="button button--small"
                    onClick={() => {
                      if (batch.runId !== null) onOpenRun(batch.runId);
                    }}
                  >
                    Open its run
                  </button>
                )}
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

/** `12:05 PM New York`: the market's own clock, which the notes and messages use. */
function newYorkTime(iso: string): string {
  const time = new Date(iso).toLocaleTimeString(undefined, {
    timeZone: "America/New_York",
    hour: "numeric",
    minute: "2-digit",
  });
  return `${time} New York`;
}
