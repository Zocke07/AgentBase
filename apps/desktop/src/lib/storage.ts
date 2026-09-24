/**
 * Read a browser preference after the product rename. A current AgentBase
 * value always wins; an AgentSpace value is only a fallback for a browser
 * that has not stored the new name yet. Copying the fallback forward lets all
 * later reads and writes use the current key without dropping a preference.
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
      // The legacy choice can still be used for this view.
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
    // Storage is optional for browser preferences.
  }
  try {
    localStorage.removeItem(legacyKey);
  } catch {
    // A failed cleanup must not stop the visible setting from updating.
  }
}
