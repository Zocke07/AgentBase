/**
 * Migrate renamed browser preferences. Current AgentBase values win; otherwise
 * copy an AgentSpace fallback so later reads and writes use the current key.
 */
export function readRenamedStorage(key: string, legacyKey: string): string | null {
  try {
    const current = localStorage.getItem(key);
    if (current !== null) return current;

    const legacy = localStorage.getItem(legacyKey);
    if (legacy === null) return null;

    try {
      localStorage.setItem(key, legacy);
    } catch {
      // Use the legacy choice for this view.
    }
    return legacy;
  } catch {
    return null;
  }
}

/** Remove both names when a person explicitly resets a renamed preference. */
export function removeRenamedStorage(key: string, legacyKey: string): void {
  try {
    localStorage.removeItem(key);
  } catch {
    // Browser preference storage is optional.
  }
  try {
    localStorage.removeItem(legacyKey);
  } catch {
    // Failed cleanup must not block the visible update.
  }
}
