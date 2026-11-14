/** The shell's sections, in rail order, which is also their Ctrl/Cmd+digit shortcut.
    Automations come second: working on its own is the primary way a space runs. */

export type Section =
  | "home"
  | "automations"
  | "runs"
  | "agents"
  | "knowledge"
  | "usage"
  | "space"
  | "settings";

export const SECTION_ORDER: readonly Section[] = [
  "home",
  "automations",
  "runs",
  "agents",
  "knowledge",
  "usage",
  "space",
  "settings",
];

/** Each section's name, as the rail, the toolbar and the palette say it. */
export const SECTION_LABEL: Readonly<Record<Section, string>> = {
  home: "Home",
  automations: "Automations",
  runs: "Runs",
  agents: "Agents",
  knowledge: "Knowledge",
  usage: "Usage",
  space: "Space settings",
  settings: "Settings",
};
