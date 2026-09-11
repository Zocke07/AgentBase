import type { Event, Run } from "@agentspace/schemas";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../lib/api";
import type { RunStreamHandlers } from "../lib/events";
import * as events from "../lib/events";
import { useRunStore } from "../state/runStore";
import { twoAgentRun } from "../test/log";

import { RunsView, type RunsViewProps } from "./RunsView";

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
  cancelRun: vi.fn(),
  startDebugRun: vi.fn(),
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

const APPROVAL = {
  id: "ap-9",
  run_id: "run-discord",
  tool: "write_file",
  args: {},
  risk: "medium",
  status: "pending",
  created_at: "2026-09-10T12:00:00Z",
};

const row = (status: Run["status"], id = "run-1"): Run => ({
  id,
  goal: "Summarise the quarterly report",
  status,
  origin: "ui",
  origin_ref: null,
  created_at: "2026-09-10T12:00:00Z",
  finished_at: null,
});

/** The view with the run selection it no longer owns, held the way `App` holds it. */
function Harness(props: Omit<RunsViewProps, "runId" | "onSelectRun" | "onOpenSettings">) {
  const [runId, setRunId] = useState<string | null>(null);
  return <RunsView {...props} runId={runId} onSelectRun={setRunId} onOpenSettings={vi.fn()} />;
}

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
    render(<Harness onRunChanged={onRunChanged} blocker={null} pendingApprovals={[]} />);
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
    render(<Harness onRunChanged={onRunChanged} blocker={null} pendingApprovals={[]} />);

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
    render(<Harness onRunChanged={onRunChanged} blocker={null} pendingApprovals={[]} />);
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
    render(<Harness onRunChanged={vi.fn()} blocker={null} pendingApprovals={[]} />);
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
    render(<Harness onRunChanged={onRunChanged} blocker={null} pendingApprovals={[]} />);
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
    render(<Harness onRunChanged={vi.fn()} blocker={null} pendingApprovals={[]} />);
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
    render(<Harness onRunChanged={onRunChanged} blocker={null} pendingApprovals={[]} />);
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

describe("the picker", () => {
  it("shows the day a run was created, not only the time", async () => {
    mocked.listRuns.mockResolvedValue([row("completed")]);
    render(<Harness onRunChanged={vi.fn()} blocker={null} pendingApprovals={[]} />);

    const item = await screen.findByRole("button", { name: /quarterly/ });
    expect(item.textContent).toMatch(/2026-09-1[01]/);
  });

  it("marks a run that is waiting on an approval, wherever it is", async () => {
    /* `listApprovals` was written for exactly this — "a user who opens the
       window a second after the question was asked would otherwise see
       nothing" — and nothing called it. */
    mocked.listRuns.mockResolvedValue([row("running", "run-discord"), row("completed")]);
    render(<Harness onRunChanged={vi.fn()} blocker={null} pendingApprovals={[APPROVAL]} />);

    const waiting = await screen.findByTestId("run-needs-approval-run-discord");
    expect(waiting.textContent).toContain("approval");
    expect(screen.queryByTestId("run-needs-approval-run-1")).toBeNull();
  });

  it("offers to load more once the list is as long as it was asked for", async () => {
    const user = userEvent.setup();
    const many = Array.from({ length: 50 }, (_, index) => row("completed", `run-${String(index)}`));
    mocked.listRuns.mockResolvedValue(many);
    render(<Harness onRunChanged={vi.fn()} blocker={null} pendingApprovals={[]} />);

    await user.click(await screen.findByRole("button", { name: "Load more" }));

    await waitFor(() => {
      expect(mocked.listRuns).toHaveBeenLastCalledWith(100);
    });
  });
});

describe("cancelling a run", () => {
  it("offers to cancel the selected run while it is going, and asks the sidecar when clicked", async () => {
    /* `run.cancelled` was in the contract and nothing produced it; a runaway
       run could only be stopped by closing the app. */
    const user = userEvent.setup();
    mocked.listRuns.mockResolvedValue([row("running")]);
    mocked.cancelRun.mockResolvedValue(row("running"));
    render(<Harness onRunChanged={vi.fn()} blocker={null} pendingApprovals={[]} />);
    await pick(user, "quarterly");
    await deliver(twoAgentRun().slice(0, 3));

    await user.click(screen.getByRole("button", { name: "Cancel run" }));

    expect(mocked.cancelRun).toHaveBeenCalledWith("run-1");
    // Nothing changes locally: the run says `run.cancelled` over the stream.
    expect(screen.getByTestId("run-status").textContent).toBe("running");
  });

  it("says it is stopping until the run actually ends", async () => {
    /* A cancel is cooperative: the run stops before its *next* model call,
       and on a local model the one in flight can take half a minute. The
       button used to revert to "Cancel run" the moment the request returned,
       which read as though nothing had happened. */
    const user = userEvent.setup();
    mocked.listRuns.mockResolvedValue([row("running")]);
    mocked.cancelRun.mockResolvedValue(row("running"));
    render(<Harness onRunChanged={vi.fn()} blocker={null} pendingApprovals={[]} />);
    await pick(user, "quarterly");
    const log = twoAgentRun();
    await deliver(log.slice(0, 3));

    await user.click(screen.getByRole("button", { name: "Cancel run" }));

    const stopping = await screen.findByRole("button", { name: "Stopping…" });
    expect(stopping).toHaveProperty("disabled", true);

    await deliver(log.slice(3));
    expect(screen.queryByRole("button", { name: /Stopping|Cancel run/ })).toBeNull();
  });

  it("does not offer to cancel a run that has ended", async () => {
    const user = userEvent.setup();
    mocked.listRuns.mockResolvedValue([row("completed")]);
    mocked.getRunHistory.mockResolvedValue(twoAgentRun());
    render(<Harness onRunChanged={vi.fn()} blocker={null} pendingApprovals={[]} />);
    await pick(user, "quarterly", false);

    expect(screen.queryByRole("button", { name: "Cancel run" })).toBeNull();
  });

  it("shows the sidecar's refusal beside the button", async () => {
    const user = userEvent.setup();
    mocked.listRuns.mockResolvedValue([row("running")]);
    mocked.cancelRun.mockRejectedValue(new Error("run run-1 is already completed"));
    render(<Harness onRunChanged={vi.fn()} blocker={null} pendingApprovals={[]} />);
    await pick(user, "quarterly");
    await deliver(twoAgentRun().slice(0, 3));

    await user.click(screen.getByRole("button", { name: "Cancel run" }));

    expect((await screen.findByRole("alert")).textContent).toContain("already completed");
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
      <Harness
        onRunChanged={vi.fn()}
        blocker="No API key for anthropic. Add one in the settings and restart."
        pendingApprovals={[]}
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
    render(<Harness onRunChanged={vi.fn()} blocker={null} pendingApprovals={[]} />);

    await user.type(screen.getByTestId("goal-input"), "do a thing");
    await user.click(screen.getByRole("button", { name: "Start run" }));
    expect((await screen.findByRole("alert")).textContent).toContain("refused");

    await pick(user, "quarterly");

    expect(screen.queryByRole("alert")).toBeNull();
  });
});
