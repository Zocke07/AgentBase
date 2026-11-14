import type { UsageBucket } from "@agentbase/schemas";

import { BucketTable, DayChart, ModelName } from "../../components/UsageCharts";

/**
 * Usage's charts from made-up spend (brief 8, drawn with the dataviz
 * skill's rules): a month of days with gaps, the busiest one labelled, and
 * the models' shares. Scratch data's demo run costs nothing, so the real
 * app's screenshots show no bars; this page is where to look at them.
 */

const cents = (micros: number) => `$${(micros / 1_000_000).toFixed(2)}`;

const day = (date: number, micros: number, calls: number): UsageBucket => {
  const key = `2026-11-${String(date).padStart(2, "0")}`;
  return { key, label: key, calls, input_tokens: calls * 9_000, output_tokens: calls * 700, cost_micros: micros, cost_display: cents(micros) };
};

const DAYS: readonly UsageBucket[] = [
  day(2, 180_000, 14),
  day(3, 220_000, 17),
  day(4, 160_000, 12),
  day(5, 410_000, 31),
  day(6, 190_000, 15),
  day(9, 250_000, 19),
  day(10, 300_000, 22),
  day(11, 120_000, 9),
  day(12, 640_000, 44),
  day(13, 210_000, 16),
];

const model = (key: string, micros: number, calls: number): UsageBucket => ({
  key,
  label: key.replace("/", " · "),
  calls,
  input_tokens: calls * 9_000,
  output_tokens: calls * 700,
  cost_micros: micros,
  cost_display: cents(micros),
});

const MODELS: readonly UsageBucket[] = [
  model("anthropic/claude-sonnet-5-5", 1_760_000, 98),
  model("anthropic/claude-haiku-5-5", 520_000, 91),
  model("anthropic/claude-opus-5-5", 400_000, 10),
];

export function UsagePage() {
  return (
    <div className="wb-controls usage">
      <section className="usage__section">
        <h3>By day</h3>
        <DayChart period="2026-11" days={DAYS} />
      </section>
      <section className="usage__section">
        <h3>By model</h3>
        <BucketTable rows={MODELS} empty="" testId="wb-usage-models" name={(row) => <ModelName row={row} />} />
      </section>
    </div>
  );
}
