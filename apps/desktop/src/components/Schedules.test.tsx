import type { RiskLevel, ScheduleResponse, SettingsResponse, SpaceResponse } from "@agentbase/schemas";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../lib/api";

import { Schedules } from "./Schedules";

/**
 * A space's schedules: what the list says, what the editor sends, and the
 * one warning that matters for an unattended run (the approval policy).
 */

vi.mock("../lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof api>()),
  listSchedules: vi.fn(),
  createSchedule: vi.fn(),
  updateSchedule: vi.fn(),
  deleteSchedule: vi.fn(),
  runScheduleNow: vi.fn(),
  previewSchedule: vi.fn(),
}));

const mocked = vi.mocked(api);

const lab: SpaceResponse = {
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
  created_at: "2026-09-12T00:00:00Z",
  updated_at: "2026-09-12T00:00:00Z",
  folder: "/data/spaces/space-lab",
  is_default: false,
};

function settingsWith(autoApprove: RiskLevel[]): SettingsResponse {
  return {
    settings: {
      provider: "ollama",
      model: "qwen3:4b",
      auto_approve: autoApprove,
      max_steps_per_agent: 20,
      max_agents_per_run: 5,
      max_run_seconds: 600,
    },
    configured_secrets: [],
    known_secrets: [],
    supported_providers: ["ollama"],
    model_is_priced: true,
    version: "0.4.0",
    data_dir: "/data",
  };
}

const digest: ScheduleResponse = {
  id: "sched-1",
  space_id: "space-lab",
  name: "Morning digest",
  goal: "Summarise what changed since yesterday.",
  cadence: { kind: "weekly", at: "09:00", weekdays: [0, 1, 2, 3, 4] },
  missed: "run_on_launch",
  enabled: true,
  next_run_at: "2026-09-21T07:00:00+00:00",
  last_run_at: "2026-09-18T07:00:04+00:00",
  last_run_id: "run-9",
  last_outcome: "Started a run.",
  created_at: "2026-09-12T00:00:00Z",
  updated_at: "2026-09-18T07:00:04Z",
  summary: "Weekdays at 09:00",
};

beforeEach(() => {
  mocked.listSchedules.mockResolvedValue([digest]);
  mocked.previewSchedule.mockResolvedValue({
    summary: "Saturdays and Sundays at 07:30",
    next: ["2026-09-19T05:30:00+00:00", "2026-09-20T05:30:00+00:00", "2026-09-26T05:30:00+00:00"],
  });
  mocked.updateSchedule.mockImplementation((_id, patch) =>
    Promise.resolve({ ...digest, ...patch, summary: digest.summary } as ScheduleResponse),
  );
});

