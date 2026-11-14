import type { MonitorStatus } from "@agentbase/schemas";
import { useCallback, useEffect, useState } from "react";

import * as api from "../lib/api";
import { whenLabel } from "../lib/format";
import { useFetched } from "../state/useFetched";

import { Status } from "./ui/Status";

/**
 * Automations' market watch card (Phase 18): on or off, what it follows and
 * when it looks, and what raises an alert. The thresholds are the space's
 * `config/monitor.json`, opened in Knowledge to change.
 */

export interface MarketWatchProps {
  spaceId: string;
  /** Open the space's settings file in Knowledge. */
  onOpenFile?: ((path: string) => void) | undefined;
}

const MONITOR_FILE = "config/monitor.json";
/** The card rereads its status this often while it is mounted. */
const REFRESH_MS = 60_000;

export function MarketWatch({ spaceId, onOpenFile }: MarketWatchProps) {
  const load = useCallback(() => api.getMonitor(spaceId), [spaceId]);
  const status = useFetched(load, null);
  const { reload } = status;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const timer = window.setInterval(reload, REFRESH_MS);
    return () => {
      window.clearInterval(timer);
    };
  }, [reload]);

  const watch = status.data;
  const switchTo = async (enabled: boolean) => {
    setBusy(true);
    setError(null);
    try {
      await api.setMonitor(spaceId, enabled);
      reload();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="settings__section market-watch" aria-label="Market watch" data-testid="market-watch">
      <div className="market-watch__head">
        <div>
          <h2>Market watch</h2>
          <p className="settings__hint">
            Alerts you to sudden moves in your holdings, your watchlist and the main US indexes, and looks up the
            likely reason. It works while AgentBase is open, from 04:00 to 20:00 New York time on weekdays.
          </p>
        </div>
        {watch !== null && (
          <button
            type="button"
            className={`button button--small${watch.enabled ? "" : " button--primary"}`}
            disabled={busy}
            onClick={() => void switchTo(!watch.enabled)}
          >
            {watch.enabled ? "Turn off" : "Turn on"}
          </button>
        )}
      </div>
      {watch !== null && <WatchStatus watch={watch} />}
      {watch?.error !== null && watch?.error !== undefined && (
        <p className="field-error" role="alert">
          {watch.error}
        </p>
      )}
      {(error ?? status.error) !== null && (
        <p className="field-error" role="alert">
          {error ?? status.error}
        </p>
      )}
      {onOpenFile !== undefined && (
        <button
          type="button"
          className="link market-watch__edit"
          onClick={() => {
            onOpenFile(MONITOR_FILE);
          }}
        >
          Change what raises an alert
        </button>
      )}
    </section>
  );
}

function WatchStatus({ watch }: { watch: MonitorStatus }) {
  const symbols = watch.symbols ?? [];
  const thresholds = (
    <p className="market-watch__rules">
      An alert is a move of {String(watch.stock_move_pct ?? 5)}% from the previous close, or{" "}
      {String(watch.stock_jump_pct ?? 2.5)}% within {String(watch.jump_window_minutes ?? 15)} minutes; for an index,{" "}
      {String(watch.index_move_pct ?? 1.5)}% and {String(watch.index_jump_pct ?? 1)}%.{" "}
      {watch.explain === false
        ? "Explanations are off."
        : `Each alert's reason is researched by a short run, at most ${String(watch.max_explanations_per_day ?? 10)} a day (${String(watch.explanations_today ?? 0)} today).`}
    </p>
  );
  if (!watch.enabled) {
    return (
      <>
        <p className="market-watch__state">Off.</p>
        {thresholds}
      </>
    );
  }
  return (
    <>
      <p className="market-watch__state" data-testid="market-watch-state">
        <Status kind="running">On</Status>{" "}
        {watch.market_open
          ? `Checks ${symbols.length > 0 ? `${String(symbols.length)} symbols` : "its symbols"} every ${String(watch.check_every_minutes ?? 5)} minutes.`
          : "The US market is closed now; it resumes at 04:00 New York time on the next weekday."}
        {watch.last_checked_at !== null && watch.last_checked_at !== undefined && (
          <> Last check {whenLabel(watch.last_checked_at)}.</>
        )}
      </p>
      {symbols.length > 0 && <p className="market-watch__symbols">{symbols.join(" · ")}</p>}
      {thresholds}
      {(watch.problems ?? []).map((problem) => (
        <p key={problem} className="settings__hint">
          {problem}
        </p>
      ))}
    </>
  );
}
