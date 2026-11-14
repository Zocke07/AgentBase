import type { AgentDef, NoteSummary, Run, SpaceResponse } from "@agentbase/schemas";

import { fuzzyFilter } from "./fuzzy";
import { SECTION_LABEL, SECTION_ORDER, type Section } from "./sections";
import type { Theme } from "./theme";

/**
 * The command palette's list (Phase 20, brief 6.4): what it can find, and
 * how a query ranks it. The ranking is the note switcher's, `lib/fuzzy.ts`
 * over the words a row shows, so the two palettes agree on what a good
 * match is.
 */

export type PaletteGroup = "Sections" | "Actions" | "Spaces" | "Runs" | "Agents" | "Notes";

/** The order groups take while nothing is typed. */
export const PALETTE_GROUPS: readonly PaletteGroup[] = ["Sections", "Actions", "Spaces", "Runs", "Agents", "Notes"];

export interface PaletteCommand {
  /** Unique across the whole list. */
  readonly id: string;
  readonly group: PaletteGroup;
  readonly label: string;
  /** A second, quieter line: a run's goal, a note's path. */
  readonly detail?: string | undefined;
  /** Words it is also found by, never shown. */
  readonly keywords?: string | undefined;
  /** An id in `lib/shortcuts.ts`, shown at the row's end. */
  readonly shortcut?: string | undefined;
  readonly run: () => void;
}

export interface PaletteSection {
  readonly group: PaletteGroup;
  readonly commands: readonly PaletteCommand[];
}

/** How many rows a group shows for a query. */
export const GROUP_LIMIT = 6;

/** With nothing typed: these groups only, and the newest few runs. */
const RESTING: ReadonlySet<PaletteGroup> = new Set(["Sections", "Actions", "Spaces", "Runs"]);
const RESTING_RUNS = 5;

/**
 * The rows for a query, grouped. With nothing typed, groups keep their own
 * order and rows the order given (runs newest first). With a query, each
 * group's rows are best first and the groups follow their best row, so an
 * exact note title outranks a section that only half matches.
 */
export function rankCommands(query: string, commands: readonly PaletteCommand[]): PaletteSection[] {
  const trimmed = query.trim();
  if (trimmed === "") {
    return PALETTE_GROUPS.filter((group) => RESTING.has(group))
      .map((group) => {
        const rows = commands.filter((command) => command.group === group);
        return { group, commands: group === "Runs" ? rows.slice(0, RESTING_RUNS) : rows };
      })
      .filter((section) => section.commands.length > 0);
  }
  const matches = fuzzyFilter(trimmed, commands, (command) =>
    [command.label, command.detail, command.keywords].filter((part) => part !== undefined).join(" "),
  );
  const best = new Map<PaletteGroup, number>();
  const grouped = new Map<PaletteGroup, PaletteCommand[]>();
  for (const match of matches) {
    const { group } = match.item;
    if (!best.has(group)) best.set(group, match.score);
    const rows = grouped.get(group) ?? [];
    if (rows.length < GROUP_LIMIT) rows.push(match.item);
    grouped.set(group, rows);
  }
  return [...grouped.entries()]
    .sort(
      ([left], [right]) =>
        (best.get(right) ?? 0) - (best.get(left) ?? 0) || PALETTE_GROUPS.indexOf(left) - PALETTE_GROUPS.indexOf(right),
    )
    .map(([group, rows]) => ({ group, commands: rows }));
}

/** What the palette can do, each the same act as the control it stands for. */
export interface PaletteActions {
  section: (section: Section) => void;
  startRun: () => void;
  schedule: () => void;
  newSpace: () => void;
  toggleRail: () => void;
  theme: (theme: Theme) => void;
  tour: () => void;
  portfolio: () => void;
  marketWatch: () => void;
  space: (id: string) => void;
  run: (id: string) => void;
  agent: (id: string) => void;
  note: (path: string) => void;
}

