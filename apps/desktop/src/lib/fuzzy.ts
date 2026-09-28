/**
 * Subsequence matching for quick switching and link completion. Queries must
 * remain ordered; early, word-start, and shorter matches score higher. Handles
 * thousands of titles; vault search serves full-text needs.
 */

export interface FuzzyMatch<T> {
  readonly item: T;
  readonly score: number;
}

/** Match each whitespace-separated query word; sum scores. */
export function fuzzyScore(query: string, text: string): number | null {
  const words = query.trim().split(/\s+/).filter((word) => word !== "");
  if (words.length === 0) return 0;
  let total = 0;
  for (const word of words) {
    const score = wordScore(word, text);
    if (score === null) return null;
    total += score;
  }
  return total;
}

function wordScore(query: string, text: string): number | null {
  const needle = query.toLocaleLowerCase();
  const haystack = text.toLocaleLowerCase();
  const exact = haystack.indexOf(needle);
  if (exact >= 0) return 1000 - exact * 2 - (haystack.length - needle.length) / 4 + (exact === 0 ? 100 : 0);

  let score = 0;
  let position = 0;
  for (const char of needle) {
    const found = haystack.indexOf(char, position);
    if (found < 0) return null;
    const previous = haystack[found - 1];
    const wordStart = found === 0 || previous === undefined || /[\s/_.-]/.test(previous);
    score += wordStart ? 12 : found === position ? 8 : 1;
    position = found + 1;
  }
  return score - haystack.length / 8;
}

/** The items matching `query`, best first; every item when the query is empty. */
export function fuzzyFilter<T>(query: string, items: readonly T[], text: (item: T) => string): FuzzyMatch<T>[] {
  const matches: FuzzyMatch<T>[] = [];
  for (const item of items) {
    const score = fuzzyScore(query, text(item));
    if (score !== null) matches.push({ item, score });
  }
  return matches.sort((left, right) => right.score - left.score);
}
