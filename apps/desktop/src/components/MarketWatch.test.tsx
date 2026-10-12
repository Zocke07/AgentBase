import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../lib/api";

import { MarketWatch } from "./MarketWatch";

vi.mock("../lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof api>()),
  getMonitor: vi.fn(),
  setMonitor: vi.fn(),
}));

const mocked = vi.mocked(api);

beforeEach(() => {
  mocked.setMonitor.mockResolvedValue({ enabled: true });
});

describe("MarketWatch", () => {
  it("is off until turned on, and says what would raise an alert", async () => {
    mocked.getMonitor.mockResolvedValue({ enabled: false, stock_move_pct: 5, stock_jump_pct: 2.5 });
    const onOpenFile = vi.fn();
    render(<MarketWatch spaceId="space-main" onOpenFile={onOpenFile} />);

    expect(await screen.findByText("Off.")).toBeTruthy();
    expect(screen.getByText(/a move of 5% from the previous close, or 2.5% within 15 minutes/)).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Turn on" }));
    expect(mocked.setMonitor).toHaveBeenCalledWith("space-main", true);
    await waitFor(() => {
      expect(mocked.getMonitor).toHaveBeenCalledTimes(2);
    });

    await userEvent.click(screen.getByRole("button", { name: "Change what raises an alert" }));
    expect(onOpenFile).toHaveBeenCalledWith("config/monitor.json");
  });

  it("shows what it watches and when it last looked", async () => {
    mocked.getMonitor.mockResolvedValue({
      enabled: true,
      market_open: true,
      symbols: ["MU", "ORCL", "^GSPC"],
      check_every_minutes: 5,
      last_checked_at: "2026-10-13T15:00:00Z",
      explanations_today: 2,
      max_explanations_per_day: 10,
      problems: ["No quote for CRWV."],
    });
    render(<MarketWatch spaceId="space-main" />);

    expect((await screen.findByTestId("market-watch-state")).textContent).toContain("Checks 3 symbols every 5 minutes.");
    expect(screen.getByText("MU · ORCL · ^GSPC")).toBeTruthy();
    expect(screen.getByText(/at most 10 a day \(2 today\)/)).toBeTruthy();
    expect(screen.getByText("No quote for CRWV.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Turn off" })).toBeTruthy();
  });

  it("names a settings file it cannot use", async () => {
    mocked.getMonitor.mockResolvedValue({ enabled: false, error: "config/monitor.json is not valid JSON" });
    render(<MarketWatch spaceId="space-main" />);
    expect((await screen.findByRole("alert")).textContent).toContain("not valid JSON");
  });
});
