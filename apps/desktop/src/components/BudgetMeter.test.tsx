import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { BudgetMeter } from "./BudgetMeter";

/**
 * The month's spend against the cap. The one panel that is not a projection
 * of a run's log (the cap spans every run in the month) and the thresholds
 * are the ledger's: warn at 80%, refuse at 100%.
 */

const budget = (percent: number) => ({
  period: "2026-09",
  spent_micros: percent * 200_000,
  cap_micros: 20_000_000,
  percent_used: percent,
  spent_display: `$${(percent * 0.2).toFixed(4)}`,
  cap_display: "$20.0000",
});

describe("BudgetMeter", () => {
  it("shows a placeholder until the budget has been read", () => {
    render(<BudgetMeter budget={null} />);

    expect(screen.getByTestId("budget-meter").textContent).toContain("-");
  });

  it.each([
    [10, "ok"],
    [79, "ok"],
    [80, "warn"],
    [99, "warn"],
    [100, "over"],
    [140, "over"],
  ])("at %i%% reads as %s", (percent, level) => {
    render(<BudgetMeter budget={budget(percent)} />);

    expect(screen.getByTestId("budget-meter").className).toContain(`budget--${level}`);
  });

  it("says further runs are refused once the cap is reached, and never overfills the bar", () => {
    render(<BudgetMeter budget={budget(140)} />);

    expect(screen.getByTestId("budget-meter").textContent).toContain("refused");
    expect(screen.getByRole("meter").getAttribute("aria-valuenow")).toBe("140");
    const fill = document.querySelector<HTMLElement>(".budget__fill");
    expect(fill?.style.width).toBe("100%");
  });

  it("renders the backend's own money strings rather than formatting micros itself", () => {
    /* §5 Phase 3: money is integer micros and the rounding rule lives in one
       place. A second, floating-point opinion on screen is what this avoids. */
    render(<BudgetMeter budget={budget(50)} />);

    expect(screen.getByTestId("budget-meter").textContent).toContain("$10.0000 / $20.0000");
  });
});