describe("Schedules", () => {
  it("lists a schedule with its cadence, next and last times, and opens the last run", async () => {
    const onOpenRun = vi.fn();
    render(<Schedules space={lab} settings={settingsWith(["low"])} onOpenRun={onOpenRun} />);

    const row = await screen.findByTestId("schedule-sched-1");
    expect(row.textContent).toContain("Morning digest");
    expect(row.textContent).toContain("Weekdays at 09:00");
    expect(row.textContent).toContain("Next:");
    expect(row.textContent).toContain("Last:");
    expect(row.textContent).toContain("Started a run.");

    await userEvent.click(within(row).getByRole("button", { name: "open the run" }));
    expect(onOpenRun).toHaveBeenCalledWith("run-9");
  });

  it("warns when the space would stop for every tool call, in the sidecar's own terms", async () => {
    render(<Schedules space={lab} settings={settingsWith([])} />);
    await screen.findByTestId("schedule-sched-1");

    const warning = screen.getByTestId("schedules-policy");
    expect(warning.textContent).toContain("asks before every tool call");
    expect(warning.textContent).toContain("up to 600 seconds");
  });

  it("says what an unattended run may call when the policy allows something", async () => {
    // The space narrows the app-wide policy: only what both allow counts.
    const narrowed: SpaceResponse = { ...lab, auto_approve: ["low", "medium"], max_run_seconds: 900 };
    render(<Schedules space={narrowed} settings={settingsWith(["low"])} />);
    await screen.findByTestId("schedule-sched-1");

    const note = screen.getByTestId("schedules-policy");
    expect(note.textContent).toContain("calls low-risk tools without asking");
    expect(note.textContent).toContain("up to 900 seconds");
    expect(note.textContent).toContain("stops at 20 steps per agent, 5 agents, 900 seconds");
  });

  it("reads the answers by tool into the unattended readout, the stricter one per tool", async () => {
    const own: SpaceResponse = { ...lab, tool_policies: { run_shell: "deny", http_get: "ask" } };
    const settings = settingsWith([]);
    settings.settings.tool_policies = { write_file: "allow", http_get: "allow" };
    render(<Schedules space={own} settings={settings} />);
    await screen.findByTestId("schedule-sched-1");

    const note = screen.getByTestId("schedules-policy").textContent;
    expect(note).toContain("runs write_file without asking whatever the level");
    expect(note).toContain("is refused run_shell");
    expect(note).not.toContain("http_get");
  });

  it("turns a schedule off and on, and runs it now", async () => {
    mocked.runScheduleNow.mockResolvedValue({
      id: "run-abcdef12-3456",
      space_id: "space-lab",
      goal: digest.goal,
      status: "pending",
      origin: "schedule",
      origin_ref: "sched-1",
      created_at: "2026-09-19T00:00:00Z",
    });
    render(<Schedules space={lab} settings={settingsWith(["low"])} />);
    const row = await screen.findByTestId("schedule-sched-1");

    await userEvent.click(within(row).getByRole("checkbox", { name: "Morning digest enabled" }));
    expect(mocked.updateSchedule).toHaveBeenCalledWith("sched-1", { enabled: false });

    await userEvent.click(within(row).getByRole("button", { name: "Run now" }));
    expect(mocked.runScheduleNow).toHaveBeenCalledWith("sched-1");
    expect((await screen.findByRole("status")).textContent).toContain("Started a run for Morning digest");
  });

  it("creates a weekly schedule from the picker, previewing it as it is built", async () => {
    mocked.createSchedule.mockResolvedValue({
      ...digest,
      id: "sched-2",
      name: "Weekend tidy",
      summary: "Saturdays and Sundays at 07:30",
    });
    render(<Schedules space={lab} settings={settingsWith(["low"])} />);
    await screen.findByTestId("schedule-sched-1");

    await userEvent.click(screen.getByRole("button", { name: "New schedule" }));
    const editor = screen.getByTestId("schedule-editor");
    await userEvent.type(within(editor).getByTestId("schedule-name"), "Weekend tidy");
    await userEvent.type(within(editor).getByTestId("schedule-goal"), "Tidy the notes.");
    await userEvent.click(within(editor).getByTestId("schedule-kind-weekly"));
    // Weekdays start ticked; untick them and tick the weekend.
    for (const day of [0, 1, 2, 3, 4]) {
      await userEvent.click(within(editor).getByTestId(`schedule-day-${String(day)}`));
    }
    await userEvent.click(within(editor).getByTestId("schedule-day-5"));
    await userEvent.click(within(editor).getByTestId("schedule-day-6"));
    const at = within(editor).getByTestId("schedule-at");
    await userEvent.clear(at);
    await userEvent.type(at, "07:30");
    await userEvent.click(within(editor).getByTestId("schedule-missed-skip"));

    await waitFor(() => {
      expect(mocked.previewSchedule).toHaveBeenLastCalledWith({ kind: "weekly", at: "07:30", weekdays: [5, 6] });
    });
    await waitFor(() => {
      expect(screen.getByTestId("schedule-preview").textContent).toContain("Saturdays and Sundays at 07:30");
    });

    await userEvent.click(screen.getByRole("button", { name: "Create schedule" }));
    expect(mocked.createSchedule).toHaveBeenCalledWith({
      space_id: "space-lab",
      name: "Weekend tidy",
      goal: "Tidy the notes.",
      cadence: { kind: "weekly", at: "07:30", weekdays: [5, 6] },
      missed: "skip",
      enabled: true,
      max_run_seconds: null,
    });
    await waitFor(() => {
      expect(screen.queryByTestId("schedule-editor")).toBeNull();
    });
  });

  it("edits an existing schedule as an interval and refuses a bad number of hours", async () => {
    render(<Schedules space={lab} settings={settingsWith(["low"])} />);
    const row = await screen.findByTestId("schedule-sched-1");

    await userEvent.click(within(row).getByRole("button", { name: "Edit" }));
    const editor = screen.getByTestId("schedule-editor");
    expect(within(editor).getByTestId<HTMLInputElement>("schedule-name").value).toBe("Morning digest");
    await userEvent.click(within(editor).getByTestId("schedule-kind-interval"));
    const hours = within(editor).getByTestId("schedule-hours");
    await userEvent.clear(hours);
    await userEvent.type(hours, "0");
    await userEvent.click(screen.getByRole("button", { name: "Save schedule" }));
    expect(screen.getByRole("alert").textContent).toContain("1 to 168");
    expect(mocked.updateSchedule).not.toHaveBeenCalled();

    await userEvent.clear(hours);
    await userEvent.type(hours, "12");
    // A time limit of its own for the overnight run; a bad one is refused first.
    const seconds = within(editor).getByTestId("schedule-seconds");
    await userEvent.type(seconds, "0");
    await userEvent.click(screen.getByRole("button", { name: "Save schedule" }));
    expect(screen.getByRole("alert").textContent).toContain("whole number of seconds");
    expect(mocked.updateSchedule).not.toHaveBeenCalled();
    await userEvent.clear(seconds);
    await userEvent.type(seconds, "7200");
    await userEvent.click(screen.getByRole("button", { name: "Save schedule" }));
    expect(mocked.updateSchedule).toHaveBeenCalledWith("sched-1", {
      name: "Morning digest",
      goal: "Summarise what changed since yesterday.",
      cadence: { kind: "interval", every_hours: 12 },
      missed: "run_on_launch",
      enabled: true,
      max_run_seconds: 7200,
    });
  });

  it("deletes only after a second click", async () => {
    mocked.deleteSchedule.mockResolvedValue(undefined);
    render(<Schedules space={lab} settings={settingsWith(["low"])} />);
    const row = await screen.findByTestId("schedule-sched-1");

    await userEvent.click(within(row).getByRole("button", { name: "Delete…" }));
    expect(mocked.deleteSchedule).not.toHaveBeenCalled();
    await userEvent.click(within(row).getByRole("button", { name: "Delete" }));
    expect(mocked.deleteSchedule).toHaveBeenCalledWith("sched-1");
  });
});
