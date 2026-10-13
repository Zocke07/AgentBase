import type { ScheduleResponse, SpaceResponse } from "@agentbase/schemas";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../lib/api";

import { AutomationsView } from "./AutomationsView";

/**
 * The market watch and the investment pipeline's offer belong to the default
 * space (2026-10-13); another space's Automations is its schedules alone.
 */

vi.mock("../lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof api>()),
  listSchedules: vi.fn(),
  getMonitor: vi.fn(),
}));

const mocked = vi.mocked(api);

function space(id: string, isDefault: boolean): SpaceResponse {
  return {
    id,
    name: isDefault ? "Main" : "Lab",
    description: "",
    provider: null,
    model: null,
    auto_approve: null,
    max_steps_per_agent: null,
    max_agents_per_run: null,
    max_run_seconds: null,
    archived: false,
    created_at: "2026-10-13T00:00:00Z",
    updated_at: "2026-10-13T00:00:00Z",
    folder: `/data/spaces/${id}`,
    is_default: isDefault,
  };
}

/** One of migration 019's seeded pipeline stages, still switched off. */
const morning: ScheduleResponse = {
  id: "a7e2c1d0-5b3f-4c6a-9e81-0f4d2b7c9a11",
  space_id: "space-main",
  name: "Morning collection",
  goal: "Collect.",
  cadence: { kind: "weekly", at: "07:00", weekdays: [1, 2, 3, 4, 5] },
  missed: "run_on_launch",
  enabled: false,
  next_run_at: null,
  last_run_at: null,
  last_run_id: null,
  last_outcome: null,
  created_at: "2026-10-13T00:00:00Z",
  updated_at: "2026-10-13T00:00:00Z",
} as ScheduleResponse;

beforeEach(() => {
  vi.clearAllMocks();
  mocked.listSchedules.mockResolvedValue([]);
  mocked.getMonitor.mockResolvedValue({ enabled: false, stock_move_pct: 5, stock_jump_pct: 2.5 });
});

describe("AutomationsView", () => {
  it("shows the market watch in the default space", async () => {
    render(<AutomationsView space={space("space-main", true)} settings={null} />);

    expect(await screen.findByTestId("market-watch")).toBeTruthy();
    expect(mocked.getMonitor).toHaveBeenCalledWith("space-main");
  });

  it("leaves the market watch and the pipeline offer out of another space", async () => {
    // Even a stage with the pipeline's id, were one listed, offers nothing here.
    mocked.listSchedules.mockResolvedValue([{ ...morning, space_id: "space-lab" }]);
    render(<AutomationsView space={space("space-lab", false)} settings={null} />);

    await waitFor(() => {
      expect(mocked.listSchedules).toHaveBeenCalledWith("space-lab");
    });
    await screen.findByText("Morning collection");
    expect(screen.queryByTestId("market-watch")).toBeNull();
    expect(screen.queryByTestId("pipeline-offer")).toBeNull();
    expect(mocked.getMonitor).not.toHaveBeenCalled();
  });
});
