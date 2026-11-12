import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, sep } from "node:path";

import { describe, expect, it } from "vitest";

import { styleFiles } from "../test/stylesheet";

import { mixedColours, rawColours } from "./colour";
import {
  colourTokens,
  CONTRAST_PAIRS,
  KNOWN_SHORTFALLS,
  namesColour,
  pairContrast,
  pairName,
  parseTokenBlocks,
  themeTokens,
} from "./tokens";

/**
 * The design rules, as tests (Phase 20, brief section 9.4). In the house
 * style, two lists that must agree get a test: here the lists are the three
 * theme blocks, the token file and everything that uses it, and the text
 * colours and the surfaces they sit on.
 */

const SRC = join(import.meta.dirname, "..");
const TOKEN_FILE = "styles/tokens.css";

const files = styleFiles();
const tokenCss = files.find((file) => file.path === TOKEN_FILE)?.css ?? "";
const blocks = parseTokenBlocks(tokenCss);

/** Every file under `src` with one of these endings, as paths relative to `src`. */
function sources(endings: readonly string[], folder = SRC): string[] {
  return readdirSync(folder).flatMap((entry) => {
    const path = join(folder, entry);
    if (statSync(path).isDirectory()) return sources(endings, path);
    return endings.some((ending) => entry.endsWith(ending)) ? [relative(SRC, path).split(sep).join("/")] : [];
  });
}

describe("colour tokens", () => {
  it("are read from the token file", () => {
    // A guard on the reader: a file it misread would pass every rule below.
    expect(colourTokens(blocks).length).toBeGreaterThan(30);
    expect(blocks.light.get("--accent")).toBeDefined();
  });

  it("count as colours in whatever form they are written", () => {
    // A token in a newer colour form must not slip past the three-block rule.
    for (const value of ["oklch(60% 0.15 50)", "color(display-p3 1 0 0)", "hwb(20 10% 20%)", "rebeccapurple"]) {
      expect(namesColour(value), value).toBe(true);
    }
    for (const value of ['ui-monospace, "Gold Mono", monospace', "4px", "var(--info)", "cubic-bezier(0.22, 1, 0.36, 1)"]) {
      expect(namesColour(value), value).toBe(false);
    }
  });

  it("are each defined in all three theme blocks", () => {
    const colours = colourTokens(blocks);
    expect(colours.filter((name) => !blocks.darkBySystem.has(name))).toEqual([]);
    expect(colours.filter((name) => !blocks.darkByChoice.has(name))).toEqual([]);
  });

  it("are the same whether dark comes from the system or from the setting", () => {
    expect([...blocks.darkByChoice]).toEqual([...blocks.darkBySystem]);
  });

  it("add no dark token that light does not have", () => {
    expect([...blocks.darkByChoice.keys()].filter((name) => !blocks.light.has(name))).toEqual([]);
  });
});

describe("raw colours", () => {
  /**
   * What is left outside the token file today, by file. Stage 20.2 moves
   * these into tokens; until then a file may not gain one, and a file that
   * loses one must lower its number here, so the count only goes down.
   */
  const ALLOWED: Readonly<Record<string, number>> = {
    "styles/app.css": 4,
    "styles/buttons.css": 1,
    "styles/home.css": 1,
    "styles/knowledge.css": 3,
    "styles/rail.css": 1,
    "styles/responsive.css": 1,
    "styles/space-switcher.css": 1,
  };

  /** Colours mixed from tokens where they are used, held the same way. */
  const MIXED: Readonly<Record<string, number>> = {
    "styles/app.css": 1,
    "styles/buttons.css": 1,
    "styles/file-views.css": 1,
    "styles/graph.css": 3,
    "styles/knowledge.css": 5,
    "styles/markdown.css": 6,
    "styles/run-panel.css": 6,
    "styles/schedules.css": 2,
    "styles/settings-nav.css": 3,
    "styles/tour.css": 2,
  };

  const imported = new Set(files.map((file) => file.path));
  const sheets = sources([".css"]).filter((path) => path !== TOKEN_FILE);

  function counted(find: (css: string) => string[]): Record<string, number> {
    const found: Record<string, number> = {};
    for (const path of sheets) {
      const count = find(readFileSync(join(SRC, path), "utf8")).length;
      if (count > 0) found[path] = count;
    }
    return found;
  }

  it("covers every stylesheet the app loads", () => {
    // Each file under styles/ is reached from index.css, in the order it lists.
    expect(sheets.filter((path) => path.startsWith("styles/") && !imported.has(path))).toEqual([]);
    expect([...imported].filter((path) => path !== TOKEN_FILE && !sheets.includes(path))).toEqual([]);
  });

  it("are named only in the token file", () => {
    expect(counted(rawColours)).toEqual(ALLOWED);
  });

  it("are not mixed in place beyond what is already there", () => {
    expect(mixedColours(tokenCss)).toEqual([]);
    expect(counted(mixedColours)).toEqual(MIXED);
  });

  it("do not appear in component or library code", () => {
    // Tests hold colours as fixtures, and the design tooling reads them.
    const code = sources([".ts", ".tsx"]).filter(
      (path) => !/\.test\.tsx?$/.test(path) && !path.startsWith("design/") && !path.startsWith("test/"),
    );
    const literal = /#[0-9a-f]{6}\b|#[0-9a-f]{3}\b(?![\w-])|\b(?:rgba?|hsla?)\(/i;
    expect(code.filter((path) => literal.test(readFileSync(join(SRC, path), "utf8")))).toEqual([]);
  });
});

describe("text contrast", () => {
  const measured = (["light", "dark"] as const).flatMap((theme) => {
    const tokens = themeTokens(blocks, theme);
    return CONTRAST_PAIRS.map((pair) => ({ name: pairName(pair, theme), ratio: pairContrast(tokens, pair), min: pair.min }));
  });

  it("meets AA for every listed text and surface pair, in both themes", () => {
    const short = measured.filter((pair) => pair.ratio < pair.min && !KNOWN_SHORTFALLS.has(pair.name));
    expect(short.map((pair) => `${pair.name} is ${pair.ratio.toFixed(2)}:1`)).toEqual([]);
  });

  it("lists as a known shortfall only a pair that still falls short", () => {
    const names = new Set(measured.map((pair) => pair.name));
    expect([...KNOWN_SHORTFALLS].filter((name) => !names.has(name))).toEqual([]);
    const fixed = measured.filter((pair) => pair.ratio >= pair.min && KNOWN_SHORTFALLS.has(pair.name));
    expect(fixed.map((pair) => pair.name)).toEqual([]);
  });

  it("keeps the header's promises about the palette", () => {
    const ratio = (name: string) => measured.find((pair) => pair.name === name)?.ratio ?? 0;
    // "White on the accent is 5.0:1", and `--faint` is the lightest text allowed.
    expect(ratio("light: --on-accent on --accent")).toBeGreaterThanOrEqual(4.5);
    expect(ratio("light: --faint on --surface")).toBeGreaterThanOrEqual(4.5);
    expect(ratio("dark: --faint on --surface")).toBeGreaterThanOrEqual(4.5);
    expect(ratio("light: --faint on --bg")).toBeLessThan(ratio("light: --muted on --bg"));
  });
});
