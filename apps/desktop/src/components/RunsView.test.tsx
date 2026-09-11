import type { Event, Run } from "@agentspace/schemas";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../lib/api";
import type { RunStreamHandlers } from "../lib/events";
import * as events from "../lib/events";
import { useRunStore } from "../state/runStore";
import { twoAgentRun } from "../test/log";

import { RunsView } from "./RunsView";

/**
 * The runs tab: the picker, the goal box, and when the chrome around a run
 * goes back to the sidecar for fresh facts.
 *
 * `lib/api` and the SSE client are mocked so the test can hand the stream
 * events one at a time — the thing that distinguishes "this run finished while
 * I watched" from "I opened a run that had finished", which the first version
 * could not tell apart and refetched three endpoints on every picker click and
 * every pass of the scrubber over the terminal event.
 */

vi.mock("../lib/api", () => ({
  listRuns: vi.fn(),
  createRun: vi.fn(),
  getRunHistory: vi.fn(),
  resolveApproval: vi.fn(),
  baseUrl: vi.fn(() => Promise.resolve("http://x")),
}));

// Only the transport is replaced; the module's pure helpers stay real.
vi.mock("../lib/events", async (importOriginal) => ({
  ...(await importOriginal<typeof events>()),
  streamRun: vi.fn(),
}));

const mocked = vi.mocked(api);
const stream = vi.mocked(events.streamRun);

const row = (status: Run["status"], id = "run-1"): Run => ({
  id,
  goal: "Summarise the quarterly report",
  status,
  origin: "ui",
  origin_ref: null,
  created_at: "2026-09-10T12:00:00Z",
  finished_at: null,
});

/** The handlers the view attached to the most recent stream. */
let handlers: RunStreamHandlers | null = null;

beforeEach(() => {
  useRunStore.getState().reset();
  handlers = null;
  stream.mockImplementation((_origin, _runId, attached) => {
    handlers = attached;
    return { close: vi.fn() };
  });
  mocked.getRunHistory.mockResolvedValue([]);
});

/**
 * Deliver events over the mocked stream, as the SSE client would, and wait
 * for the paint on which `useRunStream` hands them to the store.
 */
async function deliver(batch: Event[]) {
  await act(async () => {
    for (const event of batch) handlers?.onEvent(event);
    await new Promise((resolve) => requestAnimationFrame(resolve));
  });
}

/**
 * Pick a run from the list and wait for its panel. A run whose history already
 * ended it opens no stream, so only a live one is waited on for its handlers.
 */
async function pick(user: ReturnType<typeof userEvent.setup>, goal: string, live = true) {
  await user.click(await screen.findByRole("button", { name: new RegExp(goal) }));
  await waitFor(() => {
    expect(screen.getByTestId("run-panel")).toBeDefined();
    if (live) expect(handlers).not.toBeNull();
  });
}

describe("refreshing the picker and the meter", () => {
  it("refetches when a run finishes while being watched", async () => {
    const user = userEvent.setup();
    const onRunChanged = vi.fn();
    mocked.listRuns.mockResolvedValue([row("running")]);
    render(<RunsView onRunChanged={onRunChanged} blocker={null} />);
    await pick(user, "quarterly");
    expect(mocked.listRuns).toHaveBeenCalledTimes(1);

    mocked.listRuns.mockResolvedValue([row("completed")]);
    await deliver(twoAgentRun());

    await waitFor(() => {
      expect(mocked.listRuns).toHaveBeenCalledTimes(2);
    });
    expect(onRunChanged).toHaveBeenCalledTimes(1);
  });

  it("does not refetch when a finished run is merely opened", async () => {
    /* `open()` resets the folded status to "pending" and the history fold sets
       it back to "completed"; keyed on that transition, every click on a past
       run cost `/runs`, `/budget` and `/settings`. */
    const user = userEvent.setup();
    const onRunChanged = vi.fn();
    mocked.listRuns.mockResolvedValue([row("completed")]);
    mocked.getRunHistory.mockResolvedValue(twoAgentRun());
    render(<RunsView onRunChanged={onRunChanged} blocker={null} />);

    await pick(user, "quarterly", false);
    await waitFor(() => {
      expect(screen.getByTestId("run-status").textContent).toBe("completed");
    });

    expect(mocked.listRuns).toHaveBeenCalledTimes(1);
    expect(onRunChanged).not.toHaveBeenCalled();
  });

  it("does not refetch when the scrubber crosses the terminal event", async () => {
    const user = userEvent.setup();
    const onRunChanged = vi.fn();
    mocked.listRuns.mockResolvedValue([row("completed")]);
    const log = twoAgentRun();
    mocked.getRunHistory.mockResolvedValue(log);
    render(<RunsView onRunChanged={onRunChanged} blocker={null} />);
    await pick(user, "quarterly", false);
    await waitFor(() => {
      expect(screen.getByTestId("run-status").textContent).toBe("completed");
    });

    act(() => {
      useRunStore.getState().setCursor(log.length - 1);
    });
    act(() => {
      useRunStore.getState().setCursor(log.length);
    });

    expect(mocked.listRuns).toHaveBeenCalledTimes(1);
    expect(onRunChanged).not.toHaveBeenCalled();
  });

  it("shows the selected run's badge from the log, not from a stale row", async () => {
    /* `POST /runs` returns `pending` and the list is not re-read until the run
       ends, so a live run wore "pending" in the picker for its whole duration. */
    const user = userEvent.setup();
    mocked.listRuns.mockResolvedValue([row("pending")]);
    render(<RunsView onRunChanged={vi.fn()} blocker={null} />);
    await pick(user, "quarterly");

    await deliver(twoAgentRun().slice(0, 3));

    expect(screen.getByTestId("run-list").textContent).toContain("running");
    expect(screen.getByTestId("run-list").textContent).not.toContain("pending");
  });
});

