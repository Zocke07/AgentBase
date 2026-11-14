import type { SpaceResponse } from "@agentbase/schemas";
import { describe, expect, it, vi } from "vitest";

import { GROUP_LIMIT, paletteCommands, rankCommands, type PaletteActions, type PaletteInput } from "./palette";

const space = (id: string, name: string, is_default = false): SpaceResponse => ({
  id,
  name,
  created_at: "2026-09-12T00:00:00Z",
  updated_at: "2026-09-12T00:00:00Z",
  folder: `spaces/${id}`,
  is_default,
});

const actions = (): PaletteActions => ({
  section: vi.fn(),
  startRun: vi.fn(),
  schedule: vi.fn(),
  newSpace: vi.fn(),
  toggleRail: vi.fn(),
  theme: vi.fn(),
  tour: vi.fn(),
  portfolio: vi.fn(),
  marketWatch: vi.fn(),
  space: vi.fn(),
  run: vi.fn(),
  agent: vi.fn(),
  note: vi.fn(),
});

const input = (extra: Partial<PaletteInput> = {}): PaletteInput => ({
  spaces: [space("main", "Main", true), space("lab", "Lab"), { ...space("old", "Old"), archived: true }],
  currentSpaceId: "main",
  runs: Array.from({ length: 8 }, (_, index) => ({
    id: `run-${String(index)}`,
    space_id: "main",
    goal: `Goal number ${String(index)}`,
    status: "completed" as const,
    origin: "ui" as const,
    origin_ref: null,
    created_at: "2026-09-10T12:00:00Z",
    finished_at: null,
    title: index === 0 ? "Morning research" : null,
  })),
  agents: [],
  notes: [{ path: "reviews/chapter-two.md", title: "Chapter two review" } as PaletteInput["notes"][number]],
  railOpen: true,
  theme: "system",
  actions: actions(),
  ...extra,
});

describe("the palette's rows", () => {
  it("offers the default space's own tools only there", () => {
    const ids = (from: PaletteInput) => paletteCommands(from).map((command) => command.id);
    expect(ids(input())).toEqual(expect.arrayContaining(["portfolio", "market-watch"]));
    const elsewhere = ids(input({ currentSpaceId: "lab" }));
    expect(elsewhere).not.toContain("portfolio");
    expect(elsewhere).not.toContain("market-watch");
  });

  it("offers the other live spaces, never the current or an archived one", () => {
    const spaces = paletteCommands(input()).filter((command) => command.group === "Spaces");
    expect(spaces.map((command) => command.label)).toEqual(["Switch to Lab"]);
  });

  it("names a run by its title, with the goal under it, or by its goal", () => {
    const runs = paletteCommands(input()).filter((command) => command.group === "Runs");
    expect(runs[0]).toMatchObject({ label: "Morning research", detail: "Goal number 0" });
    expect(runs[1]).toMatchObject({ label: "Goal number 1", detail: undefined });
  });

  it("offers the appearances not in use, and says which way the sidebar goes", () => {
    const labels = paletteCommands(input({ theme: "dark", railOpen: false })).map((command) => command.label);
    expect(labels).toContain("Use the light appearance");
    expect(labels).not.toContain("Use the dark appearance");
    expect(labels).toContain("Show the sidebar");
  });

  it("does what the row says", () => {
    const given = input();
    const lab = paletteCommands(given).find((command) => command.id === "space-lab");
    lab?.run();
    expect(given.actions.space).toHaveBeenCalledWith("lab");
  });
});

describe("ranking", () => {
  it("shows sections, actions, spaces and the newest few runs before anything is typed", () => {
    const sections = rankCommands("", paletteCommands(input()));
    expect(sections.map((section) => section.group)).toEqual(["Sections", "Actions", "Spaces", "Runs"]);
    expect(sections.find((section) => section.group === "Runs")?.commands).toHaveLength(5);
  });

  it("puts the group with the best match first", () => {
    const sections = rankCommands("chapter two", paletteCommands(input()));
    expect(sections[0]?.group).toBe("Notes");
    expect(sections[0]?.commands[0]?.label).toBe("Chapter two review");
  });

  it("shows a few rows of each group for a query", () => {
    const sections = rankCommands("goal", paletteCommands(input()));
    const runs = sections.find((section) => section.group === "Runs");
    expect(runs?.commands).toHaveLength(GROUP_LIMIT);
  });
});
