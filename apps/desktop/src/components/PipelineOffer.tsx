import type { ScheduleResponse } from "@agentbase/schemas";
import { useState } from "react";

import { pipelineOf, pipelineWaiting, turnOnPipeline, type PipelineResult } from "../lib/pipeline";

/**
 * The one-click start of the shipped investment pipeline, shown only while its
 * seeded schedules are all still off. Consent to spend is the click itself:
 * nothing is enabled before it, and it names the limits that bound each run.
 */

export interface PipelineOfferProps {
  spaceId: string;
  /** The space's schedules, as the caller already has them. */
  schedules: readonly ScheduleResponse[];
  /** Per-run spending ceiling in micros, to say what bounds each stage. */
  runCapMicros: number | null;
  /** Called after an attempt, even one that failed part way, so the caller
      rereads the schedules; `null` when nothing could be done. */
  onTurnedOn: (result: PipelineResult | null) => void;
}

export function PipelineOffer({ spaceId, schedules, runCapMicros, onTurnedOn }: PipelineOfferProps) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!pipelineWaiting(schedules)) return null;
  const stages = pipelineOf(schedules);

  const turnOn = async () => {
    setBusy(true);
    setError(null);
    try {
      onTurnedOn(await turnOnPipeline(spaceId, schedules));
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
      // Some stages may be on already; the caller rereads what is true.
      onTurnedOn(null);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="card pipeline-offer" data-testid="pipeline-offer">
      <h2 className="card__title">Set up the investment pipeline</h2>
      <p>
        {stages.length} schedules are set up and switched off: {stages.map((row) => row.name).join(", ")}.
        Turned on, the morning collection runs on its chosen local days, the theses and the daily decision follow it
        as soon as each stage completes, and the knowledge and review stages run weekly. The decision is
        a recommendation for you to review; nothing is bought or sold.
      </p>
      <div className="pipeline-offer__details">
        <p>
          <strong>What this creates:</strong> starter files for your watchlist and positions, plus risk
          limits, public data sources and a four-chart dashboard. Existing files are never replaced.
        </p>
        <p>
          <strong>Sample portfolio:</strong> one share each of MU, ORCL, CRWV, MSFT, NOW and AVGO, with
          $2,500 USD cash. Purchase prices and dates are blank because they are unknown. Review the sample
          in Home&apos;s My portfolio editor and replace it with your real holdings before relying on the results.
          Limits start at 10% per stock, 70% per sector and 3% daily loss; technology subsectors share the sector limit.
        </p>
        <p>
          <strong>Daily research:</strong> your holdings plus Yahoo Finance top gainers, losers, high-volume
          stocks and headlines, with company news and annual or quarterly financial figures from Yahoo.
          Missing sources are recorded in the run. Optional SEC company facts and filing excerpts require
          your identifying contact in the source settings.
        </p>
        <p>
          <strong>Forecast workbook:</strong> one Excel file per month, with a sheet for each market session
          and forecasts for 1, 2, 3, 5 and 21 trading days ahead, approximately one week and one month for the last two.
          The baseline repeats the latest close and is labeled as such; conditional research scenarios carry their evidence and assumptions.
          Later runs fill actual prices when those sessions arrive. Keep AgentBase open for scheduled runs and updates.
        </p>
      </div>
      <p className="settings__hint pipeline-offer__limits">
        Each run stops at its time limit
        {runCapMicros !== null && runCapMicros > 0 && ` and before spending $${(runCapMicros / 1_000_000).toFixed(2)}`}, and
        the monthly cap still holds.
      </p>
      {error !== null && (
        <p className="field-error" role="alert">
          {error}
        </p>
      )}
      <div className="card__actions">
        <button
          type="button"
          className="button button--primary"
          disabled={busy}
          aria-busy={busy}
          onClick={() => void turnOn()}
          data-testid="pipeline-turn-on"
        >
          {busy ? "Turning it on…" : "Turn on the daily pipeline"}
        </button>
      </div>
    </section>
  );
}
