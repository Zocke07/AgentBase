import type { PortfolioResponse } from "@agentbase/schemas";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../lib/api";

import { PortfolioEditor } from "./PortfolioEditor";

vi.mock("../lib/api", () => ({ getPortfolio: vi.fn(), savePortfolio: vi.fn() }));
const mocked = vi.mocked(api);
let space = 0;
const data = (): PortfolioResponse => ({
  portfolio: { currency: "USD", cash: "2500.125", holdings: [{ ticker: "MU", shares: "1", cost_per_share: null, opened: null, sector: "Technology", company_name: "Micron", industry: "Semiconductors", exchange: "US" }], watchlist: [], limits: { max_position_pct: "10", max_sector_pct: "70", max_daily_loss_pct: "3" } }, revision: "initial",
});

beforeEach(() => { vi.clearAllMocks(); mocked.getPortfolio.mockResolvedValue(data()); });

async function open(props: Partial<Parameters<typeof PortfolioEditor>[0]> = {}) {
  const spaceId = `portfolio-test-${String(++space)}`;
  const rendered = render(<PortfolioEditor spaceId={spaceId} {...props} />);
  await userEvent.click(await screen.findByRole("button", { name: "Edit portfolio" }));
  return { ...rendered, spaceId };
}

describe("personal portfolio editing", () => {
  it("loads once with a refresh nonce and ignores an older request that finishes late", async () => {
    let resolveFirst: (value: PortfolioResponse) => void = () => undefined;
    let resolveSecond: (value: PortfolioResponse) => void = () => undefined;
    mocked.getPortfolio.mockReturnValueOnce(new Promise((resolve) => { resolveFirst = resolve; }));
    mocked.getPortfolio.mockReturnValueOnce(new Promise((resolve) => { resolveSecond = resolve; }));
    render(<PortfolioEditor spaceId={`portfolio-test-${String(++space)}`} reloadNonce={1} />);
    await waitFor(() => { expect(mocked.getPortfolio).toHaveBeenCalledTimes(1); });
    act(() => { window.dispatchEvent(new Event("focus")); });
    await act(async () => { resolveSecond({ ...data(), portfolio: { ...data().portfolio, cash: "777" } }); await Promise.resolve(); });
    await userEvent.click(await screen.findByRole("button", { name: "Edit portfolio" }));
    await userEvent.clear(screen.getByLabelText("Cash available to invest"));
    await userEvent.type(screen.getByLabelText("Cash available to invest"), "888");
    await act(async () => { resolveFirst(data()); await Promise.resolve(); });
    expect(screen.getByLabelText<HTMLInputElement>("Cash available to invest").value).toBe("888");
  });

  it("a pending save cannot discard newer edits made after switching spaces", async () => {
    const user = userEvent.setup();
    let resolveSave: (value: PortfolioResponse) => void = () => undefined;
    mocked.savePortfolio.mockReturnValueOnce(new Promise((resolve) => { resolveSave = resolve; }));
    const view = await open();
    await user.clear(screen.getByLabelText("Cash available to invest"));
    await user.type(screen.getByLabelText("Cash available to invest"), "3000");
    await user.click(screen.getByRole("button", { name: "Save portfolio" }));
    view.unmount();
    const returned = render(<PortfolioEditor spaceId={view.spaceId} />);
    await user.clear(screen.getByLabelText("Cash available to invest"));
    await user.type(screen.getByLabelText("Cash available to invest"), "4000");
    await act(async () => { resolveSave({ ...data(), portfolio: { ...data().portfolio, cash: "3000" }, revision: "saved-first" }); await Promise.resolve(); });
    returned.unmount();
    render(<PortfolioEditor spaceId={view.spaceId} />);
    expect(screen.getByLabelText<HTMLInputElement>("Cash available to invest").value).toBe("4000");
    mocked.savePortfolio.mockImplementation((_id, body) => Promise.resolve({ ...body, revision: "saved-second" }));
    await user.click(screen.getByRole("button", { name: "Save portfolio" }));
    await screen.findByText("Portfolio saved. Upcoming runs will use these details.");
    expect(mocked.savePortfolio.mock.calls[1]?.[1].revision).toBe("saved-first");
  });
  it("loads existing data without saving and leaves unknown costs blank", async () => {
    await open();
    expect(screen.getByLabelText<HTMLInputElement>("Cash available to invest").value).toBe("2500.125");
    expect(screen.getByLabelText<HTMLInputElement>("Average purchase price (optional)").value).toBe("");
    expect(screen.getByLabelText<HTMLInputElement>("First purchase date (optional)").value).toBe("");
    expect(mocked.savePortfolio).not.toHaveBeenCalled();
  });

  it("saves edited holdings, precise amounts, limits and watched stocks using the loaded revision", async () => {
    const user = userEvent.setup();
    const onSaved = vi.fn();
    mocked.savePortfolio.mockImplementation((_id, body) => Promise.resolve({ ...body, revision: "saved" }));
    const { spaceId } = await open({ onSaved });
    await user.clear(screen.getByLabelText("Number of shares"));
    await user.type(screen.getByLabelText("Number of shares"), "2.123456789");
    await user.clear(screen.getByLabelText("Maximum in one sector (%)"));
    await user.type(screen.getByLabelText("Maximum in one sector (%)"), "65");
    await user.click(screen.getByRole("button", { name: "Add watched stock" }));
    const watched = within(screen.getByRole("group", { name: "Watched stock 1" }));
    await user.type(watched.getByLabelText("Ticker"), "MSFT");
    await user.click(screen.getByRole("button", { name: "Save portfolio" }));
    await screen.findByText("Portfolio saved. Upcoming runs will use these details.");
    const [savedSpace, savedBody] = mocked.savePortfolio.mock.calls[0] ?? [];
    expect(savedSpace).toBe(spaceId);
    expect(savedBody?.revision).toBe("initial");
    expect(savedBody?.portfolio.cash).toBe("2500.125");
    expect(savedBody?.portfolio.holdings[0]?.shares).toBe("2.123456789");
    expect(savedBody?.portfolio.holdings[0]?.cost_per_share).toBeNull();
    expect(savedBody?.portfolio.holdings[0]?.industry).toBe("Semiconductors");
    expect(savedBody?.portfolio.watchlist[0]?.ticker).toBe("MSFT");
    expect(savedBody?.portfolio.limits.max_sector_pct).toBe("65");
    expect(onSaved).toHaveBeenCalledOnce();
  });

  it("adds and removes holdings without altering saved data until Save", async () => {
    const user = userEvent.setup();
    await open();
    await user.click(screen.getByRole("button", { name: "Add holding" }));
    expect(screen.getByRole("group", { name: "Holding 2" })).not.toBeNull();
    await user.click(screen.getByRole("button", { name: "Remove holding 1" }));
    expect(screen.queryByRole("group", { name: "Holding 1: MU" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    await user.click(screen.getByRole("button", { name: "Edit portfolio" }));
    expect(screen.getByRole("group", { name: "Holding 1: MU" })).not.toBeNull();
    expect(mocked.savePortfolio).not.toHaveBeenCalled();
  });

  it("keeps the draft after a failed or stale save", async () => {
    const user = userEvent.setup();
    mocked.savePortfolio.mockRejectedValue(new Error("Your portfolio changed. Reload before saving."));
    await open();
    await user.clear(screen.getByLabelText("Cash available to invest"));
    await user.type(screen.getByLabelText("Cash available to invest"), "3000");
    await user.click(screen.getByRole("button", { name: "Save portfolio" }));
    await screen.findByText("Your portfolio changed. Reload before saving.");
    expect(screen.getByLabelText<HTMLInputElement>("Cash available to invest").value).toBe("3000");
    expect(screen.getByRole("button", { name: "Reload and discard edits" })).not.toBeNull();
  });

  it("retains unsaved edits when returning to the same space", async () => {
    const user = userEvent.setup();
    const view = await open();
    await user.clear(screen.getByLabelText("Cash available to invest"));
    await user.type(screen.getByLabelText("Cash available to invest"), "777");
    view.unmount();
    render(<PortfolioEditor spaceId={view.spaceId} />);
    expect(screen.getByLabelText<HTMLInputElement>("Cash available to invest").value).toBe("777");
    expect(mocked.getPortfolio).toHaveBeenCalledTimes(1);
  });

  it("warns before closing even when the unsaved draft belongs to another space", async () => {
    const user = userEvent.setup();
    const view = await open();
    await user.clear(screen.getByLabelText("Cash available to invest"));
    await user.type(screen.getByLabelText("Cash available to invest"), "777");
    view.unmount();
    render(<PortfolioEditor spaceId={`portfolio-test-${String(++space)}`} />);
    await screen.findByRole("button", { name: "Edit portfolio" });
    const leaving = new Event("beforeunload", { cancelable: true });
    act(() => { window.dispatchEvent(leaving); });
    expect(leaving.defaultPrevented).toBe(true);
  });

  it("shows load failures without an editable empty form and offers a retry", async () => {
    mocked.getPortfolio.mockRejectedValueOnce(new Error("Invalid positions data"));
    render(<PortfolioEditor spaceId={`portfolio-test-${String(++space)}`} />);
    await screen.findByText("Invalid positions data");
    expect(screen.queryByRole("button", { name: "Edit portfolio" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    await screen.findByRole("button", { name: "Edit portfolio" });
  });

  it("allows preparing edits but prevents saving while a run is active", async () => {
    await open({ running: true });
    expect(screen.getByLabelText<HTMLInputElement>("Cash available to invest").disabled).toBe(false);
    expect(screen.getByRole<HTMLButtonElement>("button", { name: "Save portfolio" }).disabled).toBe(true);
    await waitFor(() => { expect(mocked.savePortfolio).not.toHaveBeenCalled(); });
  });
});