export interface PaletteInput {
  readonly spaces: readonly SpaceResponse[];
  readonly currentSpaceId: string | null;
  /** The newest first, as the run list keeps them. */
  readonly runs: readonly Run[];
  readonly agents: readonly AgentDef[];
  readonly notes: readonly NoteSummary[];
  /** Whether the sidebar shows its names now, so the row says the opposite. */
  readonly railOpen: boolean;
  readonly theme: Theme;
  readonly actions: PaletteActions;
}

const THEME_ROWS: readonly { theme: Theme; label: string }[] = [
  { theme: "light", label: "Use the light appearance" },
  { theme: "dark", label: "Use the dark appearance" },
  { theme: "system", label: "Match the system's appearance" },
];

/**
 * Every row the palette can show for this window. The default space's own
 * tools (the portfolio and the market watch) are offered only there, as
 * they are only there in the sections themselves.
 */
export function paletteCommands(input: PaletteInput): PaletteCommand[] {
  const { actions } = input;
  const current = input.spaces.find((space) => space.id === input.currentSpaceId) ?? null;
  const commands: PaletteCommand[] = SECTION_ORDER.map((section) => ({
    id: `section-${section}`,
    group: "Sections",
    label: SECTION_LABEL[section],
    keywords: "go to open",
    shortcut: section === "settings" ? "settings" : `section-${section}`,
    run: () => {
      actions.section(section);
    },
  }));

  commands.push(
    { id: "start-run", group: "Actions", label: "Run once", keywords: "start a run new task goal", run: actions.startRun },
    { id: "schedule", group: "Actions", label: "Make a schedule", keywords: "automation recurring repeat", run: actions.schedule },
    { id: "new-space", group: "Actions", label: "New space", keywords: "create add", run: actions.newSpace },
    {
      id: "rail",
      group: "Actions",
      label: input.railOpen ? "Hide the sidebar" : "Show the sidebar",
      keywords: "fold rail sidebar",
      shortcut: "rail",
      run: actions.toggleRail,
    },
    ...THEME_ROWS.filter((row) => row.theme !== input.theme).map(
      (row): PaletteCommand => ({
        id: `theme-${row.theme}`,
        group: "Actions",
        label: row.label,
        keywords: "theme appearance colour color",
        run: () => {
          actions.theme(row.theme);
        },
      }),
    ),
    { id: "tour", group: "Actions", label: "Take the tour again", keywords: "help introduction", run: actions.tour },
  );
  if (current?.is_default === true) {
    commands.push(
      { id: "portfolio", group: "Actions", label: "Edit my portfolio", keywords: "holdings stocks cash limits", run: actions.portfolio },
      { id: "market-watch", group: "Actions", label: "Market watch", keywords: "alerts quotes prices", run: actions.marketWatch },
    );
  }

  for (const space of input.spaces) {
    if (space.id === input.currentSpaceId || space.archived === true) continue;
    commands.push({
      id: `space-${space.id}`,
      group: "Spaces",
      label: `Switch to ${space.name}`,
      detail: space.description,
      keywords: "space",
      run: () => {
        actions.space(space.id);
      },
    });
  }

  for (const run of input.runs) {
    const title = run.title ?? null;
    commands.push({
      id: `run-${run.id}`,
      group: "Runs",
      label: title ?? run.goal,
      detail: title === null ? undefined : run.goal,
      keywords: run.status,
      run: () => {
        actions.run(run.id);
      },
    });
  }

  for (const agent of input.agents) {
    commands.push({
      id: `agent-${agent.id}`,
      group: "Agents",
      label: agent.name,
      detail: agent.role,
      run: () => {
        actions.agent(agent.id);
      },
    });
  }

  for (const note of input.notes) {
    commands.push({
      id: `note-${note.path}`,
      group: "Notes",
      label: note.title,
      detail: note.path,
      run: () => {
        actions.note(note.path);
      },
    });
  }
  return commands;
}
