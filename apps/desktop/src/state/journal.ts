import type { NoteSummary } from "@agentbase/schemas";

/**
 * The Journal: a space's dated reports read as one page, newest first. Each
 * report stays its own file, because a model can only rewrite a whole file
 * and sees a file's first 20,000 characters; one growing log would have to be
 * copied out and back every day and would hide its newest entries. The page
 * is the log instead. A note joins by the date in its file name; run memories
 * (Saved context) and templates never do.
 */

export interface JournalEntry {
  readonly path: string;
  /** What the note is, such as "Decision"; "Note" for one the pipeline did not write. */
  readonly kind: string;
  readonly title: string;
  /** `2026-10-06`, or `2026-10` for a month's report. */
  readonly date: string;
  readonly updatedAt: string;
}

export interface JournalDay {
  readonly date: string;
  readonly entries: readonly JournalEntry[];
}

/** Reports by where the shipped pipeline writes them, in the order a filter lists them. */
const KINDS: readonly { prefix: string; kind: string }[] = [
  { prefix: "decisions/", kind: "Decision" },
  { prefix: "portfolio/review-", kind: "Portfolio review" },
  { prefix: "scores/review-", kind: "Weekly review" },
  { prefix: "daily/", kind: "Daily note" },
];
const OTHER = "Note";
const LEFT_OUT: readonly string[] = ["memory/", "templates/"];
const DATED = /(\d{4})-(\d{2})(?:-(\d{2}))?/;

/** Every dated note but run memories and templates, newest first. */
export function journalEntries(notes: readonly NoteSummary[]): JournalEntry[] {
  const entries: JournalEntry[] = [];
  for (const note of notes) {
    if (LEFT_OUT.some((folder) => note.path.startsWith(folder))) continue;
    const date = datedName(note.path.slice(note.path.lastIndexOf("/") + 1));
    if (date === null) continue;
    const kind = KINDS.find((known) => note.path.startsWith(known.prefix))?.kind ?? OTHER;
    entries.push({ path: note.path, kind, title: note.title, date, updatedAt: note.updated_at });
  }
  return entries.sort(
    (left, right) =>
      order(right.date).localeCompare(order(left.date)) ||
      Date.parse(right.updatedAt) - Date.parse(left.updatedAt) ||
      left.path.localeCompare(right.path),
  );
}

/** Sorted entries as one group per date. */
export function journalDays(entries: readonly JournalEntry[]): JournalDay[] {
  const days: { date: string; entries: JournalEntry[] }[] = [];
  for (const entry of entries) {
    const last = days.at(-1);
    if (last?.date === entry.date) last.entries.push(entry);
    else days.push({ date: entry.date, entries: [entry] });
  }
  return days;
}

/** The kinds present, the pipeline's own first, for a filter. */
export function journalKinds(entries: readonly JournalEntry[]): string[] {
  const present = new Set(entries.map((entry) => entry.kind));
  return [...KINDS.map((known) => known.kind), OTHER].filter((kind) => present.has(kind));
}

/** "Tuesday, October 6, 2026", or "October 2026" for a month's report. */
export function dayHeading(date: string): string {
  const { at, month } = calendarDate(date);
  return month
    ? at.toLocaleDateString(undefined, { month: "long", year: "numeric" })
    : at.toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long", year: "numeric" });
}

/** "Tue, Oct 6", or "All of October" for a month's report. */
export function shortDay(date: string): string {
  const { at, month } = calendarDate(date);
  return month
    ? `All of ${at.toLocaleDateString(undefined, { month: "long" })}`
    : at.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
}

/** "October 2026", the month a date falls in. */
export function monthHeading(date: string): string {
  return calendarDate(date.slice(0, 7)).at.toLocaleDateString(undefined, { month: "long", year: "numeric" });
}

/** The first real date or month in a file name. */
function datedName(name: string): string | null {
  const match = DATED.exec(name);
  if (match === null) return null;
  const [, year, month, day] = match;
  if (year === undefined || month === undefined) return null;
  const monthNumber = Number(month);
  if (monthNumber < 1 || monthNumber > 12) return null;
  if (day === undefined) return `${year}-${month}`;
  const at = new Date(Number(year), monthNumber - 1, Number(day));
  // Rejects the 31st of a 30-day month, which Date would roll over.
  if (at.getMonth() !== monthNumber - 1 || at.getDate() !== Number(day)) return null;
  return `${year}-${month}-${day}`;
}

/** A month's report heads its month, above that month's days. */
function order(date: string): string {
  return date.length === 7 ? `${date}-32` : date;
}

/** Local calendar date, so no time zone moves it to a neighboring day. */
function calendarDate(date: string): { at: Date; month: boolean } {
  const [year = 1970, month = 1, day = 1] = date.split("-").map(Number);
  return { at: new Date(year, month - 1, day), month: date.length === 7 };
}
