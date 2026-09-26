import { describe, expect, it } from "vitest";

import { clockDate, formatDuration, modelLabel, moneyShort, providerLabel } from "./format";

describe("formatDuration", () => {
  it.each([
    [0, "0s"],
    [27_000, "27s"],
    [92_000, "1m 32s"],
    [3_600_000, "1h 0m"],
    [5_025_000, "1h 23m"],
  ])("renders %i ms as %s", (ms, expected) => {
    expect(formatDuration(ms)).toBe(expected);
  });
});

describe("clockDate", () => {
  it("shows the day as well as the time, so yesterday's run is not today's", () => {
    /* The picker used to show `14:32:05` for a run from last week. */
    const rendered = clockDate("2026-09-10T12:00:05Z");
    expect(rendered).toMatch(/2026-09-1[01]/);
    expect(rendered).toMatch(/\d\d:\d\d/);
  });

  it("renders nonsense as a placeholder rather than throwing", () => {
    expect(clockDate("not a date")).toBe("-");
  });
});

describe("labels a person reads", () => {
  it("rounds money to cents, and drops the cents from a round figure", () => {
    expect(moneyShort(20_000_000)).toBe("$20");
    expect(moneyShort(52_400)).toBe("$0.05");
    expect(moneyShort(0)).toBe("$0");
    expect(moneyShort(1_234_567)).toBe("$1.23");
  });

  it("names models the way their makers do", () => {
    expect(modelLabel("claude-opus-5")).toBe("Claude Opus 5");
    expect(modelLabel("claude-haiku-4-5")).toBe("Claude Haiku 4.5");
    expect(modelLabel("claude-haiku-4-5-20251001")).toBe("Claude Haiku 4.5");
    expect(modelLabel("gpt-5.5")).toBe("GPT-5.5");
    expect(modelLabel("gpt-5.4-mini")).toBe("GPT-5.4 mini");
    expect(modelLabel("gpt-4o")).toBe("GPT-4o");
    expect(modelLabel("qwen3:4b")).toBe("qwen3:4b");
    expect(providerLabel("openai")).toBe("OpenAI");
  });
});
