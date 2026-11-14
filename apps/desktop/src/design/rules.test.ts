import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, sep } from "node:path";

import { describe, expect, it } from "vitest";

import { styleFiles } from "../test/stylesheet";

import { mixedColours, rawColours, withoutComments } from "./colour";
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
    // Stage 20.1 found twelve in seven files; stage 20.2 moved each to a token.
    expect(counted(rawColours)).toEqual({});
  });

  it("are not mixed in place", () => {
    // A `color-mix()` is a colour with no name and no dark value of its own.
    // The thirty that stage 20.1 found are tokens now: -soft, -line and -tint.
    expect(mixedColours(tokenCss)).toEqual([]);
    expect(counted(mixedColours)).toEqual({});
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

describe("text size", () => {
  /** The root size the stylesheet's rem values are multiples of. */
  const ROOT_PX = 15;
  const SMALLEST_PX = 13;

  /** A length in px, when the value states one in px or rem. */
  function pixels(length: string): number | null {
    const match = /^([\d.]+)(px|rem)$/.exec(length);
    if (match === null) return null;
    return Number(match[1]) * (match[2] === "rem" ? ROOT_PX : 1);
  }

  it("is never set below 13 px, by font-size or by the font shorthand", () => {
    // D7: captions are 13 px and the smallest text. A size relative to its
    // parent (em, %) is not read here.
    const small: string[] = [];
    for (const path of sources([".css"])) {
      const css = withoutComments(readFileSync(join(SRC, path), "utf8"));
      for (const [, property = "", value = ""] of css.matchAll(/(?<![-\w])(font-size|font)\s*:\s*([^;{}]+)/g)) {
        // In the shorthand the size is the token before the family, with an
        // optional line height after a slash.
        const sizes = property === "font-size" ? [value.trim()] : value.trim().split(/\s+/).map((part) => part.split("/")[0] ?? "");
        for (const size of sizes) {
          const px = pixels(size);
          if (px !== null && px < SMALLEST_PX && px > 0) small.push(`${path}: ${property}: ${value.trim()}`);
        }
      }
    }
    expect(small).toEqual([]);
  });

  it("has a caption token of 13 px, the smallest size token", () => {
    const sizes = [...blocks.light].filter(([name]) => name.startsWith("--size-")).map(([, value]) => pixels(value) ?? 0);
    expect(sizes.length).toBeGreaterThanOrEqual(7);
    expect(Math.min(...sizes)).toBe(SMALLEST_PX);
    expect(pixels(blocks.light.get("--size-caption") ?? "")).toBe(SMALLEST_PX);
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

  it("keeps the token file's promises about the palette", () => {
    const ratio = (name: string) => measured.find((pair) => pair.name === name)?.ratio ?? 0;
    // "White on the accent is 5.0:1", and `--faint` is the lightest text allowed.
    expect(ratio("light: --on-accent on --accent")).toBeGreaterThanOrEqual(4.5);
    for (const theme of ["light", "dark"]) {
      expect(ratio(`${theme}: --faint on --content`)).toBeGreaterThanOrEqual(4.5);
      expect(ratio(`${theme}: --faint on --window`)).toBeLessThan(ratio(`${theme}: --muted on --window`));
      expect(ratio(`${theme}: --muted on --window`)).toBeLessThan(ratio(`${theme}: --text on --window`));
    }
  });
});

describe("React Flow", () => {
  /* Its stylesheet positions every node; without it a graph draws as a
     stack in a corner, and nothing in the tests draws one. It came with the
     run diagram until D8 retired that, which nearly left Knowledge's graph
     without it, so each file that draws with React Flow loads it itself. */
  it("is drawn only by a file that loads its stylesheet", () => {
    const drawing = sources([".tsx"]).filter((path) => /<ReactFlow\b/.test(readFileSync(join(SRC, path), "utf8")));
    expect(drawing.length).toBeGreaterThan(0);
    const unstyled = drawing.filter((path) => !readFileSync(join(SRC, path), "utf8").includes('import "@xyflow/react/dist/style.css";'));
    expect(unstyled).toEqual([]);
  });
});
