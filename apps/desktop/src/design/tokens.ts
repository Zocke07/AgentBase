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
/** Large text, icons and marks. */
const MARK_MIN = 3;

/** The four planes text sits on. */
const PLANES = ["--window", "--sidebar", "--content", "--elevated"] as const;
const STATUS = ["--good", "--bad", "--warn", "--info"] as const;
/** Words in a colour: the accent as text, and the status words. */
const WORDS = ["--accent-strong", ...STATUS] as const;

/** Every text on every ground, with an optional tint laid over the ground. */
const pairs = (
  texts: readonly string[],
  surfaces: readonly string[],
  tint?: string | ((text: string) => string),
  min = TEXT_MIN,
): ContrastPair[] =>
  texts.flatMap((text) =>
    surfaces.map((surface) => ({
      text,
      surface,
      ...(tint === undefined ? {} : { tint: typeof tint === "string" ? tint : tint(text) }),
      min,
    })),
  );

/**
 * Every pair the interface sets text in, and so must hold to AA. The list
 * follows the token file's own rules for where each text level may sit:
 * `--faint` and coloured words on a plane, a quiet fill or a hovered one;
 * `--text` and `--muted` anywhere, a selected or strong fill included.
 */
export const CONTRAST_PAIRS: readonly ContrastPair[] = [
  // On the planes themselves.
  ...pairs(["--text", "--muted", "--faint", ...WORDS], PLANES),
  // On a fill laid over a plane.
  ...pairs(["--text", "--muted", "--faint", ...WORDS], PLANES, "--fill"),
  ...pairs(["--text", "--muted", "--faint", ...WORDS], PLANES, "--fill-hover"),
  ...pairs(["--text", "--muted", "--accent-strong"], PLANES, "--fill-selected"),
  ...pairs(["--text", "--muted"], PLANES, "--fill-strong"),
  // On buttons and fields. A placeholder is faint on a resting field.
  ...pairs(["--text", "--muted"], ["--control", "--control-hover", "--control-pressed"]),
  ...pairs(["--faint", "--accent-strong", "--good", "--bad"], ["--control", "--control-hover"]),
  // On a floating layer's material, over whatever plane it floats above.
  ...pairs(["--text", "--muted", "--faint", ...WORDS], PLANES, "--material"),
  // Text on a solid fill of the accent or a status colour.
  ...pairs(["--on-accent"], ["--accent", "--accent-strong"]),
  { text: "--on-good", surface: "--good", min: TEXT_MIN },
  { text: "--on-bad", surface: "--bad", min: TEXT_MIN },
  { text: "--on-warn", surface: "--warn", min: TEXT_MIN },
  // A coloured word on its own soft fill: badges, notices, chips, the
  // selected row of the rail.
  ...pairs(["--accent-strong"], PLANES, "--accent-soft"),
  ...pairs(STATUS, PLANES, (text) => `${text}-soft`),
  // A highlight in prose, and a hovered soft chip, whose words turn to --text.
  ...pairs(["--text"], PLANES, "--warn-tint"),
  ...pairs(["--text"], PLANES, "--info-tint"),
  // The accent as a mark or an icon, never as running text.
  ...pairs(["--accent"], PLANES, undefined, MARK_MIN),
  ...pairs(["--accent"], PLANES, "--fill-hover", MARK_MIN),
  // Chart series as marks on the plane charts are drawn on.
  ...pairs(["--viz-1", "--viz-2", "--viz-3", "--viz-4", "--viz-5", "--viz-6"], ["--content"], undefined, MARK_MIN),
  // The keyboard's focus ring, a translucent accent laid on the plane.
  ...pairs(["--focus-ring"], PLANES, undefined, MARK_MIN),
];

export const pairName = (pair: ContrastPair, theme: string): string =>
  `${theme}: ${pair.text} on ${pair.tint === undefined ? "" : `${pair.tint} over `}${pair.surface}`;

/**
 * Pairs below their minimum, by `pairName`. Stage 20.1 listed sixteen in the
 * palette it found; stage 20.2's tokens emptied the list, and it stays as the
 * place a later palette change would have to confess a shortfall. A pair
 * listed here that passes fails the rule test, so an entry cannot outlive its
 * reason.
 */
export const KNOWN_SHORTFALLS: ReadonlySet<string> = new Set<string>([]);

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
