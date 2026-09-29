import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { perMillion } from "../lib/format";

import { ModelOptions } from "./ModelOptions";

/**
 * A model picker's options: the current lineup first, each with where it sits
 * and what it costs, so the choice needs no pricing page beside it.
 */

const entry = (id: string, tier: "frontier" | "strong" | "balanced" | "fast", current: boolean, input: number, output: number) => ({
  id,
  tier,
  current,
  input_micros_per_million: input,
  output_micros_per_million: output,
});

function options(element: React.ReactElement) {
  const { container } = render(<select>{element}</select>);
  return container;
}

describe("ModelOptions", () => {
  it("puts the current lineup first, then older models, each with tier and price", () => {
    const container = options(
      <ModelOptions
        entries={[
          entry("claude-opus-5-5", "strong", true, 4_000_000, 20_000_000),
          entry("claude-haiku-4-5", "fast", true, 1_000_000, 5_000_000),
          entry("claude-opus-5", "strong", false, 5_000_000, 25_000_000),
        ]}
        models={[]}
      />,
    );

    const groups = [...container.querySelectorAll("optgroup")].map((group) => group.label);
    expect(groups).toEqual(["Current models", "Older models, still available"]);
    const first = container.querySelector("option");
    expect(first?.value).toBe("claude-opus-5-5");
    expect(first?.textContent).toBe("Claude Opus 5.5 · high · $4 in / $20 out");
  });

  it("falls back to plain names for a catalogue without entries", () => {
    const container = options(<ModelOptions entries={undefined} models={["gpt-6-sol"]} />);

    expect(container.querySelector("optgroup")).toBeNull();
    expect(container.querySelector("option")?.textContent).toBe("GPT-6 Sol");
  });

  it("shows cents only when there are some", () => {
    expect(perMillion(4_000_000)).toBe("$4");
    expect(perMillion(100_000)).toBe("$0.10");
    expect(perMillion(1_250_000)).toBe("$1.25");
  });

  it("puts a ChatGPT plan's models first and shows the rest as unavailable", () => {
    const container = options(
      <ModelOptions
        entries={[
          { ...entry("gpt-6-astra", "frontier", true, 10_000_000, 50_000_000), available: true },
          { ...entry("gpt-6-sol", "balanced", true, 2_000_000, 10_000_000), available: false },
          { ...entry("gpt-5.6-sol", "strong", false, 4_000_000, 20_000_000), available: true },
        ]}
        models={[]}
      />,
    );

    const groups = [...container.querySelectorAll("optgroup")].map((group) => group.label);
    expect(groups).toEqual(["In your ChatGPT plan", "Not in your ChatGPT plan (API key only)"]);
    const sol = container.querySelector<HTMLOptionElement>('option[value="gpt-6-sol"]');
    expect(sol?.disabled).toBe(true);
    expect(container.querySelector<HTMLOptionElement>('option[value="gpt-5.6-sol"]')?.disabled).toBe(false);
  });
});
