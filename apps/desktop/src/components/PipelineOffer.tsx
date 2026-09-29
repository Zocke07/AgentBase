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
      <h2 className="card__title">The investment pipeline is ready to run on its own</h2>
      <p>
        {stages.length} schedules are set up and switched off: {stages.map((row) => row.name).join(", ")}.
        Turned on, the morning collection runs on weekdays, the theses and the daily decision follow it
        as soon as each stage completes, and the knowledge and review stages run weekly. The decision is
        a recommendation for you to review; nothing is bought or sold.
      </p>
      <p className="settings__hint">
        Each run stops at its time limit
        {runCapMicros !== null && runCapMicros > 0 && ` and before spending $${(runCapMicros / 1_000_000).toFixed(2)}`}, and
        the monthly cap still holds. Any data file the agents read that is missing is created from its
        template first; edit config/watchlist.json in Knowledge to choose your tickers.
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
