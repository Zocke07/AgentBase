/** The shell's sections, in rail order, which is also their Ctrl/Cmd+digit shortcut. */

export type Section = "home" | "runs" | "agents" | "knowledge" | "usage" | "space" | "settings";

export const SECTION_ORDER: readonly Section[] = [
  "home",
  "runs",
  "agents",
  "knowledge",
  "usage",
  "space",
  "settings",
];
