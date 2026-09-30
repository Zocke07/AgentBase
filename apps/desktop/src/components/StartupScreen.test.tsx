import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { StartupScreen } from "./StartupScreen";

/**
 * The start screen says what AgentBase is waiting on, in words, and never how
 * many times it has asked.
 */

const connecting = { kind: "connecting" as const, attempt: 40 };
const ready = { kind: "ready" as const, health: { ok: true, instance: null }, baseUrl: "http://x" };

function screenWith(status: Parameters<typeof StartupScreen>[0]["status"], loaded = { settings: false, spaces: false }) {
  return render(
    <StartupScreen status={status} settingsLoaded={loaded.settings} spacesLoaded={loaded.spaces} onRetry={vi.fn()} />,
  );
}

const stageText = () => screen.getByTestId("startup-stages").textContent;

describe("the stages", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("marks the engine done and the reads in progress once the engine answers", () => {
    screenWith(ready, { settings: true, spaces: false });

    const mark = screen.getByTestId("brand-mark");
    expect(mark.querySelectorAll("circle")).toHaveLength(3);
    expect(mark.querySelector("path")).toBeTruthy();
    expect(stageText()).toContain("Starting the engine: done");
    expect(stageText()).toContain("Checking your settings: done");
    expect(stageText()).toContain("Loading your spaces: in progress");
    expect(screen.getByRole("progressbar").getAttribute("aria-valuenow")).toBe("2");
  });

  it("says a slow first start is normal, only once it has been slow", () => {
    /* A cold first launch unpacks the engine, and under macOS translocation
       that has taken nearly two minutes. A spinner alone for that long reads
       as a hang. */
    screenWith(connecting);
    expect(stageText()).not.toContain("minute");

    act(() => {
      vi.advanceTimersByTime(6_000);
    });

    expect(stageText()).toContain("The first start after installing or updating can take a minute or two.");
    expect(stageText()).not.toContain("40");
  });

  it("says when an earlier AgentBase still holds on", () => {
    screenWith({ ...connecting, blocked: true });

    expect(stageText()).toContain("Waiting for an earlier AgentBase to finish closing.");
  });

  it("marks the engine failed and offers another try, with the cause folded away", () => {
    screenWith({ kind: "failed", message: "Failed to fetch", baseUrl: "http://127.0.0.1:8787" });

    expect(stageText()).toContain("Starting the engine: failed");
    expect(screen.getByRole("alert").textContent).toContain("could not start its engine");
    expect(screen.getByText("Technical details")).toBeDefined();
    expect(screen.getByRole("button", { name: "Try again" })).toBeDefined();
  });
});
