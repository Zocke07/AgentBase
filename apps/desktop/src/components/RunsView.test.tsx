import type { Event, Run } from "@agentbase/schemas";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../lib/api";
import type { RunStreamHandlers } from "../lib/events";
import * as events from "../lib/events";
import { useRunList } from "../state/runList";
import { useRunStore } from "../state/runStore";
import { twoAgentRun } from "../test/log";

import { RunsView, type RunsViewProps } from "./RunsView";

/**
 * The Runs section: the picker, and when the chrome around a run goes back to
 * the sidecar for fresh facts. Starting a run lives on the Home screen and is
 * tested there; the shell's background poll is tested with the shell.
 *
 * `lib/api` and the SSE client are mocked so the test can hand the stream
 * events one at a time: the thing that distinguishes "this run finished while
 * I watched" from "I opened a run that had finished", which the first version
 * could not tell apart and refetched three endpoints on every picker click and
 * every pass of the scrubber over the terminal event.
 */

vi.mock("../lib/api", () => ({
  listRuns: vi.fn(),
  cancelRun: vi.fn(),
  deleteRun: vi.fn(),
  getRunHistory: vi.fn(),
  resolveApproval: vi.fn(),
  saveKnowledgeNote: vi.fn(),
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
  space_id: "space-main",
  goal: "Summarise the quarterly report",
  status,
  origin: "ui",
  origin_ref: null,
  created_at: "2026-09-10T12:00:00Z",
  finished_at: null,
});

/** The view with the run selection it no longer owns, held the way `App` holds it. */
function Harness(props: Omit<RunsViewProps, "runId" | "onSelectRun" | "onNewRun">) {
  const [runId, setRunId] = useState<string | null>(null);
  return <RunsView {...props} runId={runId} onSelectRun={setRunId} onNewRun={vi.fn()} />;
}

/** The handlers the view attached to the most recent stream. */
let handlers: RunStreamHandlers | null = null;

beforeEach(() => {
  useRunStore.getState().reset();
  useRunList.getState().reset();
  useRunList.setState({ spaceId: "space-main" });
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
    render(<Harness onRunChanged={onRunChanged} pendingApprovals={[]} />);
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
    render(<Harness onRunChanged={onRunChanged} pendingApprovals={[]} />);

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
    render(<Harness onRunChanged={onRunChanged} pendingApprovals={[]} />);
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
    render(<Harness onRunChanged={vi.fn()} pendingApprovals={[]} />);
    await pick(user, "quarterly");

    await deliver(twoAgentRun().slice(0, 3));

    expect(screen.getByTestId("run-list").textContent).toContain("running");
    expect(screen.getByTestId("run-list").textContent).not.toContain("not started");
  });
});

describe("switching runs", () => {
  it("keeps the open run on screen, marked busy, until the next one has loaded", async () => {
    /* Picking another run used to blank the panel for the length of a fetch:
       the store was wiped first and the whole panel remounted. Now the panel
       stays populated and dimmed, its controls disabled, and the picker does
       not borrow the old run's status for the new row. */
    const user = userEvent.setup();
    const log = twoAgentRun();
    mocked.listRuns.mockResolvedValue([
      row("completed"),
      { ...row("pending", "run-2"), goal: "Draft the release notes" },
    ]);
    mocked.getRunHistory.mockResolvedValueOnce(log);
    const onRunChanged = vi.fn();
    render(<Harness onRunChanged={onRunChanged} pendingApprovals={[]} />);
    await pick(user, "quarterly", false);
    await waitFor(() => {
      expect(screen.getByTestId("run-status").textContent).toBe("completed");
    });

    let arrive: (history: Event[]) => void = () => undefined;
    mocked.getRunHistory.mockImplementationOnce(
      () => new Promise((resolve) => { arrive = resolve; }),
    );
    const second = screen.getByRole("button", { name: /release notes/ });
    await user.click(second);
    await waitFor(() => {
      expect(mocked.getRunHistory).toHaveBeenLastCalledWith("run-2");
    });

    // Still the first run's projection, under a busy panel.
    expect(screen.getByTestId("run-status").textContent).toBe("completed");
    expect(screen.getByTestId("run-panel").getAttribute("aria-busy")).toBe("true");
    expect(screen.getByLabelText<HTMLInputElement>("Position in the event log").disabled).toBe(true);
    expect(screen.getByTestId("connection-status").textContent).toContain("loading");
    // The new row wears its own status, not the old head's.
    expect(second.textContent).toContain("not started");
    expect(second.textContent).not.toContain("completed");
    expect(onRunChanged).not.toHaveBeenCalled();

    await act(async () => {
      arrive(log.slice(0, 3));
      await Promise.resolve();
    });
    await waitFor(() => {
      expect(screen.getByTestId("run-status").textContent).toBe("running");
    });
    expect(screen.getByTestId("run-panel").getAttribute("aria-busy")).toBe("false");
  });
});

