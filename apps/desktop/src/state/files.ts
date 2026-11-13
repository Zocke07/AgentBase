import { toolInfo } from "../lib/tools";

import type { RunView } from "./reducer";

/** A space file a run wrote, and where it opens. */
export interface WrittenFile {
  readonly path: string;
  /** Markdown opens as a note; anything else opens in Agent files. */
  readonly kind: "note" | "file";
}

/**
 * Tools that list what they wrote in their result's `written` array. Others
 * return read or fetched text, which is untrusted, so a `written` key in it
 * must not become a file link.
 */
const reportsWritten = (tool: string): boolean => toolInfo(tool).reportsWritten;

/**
 * Files a run wrote, from its executed calls, once each in the order written.
 * Only answered calls count: a refused or failed write changed nothing. The
 * log is the source, so a replay lists the same files as the live run did.
 */
export function writtenFiles(view: RunView): WrittenFile[] {
  const seen = new Set<string>();
  const files: WrittenFile[] = [];
  const add = (path: unknown) => {
    if (typeof path !== "string" || path === "" || seen.has(path)) return;
    seen.add(path);
    files.push({ path, kind: isNote(path) ? "note" : "file" });
  };
  for (const call of view.toolCalls) {
    if (call.result === null) continue;
    if (call.tool === "write_file") add(call.args.path);
    else if (reportsWritten(call.tool)) reportedPaths(call.result).forEach(add);
  }
  return files;
}

export function isNote(path: string): boolean {
  return path.toLocaleLowerCase().endsWith(".md");
}

/** Folders the shipped pipeline's runs fill with working data, a day at a time. */
const WORKING_FOLDERS: readonly string[] = ["raw/", "theses/", "risk/", "scores/"];
const WORKING_FILES: ReadonlySet<string> = new Set(["portfolio/computed.json", "portfolio/weights.csv", "predictions/forecasts.json"]);

/**
 * A data file runs write for each other rather than for a person to read: the
 * lists fold these away so the reports and the inputs a person keeps stand out.
 * Notes are never working files, and nothing outside these folders is.
 */
export function isWorkingFile(path: string): boolean {
  return !isNote(path) && (WORKING_FILES.has(path) || WORKING_FOLDERS.some((folder) => path.startsWith(folder)));
}

/** `decisions/2026-10-06.md` as its file name and its folder. */
export function splitPath(path: string): { name: string; folder: string } {
  const separator = path.lastIndexOf("/");
  return separator < 0
    ? { name: path, folder: "" }
    : { name: path.slice(separator + 1), folder: path.slice(0, separator) };
}

function reportedPaths(result: string): unknown[] {
  try {
    const parsed: unknown = JSON.parse(result);
    if (typeof parsed === "object" && parsed !== null && "written" in parsed) {
      return Array.isArray(parsed.written) ? parsed.written : [];
    }
  } catch {
    // Not JSON: nothing reported.
  }
  return [];
}
