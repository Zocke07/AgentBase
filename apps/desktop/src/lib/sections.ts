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
