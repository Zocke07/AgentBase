/**
 * Reading event payloads.
 *
 * Payloads are `dict[str, Any]` on the wire — §4 gives each event type a shape
 * by convention, not by schema — so every read here is defensive and returns
 * `null` rather than throwing. A dashboard that crashed on one malformed event
 * would lose a whole run that was otherwise fine, and the log panel exists
 * precisely to be readable when something has gone wrong.
 *
 * These live in one module because the reducer and the event log both read the
 * same payloads, and two sets of accessors would eventually disagree about what
 * a missing field means.
 */

export type Payload = Record<string, unknown>;

/** A string field, or null if it is absent or not a string. */
export function text(payload: Payload, key: string): string | null {
  const value = payload[key];
  return typeof value === "string" ? value : null;
}

/** A finite number field, or null. */
export function int(payload: Payload, key: string): number | null {
  const value = payload[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/** True only when the field is literally `true`. */
export function flag(payload: Payload, key: string): boolean {
  return payload[key] === true;
}

/** The string members of an array field; an empty array otherwise. */
export function strings(payload: Payload, key: string): string[] {
  const value = payload[key];
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
}

/** A nested object field, or an empty object. */
export function record(payload: Payload, key: string): Payload {
  const value = payload[key];
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Payload)
    : {};
}

/**
 * A field rendered for display, whatever it turned out to be.
 *
 * Used only by the log panel, which shows what the payload actually contains
 * rather than what it should contain. `String(unknown)` would render an object
 * as `[object Object]`, so anything that is not already a scalar is serialised.
 */
export function display(payload: Payload, key: string, fallback = "?"): string {
  const value = payload[key];
  if (value === undefined || value === null) return fallback;
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value);
}
