import type { NoteSummary, TextFileSummary } from "@agentbase/schemas";

import { fileKind } from "../lib/visualization";

import { isNote } from "./files";
import { dateInName, monthHeading, reportKind } from "./journal";

/**
 * Knowledge in two sections. User Summary is what a person reads: the
 * reports, notes, workbooks and charts a run or a person wrote. Technical
 * Details is the raw data, settings and records the agents work from, with
 * the vault's own tools. A file belongs to one of them by where it is and
 * what it is, so the same file never sits in both lists.
 *
 * The pipeline's groups (decisions, reviews, alerts, forecast workbooks) are
 * the default space's: its investment pipeline stays there (2026-10-13).
 * Another space's results are notes, daily notes, workbooks and charts.
 */
export type KnowledgeSection = "summary" | "technical";

/** User Summary's groups, in the order the list shows them. */
export const SUMMARY_GROUPS = [
  "Decisions",
  "Portfolio reviews",
  "Weekly reviews",
  "Market alerts",
  "Forecast workbooks",
  "Workbooks",
  "Charts and dashboards",
  "Daily notes",
  "Notes",
] as const;

export type SummaryGroup = (typeof SUMMARY_GROUPS)[number];

/** A result in User Summary. */
export interface SummaryItem {
  readonly path: string;
  /** A Markdown note opens in the reader; anything else in the file view. */
  readonly kind: "note" | "file";
  readonly group: SummaryGroup;
  readonly title: string;
  /** The date in its name, `2026-10-12` or `2026-10`; null when it has none. */
  readonly date: string | null;
  readonly updatedAt: string;
}

const REPORT_GROUPS: Readonly<Record<string, SummaryGroup>> = {
  Decision: "Decisions",
  "Portfolio review": "Portfolio reviews",
  "Weekly review": "Weekly reviews",
  "Market alert": "Market alerts",
  "Daily note": "Daily notes",
};

/**
 * Markdown here is the agents' saved context, scaffolding or collected
 * source text, not a result: it stays under Technical Details.
 */
const BEHIND_THE_SCENES: readonly string[] = ["memory/", "templates/", "raw/"];

/**
 * The User Summary group a file belongs to, or null for Technical Details.
 * `pipeline` is whether the space is the default one, with the pipeline's groups.
 */
export function summaryGroup(path: string, pipeline = true): SummaryGroup | null {
  if (path.split("/").some((part) => part.startsWith("."))) return null;
  if (path.toLocaleLowerCase().endsWith(".xlsx")) return pipeline ? "Forecast workbooks" : "Workbooks";
  const kind = fileKind(path);
  if (kind === "chart" || kind === "dashboard" || kind === "diagram") return "Charts and dashboards";
  if (!isNote(path) || BEHIND_THE_SCENES.some((folder) => path.startsWith(folder))) return null;
  const report = reportKind(path);
  const group = report === null ? "Notes" : (REPORT_GROUPS[report] ?? "Notes");
  return pipeline || group === "Daily notes" ? group : "Notes";
}

/** Which section a file is in. */
export function sectionOf(path: string): KnowledgeSection {
  return summaryGroup(path) === null ? "technical" : "summary";
}

/**
 * Every result for User Summary: notes by their own titles, and workbooks and
 * charts by what they hold. Grouped in list order, newest first in a group.
 */
export function summaryItems(
  notes: readonly NoteSummary[],
  files: readonly TextFileSummary[],
  pipeline = true,
): SummaryItem[] {
  const items: SummaryItem[] = [];
  for (const note of notes) {
    const group = summaryGroup(note.path, pipeline);
    if (group === null) continue;
    items.push({
      path: note.path,
      kind: "note",
      group,
      title: note.title,
      date: dateInName(note.path),
      updatedAt: note.updated_at,
    });
  }
  for (const file of files) {
    const group = summaryGroup(file.path, pipeline);
    if (group === null) continue;
    items.push({
      path: file.path,
      kind: "file",
      group,
      title: fileTitle(file.path, pipeline),
      date: dateInName(file.path),
      updatedAt: file.updated_at,
    });
  }
  return items.sort(
    (left, right) =>
      SUMMARY_GROUPS.indexOf(left.group) - SUMMARY_GROUPS.indexOf(right.group) ||
      (right.date ?? "").localeCompare(left.date ?? "") ||
      Date.parse(right.updatedAt) - Date.parse(left.updatedAt) ||
      left.path.localeCompare(right.path),
  );
}

/** "Forecasts for October 2026"; "Daily change" for `visualizations/daily-change.viz.json`. */
export function fileTitle(path: string, pipeline = true): string {
  const name = path.slice(path.lastIndexOf("/") + 1);
  const monthly = /^(\d{4}-\d{2})\.xlsx$/iu.exec(name);
  if (pipeline && monthly?.[1] !== undefined && path.startsWith("predictions/")) {
    return `Forecasts for ${monthHeading(monthly[1])}`;
  }
  const stem = name.replace(/\.(?:viz\.json|dashboard\.json|mmd|mermaid|xlsx)$/iu, "");
  const words = stem.replace(/[-_]+/gu, " ").trim();
  return words === "" ? name : `${words.charAt(0).toLocaleUpperCase()}${words.slice(1)}`;
}

/** What a file in User Summary is, under its title. */
export function fileNoun(path: string): string {
  if (path.toLocaleLowerCase().endsWith(".xlsx")) return "Excel workbook";
  switch (fileKind(path)) {
    case "chart":
      return "Chart";
    case "dashboard":
      return "Dashboard";
    case "diagram":
      return "Diagram";
    default:
      return "File";
  }
}
