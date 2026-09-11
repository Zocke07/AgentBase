import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";
import * as api from "./lib/api";
import * as events from "./lib/events";
import * as sidecar from "./lib/sidecar";
import { useRunStore } from "./state/runStore";

/**
 * The shell: which tab is showing, and what survives switching.
 */

vi.mock("./lib/sidecar", () => ({
  connectWithRetry: vi.fn(),
}));

vi.mock("./lib/api", () => ({
  listRuns: vi.fn(),
  getRunHistory: vi.fn(),
  getBudget: vi.fn(),
  getSettings: vi.fn(),
  verifySettings: vi.fn(),
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

beforeEach(() => {
  useRunStore.getState().reset();
  vi.mocked(sidecar.connectWithRetry).mockImplementation((onStatus) => {
    onStatus({ kind: "ready", health: { ok: true }, baseUrl: "http://x" });
    return Promise.resolve();
  });
  vi.mocked(events.streamRun).mockReturnValue({ close: vi.fn() });
  mocked.getBudget.mockRejectedValue(new Error("not in this test"));
  mocked.getSettings.mockRejectedValue(new Error("not in this test"));
  mocked.verifySettings.mockResolvedValue({ ok: true, provider: "ollama", model: "qwen3:4b" });
  mocked.listAgents.mockResolvedValue([]);
  mocked.listTools.mockResolvedValue([]);
  mocked.listProviders.mockResolvedValue({ providers: [], models: {} });
  mocked.getRunHistory.mockResolvedValue([]);
  mocked.listRuns.mockResolvedValue([
    {
      id: "run-1",
      goal: "Summarise the quarterly report",
      status: "running",
      origin: "ui",
      origin_ref: null,
      created_at: "2026-09-10T12:00:00Z",
      finished_at: null,
    },
  ]);
});

describe("pre-flight", () => {
  it("puts the sidecar's own refusal beside the goal box before any run is started", async () => {
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

describe("switching tabs", () => {
  it("keeps the selected run open, and its stream attached, across a visit to the agents tab", async () => {
    /* The runs tab used to unmount, which closed the `EventSource`, forgot
       `runId`, and put the placeholder back. Coming back meant re-picking the
       run and downloading its whole log again — and an approval that arrived
       while the agents tab was showing was never seen. */
    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByRole("button", { name: /quarterly/ }));
    await waitFor(() => {
      expect(screen.getByTestId("run-panel")).toBeDefined();
    });
    const close = vi.mocked(events.streamRun).mock.results[0]?.value as { close: ReturnType<typeof vi.fn> };

    await user.click(screen.getByRole("button", { name: "Agents" }));
    expect(screen.getByTestId("agent-list")).toBeDefined();
    expect(close.close).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Runs" }));

    expect(screen.getByTestId("run-panel")).toBeDefined();
    expect(vi.mocked(events.streamRun)).toHaveBeenCalledTimes(1);
    expect(mocked.getRunHistory).toHaveBeenCalledTimes(1);
  });

  it("shows only the active tab", async () => {
    const user = userEvent.setup();
    render(<App />);
    await screen.findByTestId("run-list");

    expect(screen.getByTestId("agent-list").closest("[hidden]")).not.toBeNull();

    await user.click(screen.getByRole("button", { name: "Agents" }));

    expect(screen.getByTestId("agent-list").closest("[hidden]")).toBeNull();
    expect(screen.getByTestId("run-list").closest("[hidden]")).not.toBeNull();
  });
});
