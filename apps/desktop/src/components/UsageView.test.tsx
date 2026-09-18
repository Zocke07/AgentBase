import type { SpaceResponse, UsageReport } from "@agentspace/schemas";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../lib/api";

import { UsageView } from "./UsageView";

/**
 * The usage section: what it asks the sidecar for, and that every figure it
 * shows is one the report carried, with the run's peak context beside its cost.
 */

vi.mock("../lib/api", () => ({
  getUsage: vi.fn(),
}));

const mocked = vi.mocked(api);

const lab: SpaceResponse = {
  id: "space-lab",
  name: "Lab",
  created_at: "2026-09-12T00:00:00Z",
  updated_at: "2026-09-12T00:00:00Z",
  folder: "/data/spaces/space-lab",
  is_default: false,
};

const report: UsageReport = {
  period: "2026-09",
  periods: ["2026-09", "2026-08"],
  space_id: "space-lab",
  cap_micros: 20_000_000,
  totals: { calls: 3, runs: 2, input_tokens: 4700, output_tokens: 370, cost_micros: 14500, cost_display: "$0.0145" },
  by_model: [
    { key: "anthropic/claude-opus-5", label: "anthropic · claude-opus-5", calls: 2, input_tokens: 4000, output_tokens: 300, cost_micros: 14000, cost_display: "$0.0140" },
    { key: "anthropic/claude-haiku-4-5", label: "anthropic · claude-haiku-4-5", calls: 1, input_tokens: 700, output_tokens: 70, cost_micros: 500, cost_display: "$0.0005" },
  ],
  by_space: [
    { key: "space-lab", label: "Lab", calls: 3, input_tokens: 4700, output_tokens: 370, cost_micros: 14500, cost_display: "$0.0145" },
  ],
  by_day: [
    { key: "2026-09-18", label: "2026-09-18", calls: 2, input_tokens: 1500, output_tokens: 150, cost_micros: 5400, cost_display: "$0.0054" },
    { key: "2026-09-19", label: "2026-09-19", calls: 1, input_tokens: 3200, output_tokens: 220, cost_micros: 9100, cost_display: "$0.0091" },
  ],
  runs: [
    {
      run_id: "run-1",
      space_id: "space-lab",
      goal: "Summarise the quarterly report for the board",
      status: "completed",
      origin: "schedule",
      created_at: "2026-09-19T08:00:00Z",
      calls: 2,
      input_tokens: 4000,
      output_tokens: 300,
      peak_context: 3000,
      mean_context: 2000,
      cost_micros: 14000,
      cost_display: "$0.0140",
    },
    {
      run_id: null,
      space_id: null,
      goal: null,
      status: null,
      origin: null,
      created_at: null,
      calls: 1,
      input_tokens: 700,
      output_tokens: 70,
      peak_context: 700,
      mean_context: 700,
      cost_micros: 500,
      cost_display: "$0.0005",
    },
  ],
};

beforeEach(() => {
  mocked.getUsage.mockResolvedValue(report);
});

describe("UsageView", () => {
  it("asks for this month in this space, and shows the totals, slices and runs", async () => {
    const onOpenRun = vi.fn();
    render(<UsageView space={lab} active onOpenRun={onOpenRun} onOpenSettings={vi.fn()} />);

    await waitFor(() => {
      expect(mocked.getUsage).toHaveBeenCalledWith(null, "space-lab");
    });
    expect((await screen.findByTestId("usage-spent")).textContent).toContain("$0.0145");
    expect(screen.getByTestId("usage-calls").textContent).toContain("3");
    expect(screen.getByTestId("usage-calls").textContent).toContain("across 2 runs");
    expect(screen.getByTestId("usage-input").textContent).toContain("4,700");
    expect(screen.getByTestId("usage-output").textContent).toContain("370");

    const models = screen.getByTestId("usage-models");
    expect(models.textContent).toContain("claude-opus-5");
    expect(models.textContent).toContain("$0.0140");
    // The space table only makes sense across spaces.
    expect(screen.queryByTestId("usage-spaces")).toBeNull();

    const runs = screen.getByTestId("usage-runs");
    const first = within(runs).getAllByRole("row")[1];
    if (first === undefined) throw new Error("no run row");
    expect(first.textContent).toContain("Summarise the quarterly report");
    expect(first.textContent).toContain("from schedule");
    expect(first.textContent).toContain("3,000");
    expect(first.textContent).toContain("2,000 mean");
    expect(runs.textContent).toContain("deleted runs");

    await userEvent.click(within(runs).getByRole("button", { name: /Summarise the quarterly/ }));
    expect(onOpenRun).toHaveBeenCalledWith("run-1");

    expect(screen.getByRole("img", { name: /Spend by day/ }).getAttribute("aria-label")).toContain("2026-09-19 $0.0091");
  });

  it("re-asks for another period and for every space, where the cap and the space table appear", async () => {
    render(<UsageView space={lab} active onOpenRun={vi.fn()} onOpenSettings={vi.fn()} />);
    await screen.findByTestId("usage-spent");

    await userEvent.selectOptions(screen.getByTestId("usage-period"), "2026-08");
    await waitFor(() => {
      expect(mocked.getUsage).toHaveBeenCalledWith("2026-08", "space-lab");
    });

    await userEvent.click(screen.getByRole("button", { name: "All spaces" }));
    await waitFor(() => {
      expect(mocked.getUsage).toHaveBeenCalledWith("2026-08", null);
    });
    expect(screen.getByTestId("usage-spent").textContent).toContain("of the $20.0000 cap");
    expect(screen.getByTestId("usage-spaces").textContent).toContain("Lab");
  });

  it("re-reads the ledger each time the section is opened", async () => {
    const { rerender } = render(<UsageView space={lab} active={false} onOpenRun={vi.fn()} onOpenSettings={vi.fn()} />);
    await waitFor(() => {
      expect(mocked.getUsage).toHaveBeenCalledTimes(1);
    });

    rerender(<UsageView space={lab} active onOpenRun={vi.fn()} onOpenSettings={vi.fn()} />);
    await waitFor(() => {
      expect(mocked.getUsage).toHaveBeenCalledTimes(2);
    });
    rerender(<UsageView space={lab} active={false} onOpenRun={vi.fn()} onOpenSettings={vi.fn()} />);
    rerender(<UsageView space={lab} active onOpenRun={vi.fn()} onOpenSettings={vi.fn()} />);
    await waitFor(() => {
      expect(mocked.getUsage).toHaveBeenCalledTimes(3);
    });
  });

  it("shows the sidecar's refusal", async () => {
    mocked.getUsage.mockRejectedValue(new Error("a period looks like 2026-09"));
    render(<UsageView space={lab} active onOpenRun={vi.fn()} onOpenSettings={vi.fn()} />);

    expect((await screen.findByRole("alert")).textContent).toContain("2026-09");
  });
});
