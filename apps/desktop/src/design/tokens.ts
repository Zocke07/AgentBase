import { coloursIn, contrast, over, parseColour, type Rgba } from "./colour";

/**
 * The stylesheet's tokens, read from its text. Every colour token is defined
 * three times: light on `:root`, dark under the OS preference, and dark again
 * under the explicit override. Nothing below the token file knows which theme
 * it is in, so a token missing from one block is a colour that does not
 * change with the theme.
 */

export type Tokens = ReadonlyMap<string, string>;

export interface TokenBlocks {
  /** `:root`. */
  readonly light: Tokens;
  /** `@media (prefers-color-scheme: dark)`, unless the light theme is chosen. */
  readonly darkBySystem: Tokens;
  /** `:root[data-theme="dark"]`. */
  readonly darkByChoice: Tokens;
}

const LIGHT = ":root {";
const DARK_BY_SYSTEM = ':root:not([data-theme="light"]) {';
const DARK_BY_CHOICE = ':root[data-theme="dark"] {';

/** The declarations of the first rule that opens with `opening`. */
function declarations(css: string, opening: string): Tokens {
  const start = css.indexOf(opening);
  if (start < 0) throw new Error(`The token file has no "${opening}" block.`);
  const end = css.indexOf("}", start);
  const found = new Map<string, string>();
  for (const [, name = "", value = ""] of css.slice(start + opening.length, end).matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)) {
    found.set(name, value.trim());
  }
  return found;
}

/** Read the three theme blocks out of the token file's text. */
export function parseTokenBlocks(css: string): TokenBlocks {
  const text = css.replace(/\/\*[\s\S]*?\*\//g, "");
  return {
    light: declarations(text, LIGHT),
    darkBySystem: declarations(text, DARK_BY_SYSTEM),
    darkByChoice: declarations(text, DARK_BY_CHOICE),
  };
}

/** A theme's tokens: the light values, with the dark block laid over them. */
export function themeTokens(blocks: TokenBlocks, theme: "light" | "dark"): Tokens {
  return theme === "light" ? blocks.light : new Map([...blocks.light, ...blocks.darkByChoice]);
}

/** A token's value with every `var(--other)` followed to its end. */
export function resolveToken(tokens: Tokens, name: string, depth = 0): string | null {
  const value = tokens.get(name);
  if (value === undefined || depth > 8) return null;
  const reference = /^var\((--[\w-]+)\)$/.exec(value)?.[1];
  return reference === undefined ? value : resolveToken(tokens, reference, depth + 1);
}

/**
 * Whether a value states a colour itself, rather than pointing at a token.
 * The same reading as the raw-colour rule, so a token written in any colour
 * form is held to all three theme blocks.
 */
export function namesColour(value: string): boolean {
  return coloursIn(value).length > 0;
}

/** The tokens whose light value names a colour. */
export function colourTokens(blocks: TokenBlocks): string[] {
  return [...blocks.light].filter(([, value]) => namesColour(value)).map(([name]) => name);
}

// --- contrast ----------------------------------------------------------------

/**
 * Text on a surface. `tint` is a translucent fill between them, such as a
 * badge's soft background, which is laid over the surface first.
 */
export interface ContrastPair {
  readonly text: string;
  readonly surface: string;
  readonly tint?: string;
  /** 4.5 for text; 3 for large text and icons. */
  readonly min: number;
}

const TEXT_MIN = 4.5;
const pairs = (texts: readonly string[], surfaces: readonly string[], tint?: (text: string) => string): ContrastPair[] =>
  texts.flatMap((text) =>
    surfaces.map((surface) => ({ text, surface, ...(tint === undefined ? {} : { tint: tint(text) }), min: TEXT_MIN })),
  );

const STATUS = ["--good", "--bad", "--warn", "--info"] as const;

/** Every pair the interface sets text in, and so must hold to AA. */
export const CONTRAST_PAIRS: readonly ContrastPair[] = [
  ...pairs(["--text", "--muted"], ["--bg", "--surface", "--surface-2", "--surface-3"]),
  // The lightest text allowed, and words in the accent or a status colour.
  ...pairs(["--faint", "--accent", "--accent-strong", ...STATUS], ["--bg", "--surface", "--surface-2", "--surface-3"]),
  { text: "--on-accent", surface: "--accent", min: TEXT_MIN },
  // A status word on its own soft fill: badges, notices and chips.
  ...pairs(["--accent-strong"], ["--bg", "--surface"], () => "--accent-soft"),
  ...pairs(STATUS, ["--bg", "--surface"], (text) => `${text}-soft`),
];

export const pairName = (pair: ContrastPair, theme: string): string =>
  `${theme}: ${pair.text} on ${pair.tint === undefined ? "" : `${pair.tint} over `}${pair.surface}`;

/**
 * Pairs below their minimum in today's palette, by `pairName`. Stage 20.1
 * changes nothing a person can see, so it records them instead of retuning a
 * colour; stage 20.2's tokens must empty this list. A pair listed here that
 * now passes fails the rule test, so the list cannot outlive its reason.
 */
export const KNOWN_SHORTFALLS: ReadonlySet<string> = new Set([
  "light: --faint on --surface-2",
  "light: --faint on --surface-3",
  "light: --accent on --surface-2",
  "light: --accent on --surface-3",
  "light: --good on --surface-3",
  "light: --bad on --surface-2",
  "light: --bad on --surface-3",
  "light: --warn on --surface-3",
  "light: --info on --surface-3",
  "light: --good on --good-soft over --bg",
  "light: --bad on --bad-soft over --bg",
  "light: --bad on --bad-soft over --surface",
  "light: --warn on --warn-soft over --bg",
  "light: --info on --info-soft over --bg",
  "dark: --faint on --surface-2",
  "dark: --faint on --surface-3",
]);

function colourOf(tokens: Tokens, name: string): Rgba {
  const value = resolveToken(tokens, name);
  const colour = value === null ? null : parseColour(value);
  if (colour === null) throw new Error(`${name} is not a colour this reader understands: ${String(value)}`);
  return colour;
}

/** A pair's contrast ratio under one theme's tokens. */
export function pairContrast(tokens: Tokens, pair: ContrastPair): number {
  const surface = colourOf(tokens, pair.surface);
  const ground = pair.tint === undefined ? surface : over(colourOf(tokens, pair.tint), surface);
  return contrast(colourOf(tokens, pair.text), ground);
}
