import type { AgentDef, Run, ScheduleResponse } from "@agentbase/schemas";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../lib/api";
import { PIPELINE_SCHEDULE_IDS, STARTERS } from "../lib/pipeline";
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
  searchKnowledge: vi.fn(),
  startDebugRun: vi.fn(),
  updateAgent: vi.fn(),
  listSchedules: vi.fn(),
  updateSchedule: vi.fn(),
  listFiles: vi.fn(),
  writeFile: vi.fn(),
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
      modelLabel="anthropic · claude-sonnet-5"
      {...handlers}
      {...props}
    />,
  );
  return handlers;
}

beforeEach(() => {
  vi.clearAllMocks();
  useRunList.getState().reset();
  useRoster.getState().reset();
  useRunList.setState({ spaceId: "space-main" });
  useRoster.setState({ spaceId: "space-main" });
  mocked.listRuns.mockResolvedValue([row("completed")]);
  mocked.listAgents.mockResolvedValue([writer]);
  mocked.listSchedules.mockResolvedValue([]);
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

  it("sends a model the account cannot use to Space settings, where it is chosen", async () => {
    const user = userEvent.setup();
    const onOpenSpaceSettings = vi.fn();
    const { onOpenSettings } = home({
      blocker: "Your ChatGPT subscription does not include gpt-6-sol.",
      blockerKind: "space",
      onOpenSpaceSettings,
    });

    const card = screen.getByTestId("preflight");
    expect(card.textContent).toContain("This space needs a different model");
    expect(card.textContent).not.toContain("first run");
    await user.click(screen.getByRole("button", { name: "Open Space settings" }));
    expect(onOpenSpaceSettings).toHaveBeenCalled();
    expect(onOpenSettings).not.toHaveBeenCalled();
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

describe("the retrieval preview", () => {
  const lab = {
    id: "space-lab",
    name: "Lab",
    description: "",
    provider: null,
    model: null,
    auto_approve: null,
    max_steps_per_agent: null,
    max_agents_per_run: null,
    max_run_seconds: null,
    archived: false,
    created_at: "2026-09-15T00:00:00Z",
    updated_at: "2026-09-15T00:00:00Z",
    folder: "/data/spaces/space-lab",
    is_default: false,
  };

  it("shows each excerpt's terms and token cost, names the model, and excludes an unticked one", async () => {
    const user = userEvent.setup();
    mocked.searchKnowledge.mockResolvedValue({
      query: "storage",
      hits: [
        {
          path: "decisions/storage.md",
          title: "Storage",
          heading: "WAL",
          excerpt: "Use SQLite WAL.",
          citation: "[[decisions/storage#WAL]]",
          score: 0.8,
          matched_terms: ["storag", "wal"],
          reasons: ["body: storag, wal"],
          estimated_tokens: 12,
        },
        {
          path: "recipes/soup.md",
          title: "Soup",
          heading: null,
          excerpt: "Carrots.",
          citation: "[[recipes/soup]]",
          score: 0.2,
          matched_terms: ["storag"],
          reasons: ["title: storag"],
          estimated_tokens: 4,
        },
      ],
    });
    mocked.createRun.mockResolvedValue(row("pending", "run-new", "pick storage"));
    home({ space: lab });
    await screen.findByTestId("run-card-run-1");

    await user.type(screen.getByTestId("goal-input"), "pick storage");
    await user.click(screen.getByRole("button", { name: "Preview notes" }));

    const preview = await screen.findByTestId("retrieval-preview");
    expect(preview.textContent).toContain("These 2 passages from this space's notes");
    expect(preview.textContent).toContain("(about 16 tokens)");
    expect(preview.textContent).toContain("anthropic · claude-sonnet-5");
    expect(preview.textContent).toContain("matched storag, wal");
    await user.click(screen.getByRole("checkbox", { name: /recipes\/soup/ }));
    expect(preview.textContent).toContain("This passage from this space's notes");
    expect(preview.textContent).toContain("(about 12 tokens)");
    await user.click(screen.getByRole("button", { name: "Start run" }));

    expect(mocked.createRun).toHaveBeenCalledWith("pick storage", "space-lab", ["[[recipes/soup]]"]);
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


describe("working on its own", () => {
  const main = {
    id: "space-main",
    name: "Main",
    description: "",
    provider: null,
    model: null,
    auto_approve: null,
    max_steps_per_agent: null,
    max_agents_per_run: null,
    max_run_seconds: null,
    archived: false,
    created_at: "2026-09-15T00:00:00Z",
    updated_at: "2026-09-15T00:00:00Z",
    folder: "/data/spaces/space-main",
    is_default: true,
  };

  const stage = (id: string, name: string, enabled = false): ScheduleResponse => ({
    id,
    space_id: "space-main",
    name,
    goal: `Run ${name}.`,
    cadence: { kind: "weekly", at: "07:00", weekdays: [0, 1, 2, 3, 4] },
    missed: "run_on_launch",
    enabled,
    next_run_at: enabled ? "2026-09-30T05:00:00+00:00" : null,
    last_run_at: null,
    last_run_id: null,
    last_outcome: null,
    created_at: "2026-09-29T00:00:00Z",
    updated_at: "2026-09-29T00:00:00Z",
    summary: "Weekdays at 07:00",
  });

  it("steps through a run when asked, as the manual fallback", async () => {
    const user = userEvent.setup();
    mocked.createRun.mockResolvedValue(row("pending", "run-new", "look around"));
    home();

    await user.type(screen.getByTestId("goal-input"), "look around");
    await user.click(screen.getByTestId("step-through"));
    await user.click(screen.getByRole("button", { name: "Start run" }));

    expect(mocked.createRun).toHaveBeenCalledWith("look around", undefined, [], true);
  });

  it("hands a goal to Automations to make it recurring", async () => {
    const user = userEvent.setup();
    const onAutomate = vi.fn();
    home({ onAutomate });

    expect(screen.getByTestId<HTMLButtonElement>("make-recurring").disabled).toBe(true);
    await user.type(screen.getByTestId("goal-input"), "Summarise the inbox");
    await user.click(screen.getByTestId("make-recurring"));

    expect(onAutomate).toHaveBeenCalledWith("Summarise the inbox");
  });

  it("offers to automate a task when nothing runs on its own", async () => {
    const user = userEvent.setup();
    const onAutomate = vi.fn();
    home({ space: main, onAutomate });

    const line = await screen.findByTestId("home-automations-line");
    expect(line.textContent).toContain("Nothing in Main runs on its own yet.");
    await user.click(screen.getByRole("button", { name: "Automate a task" }));
    expect(onAutomate).toHaveBeenCalledWith("");
  });

  it("says how many automations are on and which is next", async () => {
    mocked.listSchedules.mockResolvedValue([stage("s-1", "Digest", true), stage("s-2", "Off")]);
    home({ space: main });

    const line = await screen.findByTestId("home-automations-line");
    await waitFor(() => {
      expect(line.textContent).toContain("1 automation on. Next: Digest");
    });
  });

  it("rereads the strip when schedules change in Automations, and says when it changed them", async () => {
    /* Every section stays mounted, so a list read once goes stale: turning the
       pipeline on from Home once left Automations showing every stage off. */
    const onSchedulesChanged = vi.fn();
    const { rerender } = render(
      <HomeView
        space={main}
        blocker={null}
        pendingApprovals={[]}
        liveStatus={null}
        modelLabel={null}
        onOpenRun={vi.fn()}
        onOpenRuns={vi.fn()}
        onOpenAgents={vi.fn()}
        onOpenSettings={vi.fn()}
        onWorkspaceChanged={vi.fn()}
        schedulesNonce={0}
        onSchedulesChanged={onSchedulesChanged}
      />,
    );
    await screen.findByTestId("home-automations-line");
    const reads = mocked.listSchedules.mock.calls.length;

    rerender(
      <HomeView
        space={main}
        blocker={null}
        pendingApprovals={[]}
        liveStatus={null}
        modelLabel={null}
        onOpenRun={vi.fn()}
        onOpenRuns={vi.fn()}
        onOpenAgents={vi.fn()}
        onOpenSettings={vi.fn()}
        onWorkspaceChanged={vi.fn()}
        schedulesNonce={1}
        onSchedulesChanged={onSchedulesChanged}
      />,
    );
    await waitFor(() => {
      expect(mocked.listSchedules.mock.calls.length).toBe(reads + 1);
    });
  });

  it("turns the shipped pipeline on in one click, writing only the files that are missing", async () => {
    const user = userEvent.setup();
    const pipeline = PIPELINE_SCHEDULE_IDS.map((id, index) => stage(id, `Stage ${String(index)}`));
    mocked.listSchedules.mockResolvedValue(pipeline);
    mocked.listFiles.mockResolvedValue({
      files: [{ path: "config/watchlist.json", size: 10, updated_at: "2026-09-29T00:00:00Z" }],
    });
    mocked.writeFile.mockResolvedValue({ path: "x", size: 1, updated_at: "", content: "" });
    mocked.updateSchedule.mockImplementation((id) =>
      Promise.resolve({ ...stage(id, "x", true) }),
    );
    home({ space: main, runCapMicros: 2_000_000 });

    const offer = await screen.findByTestId("pipeline-offer");
    expect(offer.textContent).toContain("before spending $2.00");
    expect(offer.textContent).toContain("watchlist and positions");
    expect(offer.textContent).toContain("Reddit");
    expect(offer.textContent).toContain("SEC filings");
    await user.click(screen.getByTestId("pipeline-turn-on"));

    await waitFor(() => {
      expect(mocked.updateSchedule).toHaveBeenCalledTimes(5);
    });
    expect(mocked.writeFile.mock.calls.map((call) => call[1])).toEqual(
      STARTERS.map((entry) => entry.path).filter((path) => path !== "config/watchlist.json"),
    );
    expect((await screen.findByRole("status")).textContent).toContain("The pipeline is on");
  });

  it("turns on what it can when one stage refuses, and names that stage", async () => {
    const user = userEvent.setup();
    const pipeline = PIPELINE_SCHEDULE_IDS.map((id, index) => stage(id, `Stage ${String(index)}`));
    mocked.listSchedules.mockResolvedValue(pipeline);
    // A case-variant of a template's file is the same file on Windows and macOS.
    mocked.listFiles.mockResolvedValue({
      files: STARTERS.map((entry, index) => ({
        path: index === 0 ? "Config/Watchlist.json" : entry.path,
        size: 10,
        updated_at: "",
      })),
    });
    mocked.updateSchedule.mockImplementation((id) =>
      id === PIPELINE_SCHEDULE_IDS[1]
        ? Promise.reject(new Error("there is no schedule with that id to follow"))
        : Promise.resolve({ ...stage(id, "x", true) }),
    );
    home({ space: main });

    await user.click(await screen.findByTestId("pipeline-turn-on"));

    await waitFor(() => {
      expect(mocked.updateSchedule).toHaveBeenCalledTimes(5);
    });
    expect(mocked.writeFile).not.toHaveBeenCalled();
    const notice = (await screen.findByRole("status")).textContent;
    expect(notice).toContain("Part of the pipeline is on");
    expect(notice).toContain("Stage 1 (there is no schedule with that id to follow)");
  });

  it("tells the shell it changed the schedules, so Automations rereads them", async () => {
    const user = userEvent.setup();
    const pipeline = PIPELINE_SCHEDULE_IDS.map((id, index) => stage(id, `Stage ${String(index)}`));
    mocked.listSchedules.mockResolvedValue(pipeline);
    mocked.listFiles.mockResolvedValue({ files: [] });
    mocked.writeFile.mockResolvedValue({ path: "x", size: 1, updated_at: "", content: "" });
    mocked.updateSchedule.mockImplementation((id) => Promise.resolve({ ...stage(id, "x", true) }));
    const onSchedulesChanged = vi.fn();
    home({ space: main, onSchedulesChanged });

    await user.click(await screen.findByTestId("pipeline-turn-on"));
    await waitFor(() => {
      expect(onSchedulesChanged).toHaveBeenCalled();
    });
  });
});
