import type { AgentDef, Run } from "@agentspace/schemas";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../lib/api";
import { useRoster } from "../state/roster";
import { useRunList } from "../state/runList";

import { HomeView, type HomeViewProps } from "./HomeView";

/**
 * The Home screen: the goal box, what stands in its way, what is happening
 * now, what happened recently, and who is available to work.
 */

vi.mock("../lib/api", () => ({
  listRuns: vi.fn(),
  listAgents: vi.fn(),
  createRun: vi.fn(),
  startDebugRun: vi.fn(),
  updateAgent: vi.fn(),
}));

const mocked = vi.mocked(api);

const row = (status: Run["status"], id = "run-1", goal = "Summarise the quarterly report"): Run => ({
  id,
  space_id: "space-main",
  goal,
  status,
  origin: "ui",
  origin_ref: null,
  created_at: "2026-09-10T12:00:00Z",
  finished_at: status === "completed" || status === "failed" ? "2026-09-10T12:01:32Z" : null,
});

const writer: AgentDef = {
  id: "def-1",
  space_id: "space-main",
  name: "writer",
  role: "Writes things",
  system_prompt: "You write.",
  provider: null,
  model: null,
  allowed_tools: ["write_file"],
  max_steps: 10,
  auto_approve: [],
  is_builtin: false,
  enabled: true,
  created_at: "2026-09-10T12:00:00Z",
  updated_at: "2026-09-10T12:00:00Z",
};

const APPROVAL = {
  id: "ap-9",
  run_id: "run-discord",
  tool: "write_file",
  args: {},
  risk: "medium",
  status: "pending",
  created_at: "2026-09-10T12:00:00Z",
};

function home(props: Partial<HomeViewProps> = {}) {
  const handlers = {
    onOpenRun: vi.fn(),
    onOpenRuns: vi.fn(),
    onOpenAgents: vi.fn(),
    onOpenSettings: vi.fn(),
    onWorkspaceChanged: vi.fn(),
  };
  render(
    <HomeView
      space={null}
      blocker={null}
      pendingApprovals={[]}
      liveStatus={null}
      {...handlers}
      {...props}
    />,
  );
  return handlers;
}

beforeEach(() => {
  useRunList.getState().reset();
  useRoster.getState().reset();
  useRunList.setState({ spaceId: "space-main" });
  useRoster.setState({ spaceId: "space-main" });
  mocked.listRuns.mockResolvedValue([row("completed")]);
  mocked.listAgents.mockResolvedValue([writer]);
});

describe("starting a run", () => {
  it("starts the run, opens it, and re-reads the list", async () => {
    const user = userEvent.setup();
    mocked.createRun.mockResolvedValue(row("pending", "run-new", "do a thing"));
    const { onOpenRun } = home();
    await screen.findByTestId("run-card-run-1");

    await user.type(screen.getByTestId("goal-input"), "do a thing");
    await user.click(screen.getByRole("button", { name: "Start run" }));

    expect(mocked.createRun).toHaveBeenCalledWith("do a thing", undefined);
    expect(onOpenRun).toHaveBeenCalledWith("run-new");
    await waitFor(() => {
      expect(mocked.listRuns).toHaveBeenCalledTimes(2);
    });
    expect(screen.getByTestId<HTMLTextAreaElement>("goal-input").value).toBe("");
  });

  it("sends on Enter and keeps Shift+Enter for a new line", async () => {
    const user = userEvent.setup();
    mocked.createRun.mockResolvedValue(row("pending", "run-new"));
    home();

    await user.type(screen.getByTestId("goal-input"), "first line{Shift>}{Enter}{/Shift}second");
    expect(mocked.createRun).not.toHaveBeenCalled();
    await user.keyboard("{Enter}");

    expect(mocked.createRun).toHaveBeenCalledWith("first line\nsecond", undefined);
  });

  it("says why a run would be refused and does not offer to start one", async () => {
    /* The header said "unpriced: runs will be refused" and the meter said
       "further runs are refused" while the Start button stayed live. Every
       click added a dead `failed` row, with the reason only in its log. */
    const user = userEvent.setup();
    const { onOpenSettings } = home({
      blocker: "No API key for anthropic. Add one in the settings and restart.",
    });

    await user.type(screen.getByTestId("goal-input"), "do a thing");

    expect(screen.getByTestId("preflight").textContent).toContain("No API key for anthropic");
    expect(screen.getByRole("button", { name: "Start run" })).toHaveProperty("disabled", true);
    expect(mocked.createRun).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Open settings" }));
    expect(onOpenSettings).toHaveBeenCalled();
  });

  it("offers the scripted demo run when a real one cannot start", async () => {
    const user = userEvent.setup();
    mocked.startDebugRun.mockResolvedValue(row("running", "run-demo", "demo"));
    const { onOpenRun } = home({ blocker: "No API key." });

    await user.click(screen.getByRole("button", { name: "Try a demo run" }));

    expect(mocked.startDebugRun).toHaveBeenCalled();
    expect(onOpenRun).toHaveBeenCalledWith("run-demo");
  });

  it("shows a failed start beside the box", async () => {
    const user = userEvent.setup();
    mocked.createRun.mockRejectedValue(new Error("the sidecar refused"));
    home();

    await user.type(screen.getByTestId("goal-input"), "do a thing");
    await user.click(screen.getByRole("button", { name: "Start run" }));

    expect((await screen.findByRole("alert")).textContent).toContain("refused");
  });
});

