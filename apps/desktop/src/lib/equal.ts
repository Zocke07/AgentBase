/**
 * Whether two values hold the same data: equal primitives, or arrays and
 * plain objects whose entries hold the same data. For models a projection
 * rebuilds on every event (the office's desks), so a component can skip a
 * render when nothing it shows changed, without a list of fields that a
 * new field could be missing from.
 */
export function sameData(a: unknown, b: unknown): boolean {
  if (Object.is(a, b)) return true;
  if (typeof a !== "object" || typeof b !== "object" || a === null || b === null) return false;
  if (Array.isArray(a) !== Array.isArray(b)) return false;
  if (Array.isArray(a) && Array.isArray(b)) return a.length === b.length && a.every((entry, index) => sameData(entry, b[index]));
  const left = a as Record<string, unknown>;
  const right = b as Record<string, unknown>;
  const keys = Object.keys(left);
  return keys.length === Object.keys(right).length && keys.every((key) => Object.hasOwn(right, key) && sameData(left[key], right[key]));
}
