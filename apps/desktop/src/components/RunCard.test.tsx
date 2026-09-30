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
});
