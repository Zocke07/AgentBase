/**
 * Reading event payloads. They are `dict[str, Any]` on the wire, so every read
 * returns `null` rather than throwing: one malformed event must not lose the
 * run. Shared by the reducer and the log panel so they agree on what a
 * missing field means.
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

/** A field rendered for display, whatever it turned out to be; objects are serialised. */
export function display(payload: Payload, key: string, fallback = "?"): string {
  const value = payload[key];
  if (value === undefined || value === null) return fallback;
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value);
}