describe("the picker", () => {
  it("shows the day a run was created, not only the time", async () => {
    mocked.listRuns.mockResolvedValue([row("completed")]);
    render(<Harness onRunChanged={vi.fn()} pendingApprovals={[]} />);

    const item = await screen.findByRole("button", { name: /quarterly/ });
    expect(item.textContent).toMatch(/2026-09-1[01]/);
  });

  it("marks a run that is waiting on an approval, wherever it is", async () => {
    /* `listApprovals` was written for exactly this ("a user who opens the
       window a second after the question was asked would otherwise see
       nothing"), and nothing called it. */
    mocked.listRuns.mockResolvedValue([row("running", "run-discord"), row("completed")]);
    render(<Harness onRunChanged={vi.fn()} pendingApprovals={[APPROVAL]} />);

    const waiting = await screen.findByTestId("run-row-needs-approval-run-discord");
    expect(waiting.textContent).toContain("approval");
    expect(screen.queryByTestId("run-row-needs-approval-run-1")).toBeNull();
  });

  it("offers to load more once the list is as long as it was asked for", async () => {
    const user = userEvent.setup();
    const many = Array.from({ length: 50 }, (_, index) => row("completed", `run-${String(index)}`));
    mocked.listRuns.mockResolvedValue(many);
    render(<Harness onRunChanged={vi.fn()} pendingApprovals={[]} />);

    await user.click(await screen.findByRole("button", { name: "Load more" }));

    await waitFor(() => {
      expect(mocked.listRuns).toHaveBeenLastCalledWith(100, "space-main", undefined);
    });
  });

  it("narrows the list to one origin, from the first page, and widens it again", async () => {
    /* One list with a filter, not three: the sidecar does the narrowing so
       the pages stay whole, and a filter change starts from the first page. */
    const user = userEvent.setup();
    mocked.listRuns.mockResolvedValue([row("completed", "run-1")]);
    render(<Harness onRunChanged={vi.fn()} pendingApprovals={[]} />);
    await screen.findByTestId("run-row-run-1");

    mocked.listRuns.mockResolvedValue([]);
    await user.selectOptions(screen.getByTestId("runs-origin"), "schedule");
    await waitFor(() => {
      expect(mocked.listRuns).toHaveBeenLastCalledWith(50, "space-main", "schedule");
    });
    expect(await screen.findByText("No runs of this kind yet.")).toBeDefined();

    await user.selectOptions(screen.getByTestId("runs-origin"), "");
    await waitFor(() => {
      expect(mocked.listRuns).toHaveBeenLastCalledWith(50, "space-main", undefined);
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
    render(<Harness onRunChanged={vi.fn()} pendingApprovals={[]} />);
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
    render(<Harness onRunChanged={vi.fn()} pendingApprovals={[]} />);
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
    render(<Harness onRunChanged={vi.fn()} pendingApprovals={[]} />);
    await pick(user, "quarterly", false);

    expect(screen.queryByRole("button", { name: "Cancel run" })).toBeNull();
  });

  it("shows the sidecar's refusal beside the button", async () => {
    const user = userEvent.setup();
    mocked.listRuns.mockResolvedValue([row("running")]);
    mocked.cancelRun.mockRejectedValue(new Error("run run-1 is already completed"));
    render(<Harness onRunChanged={vi.fn()} pendingApprovals={[]} />);
    await pick(user, "quarterly");
    await deliver(twoAgentRun().slice(0, 3));

    await user.click(screen.getByRole("button", { name: "Cancel run" }));

    expect((await screen.findByRole("alert")).textContent).toContain("already completed");
  });
});

describe("deleting a run", () => {
  it("offers to delete a finished run, asks first, and closes it once the sidecar has", async () => {
    /* Deleting history is the one irreversible thing this section does, so
       the button asks: the same shape as deleting a space. On a yes, the
       run leaves the picker and the panel, and the meter is told the
       space's spend may have moved. */
    const user = userEvent.setup();
    const onRunChanged = vi.fn();
    mocked.listRuns.mockResolvedValue([row("completed")]);
    mocked.getRunHistory.mockResolvedValue(twoAgentRun());
    mocked.deleteRun.mockImplementation(async () => {
      mocked.listRuns.mockResolvedValue([]);
      await Promise.resolve();
    });
    render(<Harness onRunChanged={onRunChanged} pendingApprovals={[]} />);
    await pick(user, "quarterly", false);
    const listed = mocked.listRuns.mock.calls.length;

    await user.click(screen.getByRole("button", { name: "Delete run…" }));
    expect(mocked.deleteRun).not.toHaveBeenCalled();
    expect(screen.getByText(/Delete this run and its log\?/)).toBeDefined();

    await user.click(screen.getByRole("button", { name: "Delete" }));

    expect(mocked.deleteRun).toHaveBeenCalledWith("run-1");
    await waitFor(() => {
      expect(screen.queryByTestId("run-panel")).toBeNull();
      expect(screen.getByText(/Pick a run/)).toBeDefined();
    });
    expect(mocked.listRuns.mock.calls.length).toBeGreaterThan(listed);
    expect(onRunChanged).toHaveBeenCalled();
    await waitFor(() => {
      expect(screen.queryByRole("button", { name: /quarterly/ })).toBeNull();
    });
  });

  it("backs out on Keep without asking the sidecar", async () => {
    const user = userEvent.setup();
    mocked.listRuns.mockResolvedValue([row("completed")]);
    mocked.getRunHistory.mockResolvedValue(twoAgentRun());
    render(<Harness onRunChanged={vi.fn()} pendingApprovals={[]} />);
    await pick(user, "quarterly", false);

    await user.click(screen.getByRole("button", { name: "Delete run…" }));
    await user.click(screen.getByRole("button", { name: "Keep" }));

    expect(mocked.deleteRun).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Delete run…" })).toBeDefined();
    expect(screen.getByTestId("run-panel")).toBeDefined();
  });

  it("does not offer to delete a run that is still going", async () => {
    /* The sidecar would refuse anyway; the button not being there is what
       stops a person reaching for it while a run they meant to cancel is
       mid-flight. */
    const user = userEvent.setup();
    mocked.listRuns.mockResolvedValue([row("running")]);
    render(<Harness onRunChanged={vi.fn()} pendingApprovals={[]} />);
    await pick(user, "quarterly");
    await deliver(twoAgentRun().slice(0, 3));

    expect(screen.queryByRole("button", { name: /Delete run/ })).toBeNull();
    expect(screen.getByRole("button", { name: "Cancel run" })).toBeDefined();
  });

  it("offers to delete once a watched run ends", async () => {
    const user = userEvent.setup();
    mocked.listRuns.mockResolvedValue([row("running")]);
    render(<Harness onRunChanged={vi.fn()} pendingApprovals={[]} />);
    await pick(user, "quarterly");
    await deliver(twoAgentRun());

    expect(await screen.findByRole("button", { name: "Delete run…" })).toBeDefined();
    expect(screen.queryByRole("button", { name: "Cancel run" })).toBeNull();
  });

  it("shows the sidecar's refusal and keeps the run open", async () => {
    const user = userEvent.setup();
    mocked.listRuns.mockResolvedValue([row("completed")]);
    mocked.getRunHistory.mockResolvedValue(twoAgentRun());
    mocked.deleteRun.mockRejectedValue(new Error("run run-1 is still running; cancel it first"));
    render(<Harness onRunChanged={vi.fn()} pendingApprovals={[]} />);
    await pick(user, "quarterly", false);

    await user.click(screen.getByRole("button", { name: "Delete run…" }));
    await user.click(screen.getByRole("button", { name: "Delete" }));

    expect((await screen.findByRole("alert")).textContent).toContain("cancel it first");
    expect(screen.getByTestId("run-panel")).toBeDefined();
    expect(screen.getByRole("button", { name: "Delete run…" })).toBeDefined();
  });
});

describe("capturing an agent's words as a note", () => {
  it("writes the run's summary under captures/ in the run's space and says where", async () => {
    /* The automatic run memory is app-owned and proposed; a capture is the
       person's own note, so it goes to a folder of its own, keyed on the run
       and the event it came from. */
    const user = userEvent.setup();
    mocked.listRuns.mockResolvedValue([row("completed")]);
    mocked.getRunHistory.mockResolvedValue(twoAgentRun());
    mocked.saveKnowledgeNote.mockResolvedValue({
      path: "captures/run-1-28.md",
      title: "x",
      excerpt: "",
      updated_at: "2026-09-10T12:00:00Z",
      content: "",
    });
    render(<Harness onRunChanged={vi.fn()} pendingApprovals={[]} />);
    await pick(user, "quarterly", false);

    await user.click(screen.getByRole("button", { name: /The run completed\./ }));
    await user.click(screen.getByRole("button", { name: "Save as note" }));

    await waitFor(() => {
      expect(mocked.saveKnowledgeNote).toHaveBeenCalledWith(
        "space-main",
        expect.stringMatching(/^captures\/run-1-\d+\.md$/),
        expect.stringContaining("type: capture"),
      );
    });
    expect(screen.getByTestId("capture-notice").textContent).toContain("Saved captures/run-1-");
  });
});
