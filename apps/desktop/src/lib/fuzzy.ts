/**
 * Subsequence matching for the quick switcher and link completion: every
 * character of the query must appear in order, and a match scores higher the
 * earlier it starts, the more it sits at word starts, and the shorter the
 * text it is found in. Good enough for a few thousand note titles; not a
 * search engine, which the vault already has.
 */

export interface FuzzyMatch<T> {
  readonly item: T;
  readonly score: number;
}

/** Each whitespace-separated word of the query must match on its own; the score is their sum. */
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
