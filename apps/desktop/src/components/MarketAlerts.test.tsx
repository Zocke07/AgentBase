import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { marketAlert } from "../test/alerts";

import { MarketAlerts } from "./MarketAlerts";

describe("MarketAlerts", () => {
  it("shows nothing until an alert has fired", () => {
    const { container } = render(<MarketAlerts alerts={[]} fresh={new Set()} />);
    expect(container.textContent).toBe("");
  });

  it("lists each check's moves with the reason found, and opens its sources and run", async () => {
    const onOpenNote = vi.fn();
    const onOpenRun = vi.fn();
    const explained = marketAlert({ explanation_status: "done", explanation: "A broker downgrade at 10:40." });
    const index = marketAlert({
      id: "alert-2",
      symbol: "^IXIC",
      name: "NASDAQ Composite",
      instrument: "index",
      change_pct: -1.6,
      price: 18123.5,
      explanation_status: "done",
      explanation: "A broker downgrade at 10:40.",
    });
    render(
      <MarketAlerts
        alerts={[explained, index]}
        fresh={new Set(["alert-1"])}
        onOpenNote={onOpenNote}
        onOpenRun={onOpenRun}
      />,
    );

    const list = screen.getByTestId("market-alerts");
    expect(list.textContent).toContain("MU ▼ 5.50%");
    expect(list.textContent).toContain("since the previous close, at 94.5 USD");
    expect(list.textContent).toContain("^IXIC ▼ 1.60%");
    expect(list.textContent).not.toContain("18,123.5 USD");
    expect(list.textContent).toContain("Likely reason: A broker downgrade at 10:40.");
    expect(within(list).getByText("New")).toBeTruthy();
    // The market's clock beside the reader's own: 15:00 UTC is 11:00 in New York.
    expect(list.textContent).toMatch(/11:00\sAM New York/);

    await userEvent.click(screen.getByRole("button", { name: "Read the sources" }));
    expect(onOpenNote).toHaveBeenCalledWith("alerts/2026-10-13-1100.md");
    await userEvent.click(screen.getByRole("button", { name: "Open its run" }));
    expect(onOpenRun).toHaveBeenCalledWith("run-9");
  });

  it("says why an alert has no reason yet", () => {
    render(
      <MarketAlerts
        alerts={[marketAlert({ explanation_status: "skipped", explanation_run_id: null })]}
        fresh={new Set()}
      />,
    );
    expect(screen.getByText(/today's explanation limit was reached/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Open its run" })).toBeNull();
  });
});
