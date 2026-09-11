import type { Run } from "@agentspace/schemas";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";
import * as api from "./lib/api";
import * as events from "./lib/events";
import * as sidecar from "./lib/sidecar";
import { useRoster } from "./state/roster";
import { useRunList } from "./state/runList";
import { useRunStore } from "./state/runStore";

/**
 * The shell: which section is showing, what survives switching, and when the
 * lists more than one section shows are re-read.
 */

vi.mock("./lib/sidecar", () => ({
  connectWithRetry: vi.fn(),
}));

vi.mock("./lib/api", () => ({
  onTransportFailure: vi.fn(() => () => undefined),
  listRuns: vi.fn(),
  createRun: vi.fn(),
  startDebugRun: vi.fn(),
  updateAgent: vi.fn(),
  getRunHistory: vi.fn(),
  getBudget: vi.fn(),
  getSettings: vi.fn(),
  verifySettings: vi.fn(),
  listApprovals: vi.fn(),
  getChannels: vi.fn(),
  updateSettings: vi.fn(),
  listAgents: vi.fn(),
  listTools: vi.fn(),
  listProviders: vi.fn(),
  baseUrl: vi.fn(() => Promise.resolve("http://x")),
}));

// Only the transport is replaced; the module's pure helpers stay real.
vi.mock("./lib/events", async (importOriginal) => ({
  ...(await importOriginal<typeof events>()),
  streamRun: vi.fn(),
}));

const mocked = vi.mocked(api);

const row = (status: Run["status"], id = "run-1"): Run => ({
  id,
  goal: "Summarise the quarterly report",
  status,
  origin: "ui",
  origin_ref: null,
  created_at: "2026-09-10T12:00:00Z",
  finished_at: null,
});

beforeEach(() => {
  useRunStore.getState().reset();
  useRunList.getState().reset();
  useRoster.getState().reset();
  vi.mocked(sidecar.connectWithRetry).mockImplementation((onStatus) => {
    onStatus({ kind: "ready", health: { ok: true }, baseUrl: "http://x" });
    return Promise.resolve();
  });
  vi.mocked(events.streamRun).mockReturnValue({ close: vi.fn() });
  mocked.getBudget.mockRejectedValue(new Error("not in this test"));
  mocked.getSettings.mockRejectedValue(new Error("not in this test"));
  mocked.verifySettings.mockResolvedValue({ ok: true, provider: "ollama", model: "qwen3:4b" });
  mocked.listApprovals.mockResolvedValue([]);
  mocked.getChannels.mockResolvedValue([]);
  mocked.listAgents.mockResolvedValue([]);
  mocked.listTools.mockResolvedValue([]);
  mocked.listProviders.mockResolvedValue({ providers: [], models: {} });
  mocked.getRunHistory.mockResolvedValue([]);
  mocked.listRuns.mockResolvedValue([row("running")]);
});

describe("pre-flight", () => {
  it("puts the sidecar's own refusal on the Home screen before any run is started", async () => {
    mocked.verifySettings.mockResolvedValue({
      ok: false,
      reason: "No API key for anthropic is configured.",
    });

    render(<App />);

    expect((await screen.findByTestId("preflight")).textContent).toContain("No API key for anthropic");
  });

  it("refuses to start a run once the month's cap is reached", async () => {
    mocked.getBudget.mockResolvedValue({
      period: "2026-09",
      spent_micros: 20_000_000,
      cap_micros: 20_000_000,
      percent_used: 100,
      spent_display: "$20.0000",
      cap_display: "$20.0000",
    });

    render(<App />);

    expect((await screen.findByTestId("preflight")).textContent).toContain("cap");
    expect(screen.getByRole("button", { name: "Start run" })).toHaveProperty("disabled", true);
  });
});

describe("losing the sidecar after startup", () => {
  it("says so, and goes back to reconnecting until it answers again", async () => {
    /* `/health` was checked once at launch. A sidecar that died afterwards left
       the header frozen and every panel failing on its own with "Failed to
       fetch", and nothing ever tried again. */
    let notify: (() => void) | null = null;
    vi.mocked(api.onTransportFailure).mockImplementation((listener) => {
      notify = listener;
      return () => undefined;
    });
    render(<App />);
    await screen.findByTestId("run-list");
    expect(vi.mocked(sidecar.connectWithRetry)).toHaveBeenCalledTimes(1);

    // The next attempt hangs so the banner can be seen.
    vi.mocked(sidecar.connectWithRetry).mockImplementation((onStatus) => {
      onStatus({ kind: "connecting", attempt: 3 });
      return new Promise(() => undefined);
    });
    await act(async () => {
      notify?.();
      await Promise.resolve();
    });

    expect(screen.getByTestId("sidecar-lost").textContent).toContain("attempt 3");
    expect(vi.mocked(sidecar.connectWithRetry)).toHaveBeenCalledTimes(2);
    // The rest of the window is still there underneath.
    expect(screen.getByTestId("run-list")).toBeDefined();
  });
});