describe("runs that happen elsewhere", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("re-reads the picker and the meter while any listed run is still going", async () => {
    /* A run started from Discord, or one left running in the background, never
       reached the picker until the user started or finished a run of their own,
       and the meter did not move while it spent. */
    vi.useFakeTimers();
    const onRunChanged = vi.fn();
    mocked.listRuns.mockResolvedValue([row("running", "run-discord")]);
    render(<RunsView onRunChanged={onRunChanged} blocker={null} />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(mocked.listRuns).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_000);
    });

    expect(mocked.listRuns).toHaveBeenCalledTimes(2);
    expect(onRunChanged).toHaveBeenCalledTimes(1);
  });

  it("stops polling once every listed run has ended", async () => {
    vi.useFakeTimers();
    mocked.listRuns.mockResolvedValue([row("completed"), row("failed", "run-2")]);
    render(<RunsView onRunChanged={vi.fn()} blocker={null} />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_000);
    });

    expect(mocked.listRuns).toHaveBeenCalledTimes(1);
  });

  it("re-reads everything when the window becomes visible again", async () => {
    /* A setting changed from a browser tab while this window was behind it. */
    const onRunChanged = vi.fn();
    mocked.listRuns.mockResolvedValue([row("completed")]);
    render(<RunsView onRunChanged={onRunChanged} blocker={null} />);
    await screen.findByRole("button", { name: /quarterly/ });

    act(() => {
      document.dispatchEvent(new Event("visibilitychange"));
    });

    await waitFor(() => {
      expect(mocked.listRuns).toHaveBeenCalledTimes(2);
    });
    expect(onRunChanged).toHaveBeenCalledTimes(1);
  });
});

describe("starting a run", () => {
  it("says why a run would be refused, beside the goal box, and does not offer to start one", async () => {
    /* The header said "unpriced — runs will be refused" and the meter said
       "further runs are refused" while the Start button stayed live. Every
       click added a dead `failed` row to the picker, with the reason only in
       the run's own log. */
    const user = userEvent.setup();
    mocked.listRuns.mockResolvedValue([]);
    render(
      <RunsView
        onRunChanged={vi.fn()}
        blocker="No API key for anthropic. Add one in the settings and restart."
      />,
    );

    await user.type(screen.getByTestId("goal-input"), "do a thing");

    expect(screen.getByTestId("preflight").textContent).toContain("No API key for anthropic");
    expect(screen.getByRole("button", { name: "Start run" })).toHaveProperty("disabled", true);
    expect(mocked.createRun).not.toHaveBeenCalled();
  });

  it("clears a failed start's message once another run is picked", async () => {
    const user = userEvent.setup();
    mocked.listRuns.mockResolvedValue([row("completed")]);
    mocked.createRun.mockRejectedValue(new Error("the sidecar refused"));
    render(<RunsView onRunChanged={vi.fn()} blocker={null} />);

    await user.type(screen.getByTestId("goal-input"), "do a thing");
    await user.click(screen.getByRole("button", { name: "Start run" }));
    expect((await screen.findByRole("alert")).textContent).toContain("refused");

    await pick(user, "quarterly");

    expect(screen.queryByRole("alert")).toBeNull();
  });
});
