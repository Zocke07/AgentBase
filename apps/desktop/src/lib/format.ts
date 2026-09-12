/**
 * Rendering helpers shared by the dashboard.
 *
 * Everything here is a pure function of its argument. That is not a style
 * preference: BUILD_SPEC §5 Phase 7 asks that replaying a run produce
 * "pixel-identical UI state to what was shown live", and a single relative
 * timestamp ("3 seconds ago") would make the same event render differently on
 * every fold. Times are therefore absolute and derived from the event's own
 * `ts`, which travels in the log and never changes.
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

/**
 * Integer micros as money.
 *
 * Mirrors `pricing.format_micros` on the backend, which rounds to nearest
 * because a display should be the closest true reading. The backend also sends
 * a pre-formatted string for the budget meter; this exists for the figures that
 * arrive inside event payloads, where only the integer travels.
 */
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

/**
 * `JSON.stringify`, typed as it behaves: it returns `undefined` for a value it
 * cannot serialise: a function, a symbol, `undefined` itself. The lib types
 * say `string`. Nothing off the wire is one of those values, and a log panel
 * that threw on the first one would take the whole run view down with it.
 */
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
