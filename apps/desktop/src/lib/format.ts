/**
 * Rendering helpers shared by the dashboard. All pure functions of their
 * argument: a relative timestamp would make the same event render differently
 * on every fold, so times are absolute and come from the event's own `ts`.
 */

/** `12:00:05`: the event's own clock time, in the viewer's timezone. */
export function clockTime(iso: string): string {
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return "--:--:--";

  return [at.getHours(), at.getMinutes(), at.getSeconds()]
    .map((part) => String(part).padStart(2, "0"))
    .join(":");
}

/** `2026-09-11 19:03`: the day and the minute, for a list of past runs. */
export function clockDate(iso: string): string {
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return "-";

  const pad = (part: number) => String(part).padStart(2, "0");
  return (
    `${String(at.getFullYear())}-${pad(at.getMonth() + 1)}-${pad(at.getDate())} ` +
    `${pad(at.getHours())}:${pad(at.getMinutes())}`
  );
}

/** `Tue 22 Sep, 09:00` in the viewer's zone: a moment a schedule names, ahead or behind. */
export function whenLabel(iso: string): string {
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return "-";
  return at.toLocaleString(undefined, {
    weekday: "short",
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** `2026-09` as `September 2026`: a ledger period, for a picker. */
export function periodLabel(period: string): string {
  const [year, month] = period.split("-");
  const index = Number(month) - 1;
  const at = new Date(Number(year), Number.isNaN(index) ? 0 : index, 1);
  if (year === undefined || Number.isNaN(at.getTime())) return period;
  return at.toLocaleString(undefined, { month: "long", year: "numeric" });
}

/** `27s`, `1m 32s`, `1h 23m`: a span between two of the log's own timestamps. */
export function formatDuration(milliseconds: number): string {
  const total = Math.max(0, Math.round(milliseconds / 1000));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  if (hours > 0) return `${String(hours)}h ${String(minutes)}m`;
  if (minutes > 0) return `${String(minutes)}m ${String(seconds)}s`;
  return `${String(seconds)}s`;
}

/** Integer micros as money, mirroring the backend's `format_micros`, for figures inside payloads. */
export function formatMicros(micros: number): string {
  return `$${(Math.round(micros) / 1_000_000).toFixed(4)}`;
}

/** `1,234`: thousands separated, for token counts. */
export function formatCount(value: number): string {
  return value.toLocaleString("en-US");
}

/** Truncate for a single line, without lying about it. */
export function ellipsise(value: string, limit: number): string {
  const collapsed = value.replace(/\s+/gu, " ").trim();
  return collapsed.length <= limit ? collapsed : `${collapsed.slice(0, limit - 1)}…`;
}

/** `JSON.stringify`, typed as it behaves: `undefined` for a value it cannot serialise. */
const stringify = (value: unknown): string | undefined => JSON.stringify(value);

/** A one-line rendering of a tool call's arguments, for the log. */
export function summariseArgs(args: Record<string, unknown>): string {
  const parts = Object.entries(args).map(([key, value]) => {
    const rendered = typeof value === "string" ? value : (stringify(value) ?? String(value));
    return `${key}=${ellipsise(rendered, 40)}`;
  });
  return parts.join(" ");
}

/** The CSS modifier for an event type, used to colour the log and the graph. */
export function eventFamily(type: string): string {
  return type.split(".")[0] ?? "other";
}
