import type { Run } from "@agentbase/schemas";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { RunCard } from "./RunCard";

describe("RunCard", () => {
  it("groups schedule metadata separately from an unabridged dynamic goal", () => {
    const run: Run = {
      id: "run-scheduled",
      space_id: "space-main",
      goal: "Collect today's inputs for the ticker list and retain every part of this deliberately long goal",
      status: "completed",
      origin: "schedule",
      origin_ref: "schedule-collect",
      created_at: "2026-09-30T03:00:00Z",
      finished_at: "2026-09-30T03:08:56Z",
    };

    render(<RunCard run={run} onOpen={vi.fn()} />);

    const card = screen.getByTestId("run-card-run-scheduled");
    expect(card.querySelector(".run-card__meta")?.textContent).toContain("from schedule");
    expect(card.querySelector(".run-card__goal")?.textContent).toBe(run.goal);
  });

  it("keeps a compact navigation card short without discarding its full goal", () => {
    const run: Run = {
      id: "run-picker",
      space_id: "space-main",
      goal: "Using today's files, ask every specialist for a complete review and finish with the files written",
      status: "completed",
      origin: "schedule",
      origin_ref: "schedule-review",
      created_at: "2026-09-30T03:07:00Z",
      finished_at: "2026-09-30T03:09:26Z",
    };

    render(<RunCard run={run} compact onOpen={vi.fn()} />);

    const goal = screen.getByTestId("run-row-run-picker").querySelector(".run-card__goal");
    expect(goal?.textContent).toBe(run.goal);
    expect(goal?.getAttribute("title")).toBe(run.goal);
  });

  it("distinguishes Run now from a timed schedule", () => {
    const run: Run = {
      id: "run-now",
      space_id: "space-main",
      goal: "Collect the inputs now",
      status: "completed",
      origin: "automation",
      origin_ref: "schedule-collect",
      created_at: "2026-10-01T02:00:00Z",
      finished_at: "2026-10-01T02:01:00Z",
    };

    render(<RunCard run={run} onOpen={vi.fn()} />);

    expect(screen.getByTestId("run-card-run-now").textContent).toContain("started with Run now");
    expect(screen.getByTestId("run-card-run-now").textContent).not.toContain("from schedule");
  });
});
