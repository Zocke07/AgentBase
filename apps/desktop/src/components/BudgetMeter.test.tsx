import type { UsageReport } from "@agentbase/schemas";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../lib/api";

import { BudgetMeter } from "./BudgetMeter";

vi.mock("../lib/api", () => ({ getUsage: vi.fn() }));

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

    expect(screen.getByTestId("budget-meter").textContent).toContain("will not start");
    expect(screen.getByRole("meter").getAttribute("aria-valuenow")).toBe("140");
    const fill = document.querySelector<HTMLElement>(".budget__fill");
    expect(fill?.style.width).toBe("100%");
  });

  it("reads at a glance, and keeps the ledger's exact figures one hover away", () => {
    /* §5 Phase 3: money is integer micros and the exact rounding rule lives in
       one place, the backend's display strings, which the tooltip carries.
       The glance is whole cents from the same integer micros. */
    render(<BudgetMeter budget={budget(50)} />);

    const meter = screen.getByTestId("budget-meter");
    expect(meter.textContent).toContain("$10 of $20");
    expect(meter.textContent).toContain("this month");
    expect(meter.getAttribute("title")).toContain("$10.0000 of your $20.0000 monthly limit");
  });
});

const bucket = (key: string, label: string, cost: number) => ({
  key,
  label,
  calls: 3,
  input_tokens: 1000,
  output_tokens: 200,
  cost_micros: cost,
  cost_display: `$${(cost / 1_000_000).toFixed(4)}`,
});

const report: UsageReport = {
  period: "2026-09",
  periods: ["2026-09"],
  space_id: null,
  cap_micros: 20_000_000,
  totals: { calls: 12, runs: 4, input_tokens: 9000, output_tokens: 2000, cost_micros: 10_000_000, cost_display: "$10.0000" },
  by_model: [
    bucket("anthropic/claude-haiku-4-5", "anthropic · claude-haiku-4-5", 1_000_000),
    bucket("anthropic/claude-opus-5-5", "anthropic · claude-opus-5-5", 7_000_000),
    bucket("anthropic/claude-sonnet-5", "anthropic · claude-sonnet-5", 1_500_000),
    bucket("openai/gpt-6-sol", "openai · gpt-6-sol", 500_000),
  ],
  by_space: [bucket("space-main", "Main", 10_000_000)],
  by_day: [],
  runs: [],
};

describe("the breakdown", () => {
  beforeEach(() => {
    vi.mocked(api.getUsage).mockResolvedValue(report);
  });

  it("opens from the chip with where the month's money went", async () => {
    const user = userEvent.setup();
    render(
      <BudgetMeter
        budget={{ ...budget(50), space_spent_micros: 2_500_000, space_spent_display: "$2.5000" }}
        spaceName="Main"
        runLimitMicros={2_000_000}
      />,
    );
    const toggle = screen.getByRole("button", { name: /spent this month/ });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");

    await user.click(toggle);

    const panel = screen.getByRole("dialog", { name: "Spending this month" });
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    expect(panel.textContent).toContain("$10 left");
    expect(panel.textContent).toContain("In Main$2.50");
    expect(panel.textContent).toContain("Limit per run$2");
    const models = await screen.findByTestId("cost-by-model");
    // Largest first, by the model's own name, three of them and a count of the rest.
    expect([...models.querySelectorAll(".cost-panel__name")].map((cell) => cell.textContent)).toEqual([
      "Claude Opus 5.5",
      "Claude Sonnet 5",
      "Claude Haiku 4.5",
    ]);
    expect(models.textContent).toContain("and 1 more");
    expect(panel.textContent).toContain("about $2.50 each");
    expect(api.getUsage).toHaveBeenCalledWith("2026-09", null);
  });

  it("closes on Escape and hands focus back to the chip", async () => {
    const user = userEvent.setup();
    render(<BudgetMeter budget={budget(50)} />);
    const toggle = screen.getByRole("button", { name: /spent this month/ });
    await user.click(toggle);
    expect(screen.getByRole("dialog")).toBeDefined();

    await user.keyboard("{Escape}");

    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(toggle);
  });

  it("goes to Usage or the limits, closing itself on the way", async () => {
    const user = userEvent.setup();
    const onOpenUsage = vi.fn();
    render(<BudgetMeter budget={budget(50)} onOpenUsage={onOpenUsage} onOpenSettings={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: /spent this month/ }));

    await user.click(screen.getByRole("button", { name: "See all usage" }));

    expect(onOpenUsage).toHaveBeenCalledOnce();
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).toBeNull();
    });
  });

  it("says so when the breakdown cannot be read, and keeps the month's figures", async () => {
    vi.mocked(api.getUsage).mockRejectedValue(new Error("GET /usage: HTTP 500"));
    const user = userEvent.setup();
    render(<BudgetMeter budget={budget(50)} />);
    await user.click(screen.getByRole("button", { name: /spent this month/ }));

    expect((await screen.findByRole("alert")).textContent).toContain("HTTP 500");
    expect(screen.getByRole("dialog").textContent).toContain("of your $20 monthly limit");
  });
});