describe("what is on the screen", () => {
  it("puts running runs and runs waiting on an approval under Now, and finished ones under Recent", async () => {
    mocked.listRuns.mockResolvedValue([
      row("running", "run-live", "Draft the release notes"),
      row("completed", "run-discord", "From a chat"),
      row("completed"),
    ]);
    home({ pendingApprovals: [APPROVAL] });

    const now = await screen.findByTestId("home-now");
    expect(now.textContent).toContain("Draft the release notes");
    // Finished by the table, but a person is being asked about it: listed.
    expect(now.textContent).toContain("From a chat");
    expect(screen.getByTestId("run-card-needs-approval-run-discord")).toBeDefined();

    const recent = screen.getByTestId("home-recent");
    expect(recent.textContent).toContain("quarterly");
    expect(recent.textContent).not.toContain("release notes");
  });

  it("tells the open run's card what its log says, not what the table says", async () => {
    /* `POST /runs` returns `pending` and the table is not re-read until the
       run ends, so a live run's card read "not started" for its duration. */
    mocked.listRuns.mockResolvedValue([row("pending", "run-live")]);
    home({ liveStatus: { runId: "run-live", status: "running" } });

    const card = await screen.findByTestId("run-card-run-live");
    expect(card.textContent).toContain("running");
    expect(card.textContent).not.toContain("not started");
  });

  it("shows a finished run's duration from its own two timestamps", async () => {
    home();
    const card = await screen.findByTestId("run-card-run-1");
    expect(card.textContent).toContain("1m 32s");
  });

  it("opens a run from its card and the whole list from the section", async () => {
    const user = userEvent.setup();
    const { onOpenRun, onOpenRuns } = home();

    await user.click(await screen.findByTestId("run-card-run-1"));
    expect(onOpenRun).toHaveBeenCalledWith("run-1");

    await user.click(screen.getByRole("button", { name: "All runs" }));
    expect(onOpenRuns).toHaveBeenCalled();
  });

  it("makes the goal box the whole screen on a fresh install", async () => {
    /* No runs yet: nothing to list, so nothing is listed. The agents that
       are ready get one sentence, not a section. */
    mocked.listRuns.mockResolvedValue([]);
    home();

    await waitFor(() => {
      expect(screen.getByTestId("home").className).toContain("home--first");
    });
    expect(screen.queryByTestId("home-now")).toBeNull();
    expect(screen.queryByTestId("home-recent")).toBeNull();
    expect(screen.queryByTestId("home-roster")).toBeNull();
    expect(await screen.findByText(/1 agent ready: writer/)).toBeDefined();
  });
});

describe("the roster", () => {
  it("lists every agent with a toggle, and re-reads the roster after one is flipped", async () => {
    const user = userEvent.setup();
    mocked.updateAgent.mockResolvedValue({ ...writer, enabled: false });
    const { onWorkspaceChanged } = home();

    const toggle = await screen.findByLabelText<HTMLInputElement>("Available to the supervisor: writer");
    expect(toggle.checked).toBe(true);

    mocked.listAgents.mockResolvedValue([{ ...writer, enabled: false }]);
    await user.click(toggle);

    expect(mocked.updateAgent).toHaveBeenCalledWith("def-1", { enabled: false });
    await waitFor(() => {
      expect(screen.getByLabelText<HTMLInputElement>("Available to the supervisor: writer").checked).toBe(false);
    });
    expect(onWorkspaceChanged).toHaveBeenCalled();
  });

  it("points at the agents section to add one", async () => {
    const user = userEvent.setup();
    const { onOpenAgents } = home();

    await user.click(await screen.findByRole("button", { name: "Add an agent" }));

    expect(onOpenAgents).toHaveBeenCalled();
  });
});
