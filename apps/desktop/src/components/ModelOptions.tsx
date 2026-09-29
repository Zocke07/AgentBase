import type { ModelEntry } from "@agentbase/schemas";

import { modelLabel, modelOptionLabel } from "../lib/format";

/**
 * A provider's models as `<option>`s: the current lineup first, older models
 * still sold after it, each with its tier and price, so a choice does not
 * need a pricing page open beside it. The catalogue decides the order; where
 * it marks what a ChatGPT plan includes, those come first instead.
 */

export interface ModelOptionsProps {
  /** The catalogue's entries for one provider; empty falls back to `models`. */
  entries: readonly ModelEntry[] | undefined;
  /** Plain IDs, for a catalogue that carries no entries. */
  models: readonly string[];
}

export function ModelOptions({ entries, models }: ModelOptionsProps) {
  if (entries === undefined || entries.length === 0) {
    return (
      <>
        {models.map((model) => (
          <option key={model} value={model}>
            {modelLabel(model)}
          </option>
        ))}
      </>
    );
  }
  // With OpenAI through a ChatGPT subscription the plan, not the price list,
  // decides what runs: its models come first, the rest are shown but cannot
  // be chosen, so a space never lands on a model every run would fail with.
  if (entries.some((entry) => entry.available === false)) {
    const included = entries.filter((entry) => entry.available !== false);
    const lacking = entries.filter((entry) => entry.available === false);
    return (
      <>
        <optgroup label="In your ChatGPT plan">
          {included.map((entry) => (
            <option key={entry.id} value={entry.id}>
              {modelOptionLabel(entry)}
            </option>
          ))}
        </optgroup>
        <optgroup label="Not in your ChatGPT plan (API key only)">
          {lacking.map((entry) => (
            <option key={entry.id} value={entry.id} disabled>
              {modelOptionLabel(entry)}
            </option>
          ))}
        </optgroup>
      </>
    );
  }
  const current = entries.filter((entry) => entry.current);
  const older = entries.filter((entry) => !entry.current);
  return (
    <>
      {current.length > 0 && (
        <optgroup label="Current models">
          {current.map((entry) => (
            <option key={entry.id} value={entry.id}>
              {modelOptionLabel(entry)}
            </option>
          ))}
        </optgroup>
      )}
      {older.length > 0 && (
        <optgroup label="Older models, still available">
          {older.map((entry) => (
            <option key={entry.id} value={entry.id}>
              {modelOptionLabel(entry)}
            </option>
          ))}
        </optgroup>
      )}
    </>
  );
}
