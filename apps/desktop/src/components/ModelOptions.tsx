import type { ModelEntry } from "@agentbase/schemas";

import { modelLabel, modelOptionLabel } from "../lib/format";

/**
 * A provider's models as `<option>`s: the current lineup first, older models
 * still sold after it, each with its tier and price, so a choice does not
 * need a pricing page open beside it. The catalogue decides the order.
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