describe("an approval waiting elsewhere", () => {
  it("is announced in the header, and clicking it opens that run", async () => {
    /* An approval pending on any run other than the selected one was
       invisible; the run sat on it until the deadline. */
    const user = userEvent.setup();
    mocked.listApprovals.mockResolvedValue([
      {
        id: "ap-1",
        run_id: "run-1",
        tool: "write_file",
        args: {},
        risk: "medium",
        status: "pending",
        created_at: "2026-09-10T12:00:00Z",
      },
    ]);
    render(<App />);
    await user.click(await screen.findByRole("button", { name: "Agents" }));

    const badge = await screen.findByRole("button", { name: /1 approval waiting/ });
    await user.click(badge);

    await waitFor(() => {
      expect(screen.getByTestId("run-panel")).toBeDefined();
    });
    expect(screen.getByTestId("run-list").closest("[hidden]")).toBeNull();
  });
});

describe("switching sections", () => {
  it("opens on Home, and a card there opens its run in the Runs section", async () => {
    const user = userEvent.setup();
    render(<App />);

    const card = await screen.findByTestId("run-card-run-1");
    expect(card.closest("[hidden]")).toBeNull();
    expect(screen.getByTestId("run-list").closest("[hidden]")).not.toBeNull();

    await user.click(card);

    await waitFor(() => {
      expect(screen.getByTestId("run-panel")).toBeDefined();
    });
    expect(screen.getByTestId("run-list").closest("[hidden]")).toBeNull();
    expect(screen.getByTestId("home").closest("[hidden]")).not.toBeNull();
  });

  it("keeps the selected run open, and its stream attached, across a visit to the agents section", async () => {
    /* The runs tab used to unmount, which closed the `EventSource`, forgot
       `runId`, and put the placeholder back. Coming back meant re-picking the
       run and downloading its whole log again — and an approval that arrived
       while the agents tab was showing was never seen. */
    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByTestId("run-card-run-1"));
    await waitFor(() => {
      expect(screen.getByTestId("run-panel")).toBeDefined();
    });
    const close = vi.mocked(events.streamRun).mock.results[0]?.value as { close: ReturnType<typeof vi.fn> };

    await user.click(screen.getByRole("button", { name: "Agents" }));
    expect(screen.getByTestId("agent-list").closest("[hidden]")).toBeNull();
    expect(close.close).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Runs" }));

    expect(screen.getByTestId("run-panel")).toBeDefined();
    expect(vi.mocked(events.streamRun)).toHaveBeenCalledTimes(1);
    expect(mocked.getRunHistory).toHaveBeenCalledTimes(1);
  });

  it("shows only the active section", async () => {
    const user = userEvent.setup();
    render(<App />);
    await screen.findByTestId("run-list");

    expect(screen.getByTestId("agent-list").closest("[hidden]")).not.toBeNull();

    await user.click(screen.getByRole("button", { name: "Agents" }));

    expect(screen.getByTestId("agent-list").closest("[hidden]")).toBeNull();
    expect(screen.getByTestId("run-list").closest("[hidden]")).not.toBeNull();
    expect(screen.getByTestId("home").closest("[hidden]")).not.toBeNull();
  });

  it("fetches the run list and the roster once, however many sections show them", async () => {
    /* Home and Runs both show the runs; Home and Agents both show the roster.
       Two copies of a list one of them edits disagree the moment it does, and
       two fetches of the same list on mount is the smell of two copies. */
    render(<App />);
    await screen.findByTestId("run-card-run-1");
    await screen.findByTestId("agent-list");

    expect(mocked.listRuns).toHaveBeenCalledTimes(1);
    expect(mocked.listAgents).toHaveBeenCalledTimes(1);
  });
});

describe("runs that happen elsewhere", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("re-reads the run list and the meter while any listed run is still going", async () => {
    /* A run started from Discord, or one left running in the background, never
       reached the list until the user started or finished a run of their own,
       and the meter did not move while it spent. */
    vi.useFakeTimers();
    mocked.listRuns.mockResolvedValue([row("running", "run-discord")]);
    render(<App />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(mocked.listRuns).toHaveBeenCalledTimes(1);
    const budgetReads = mocked.getBudget.mock.calls.length;

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_000);
    });

    expect(mocked.listRuns).toHaveBeenCalledTimes(2);
    expect(mocked.getBudget.mock.calls.length).toBe(budgetReads + 1);
  });

  it("stops polling once every listed run has ended", async () => {
    vi.useFakeTimers();
    mocked.listRuns.mockResolvedValue([row("completed"), row("failed", "run-2")]);
    render(<App />);
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
    mocked.listRuns.mockResolvedValue([row("completed")]);
    render(<App />);
    await screen.findByTestId("run-card-run-1");
    const budgetReads = mocked.getBudget.mock.calls.length;

    act(() => {
      document.dispatchEvent(new Event("visibilitychange"));
    });

    await waitFor(() => {
      expect(mocked.listRuns).toHaveBeenCalledTimes(2);
    });
    expect(mocked.getBudget.mock.calls.length).toBe(budgetReads + 1);
  });
});
