/**
 * Rendering helpers shared by the dashboard.
 *
 * Everything here is a pure function of its argument. That is not a style
 * preference: BUILD_SPEC §5 Phase 7 asks that replaying a run produce
 * "pixel-identical UI state to what was shown live", and a single relative
 * timestamp — "3 seconds ago" — would make the same event render differently on
 * every fold. Times are therefore absolute and derived from the event's own
 * `ts`, which travels in the log and never changes.
 */

/** `12:00:05` — the event's own clock time, in the viewer's timezone. */
export function clockTime(iso: string): string {
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return "--:--:--";

  return [at.getHours(), at.getMinutes(), at.getSeconds()]
    .map((part) => String(part).padStart(2, "0"))
    .join(":");
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

/** `1,234` — thousands separated, for token counts. */
export function formatCount(value: number): string {
  return value.toLocaleString("en-US");
}

/** Truncate for a single line, without lying about it. */
export function ellipsise(value: string, limit: number): string {
  const collapsed = value.replace(/\s+/gu, " ").trim();
  return collapsed.length <= limit ? collapsed : `${collapsed.slice(0, limit - 1)}…`;
}

/** A one-line rendering of a tool call's arguments, for the log. */
export function summariseArgs(args: Record<string, unknown>): string {
  const parts = Object.entries(args).map(([key, value]) => {
    const rendered = typeof value === "string" ? value : JSON.stringify(value);
    return `${key}=${ellipsise(rendered, 40)}`;
  });
  return parts.join(" ");
}

/** The CSS modifier for an event type, used to colour the log and the graph. */
export function eventFamily(type: string): string {
  return type.split(".")[0] ?? "other";
}
