import { describe, expect, it } from "vitest";

import { contrast, mixedColours, over, parseColour, rawColours } from "./colour";

describe("parseColour", () => {
  it("reads the forms the stylesheet and a computed style use", () => {
    expect(parseColour("#fff")).toEqual({ r: 255, g: 255, b: 255, a: 1 });
    expect(parseColour("#b8501e")).toEqual({ r: 184, g: 80, b: 30, a: 1 });
    expect(parseColour("#00000080")?.a).toBeCloseTo(0.5, 2);
    expect(parseColour("rgb(184 80 30 / 12%)")).toEqual({ r: 184, g: 80, b: 30, a: 0.12 });
    expect(parseColour("rgba(20, 24, 40, 0.06)")).toEqual({ r: 20, g: 24, b: 40, a: 0.06 });
    expect(parseColour(" rgb(26, 30, 41) ")).toEqual({ r: 26, g: 30, b: 41, a: 1 });
  });

  it("refuses what it does not understand rather than guessing", () => {
    for (const value of ["", "var(--text)", "#12345", "transparent", "hsl(10 20% 30%)", "0 1px 2px rgb(0 0 0 / 6%)"]) {
      expect(parseColour(value), value).toBeNull();
    }
  });
});

describe("contrast", () => {
  const colour = (value: string) => {
    const parsed = parseColour(value);
    if (parsed === null) throw new Error(value);
    return parsed;
  };

  it("matches WCAG's published ends and a known middle", () => {
    expect(contrast(colour("#000"), colour("#fff"))).toBeCloseTo(21, 5);
    expect(contrast(colour("#fff"), colour("#fff"))).toBeCloseTo(1, 5);
    // #767676 on white is the well-known grey that just reaches 4.5:1.
    expect(contrast(colour("#767676"), colour("#fff"))).toBeCloseTo(4.54, 2);
  });

  it("is the same whichever of the two is lighter", () => {
    expect(contrast(colour("#1a1e29"), colour("#f3f4f7"))).toBeCloseTo(contrast(colour("#f3f4f7"), colour("#1a1e29")), 10);
  });

  it("lays translucent text over its surface before measuring", () => {
    const half = colour("rgb(0 0 0 / 50%)");
    expect(over(half, colour("#fff"))).toEqual({ r: 127.5, g: 127.5, b: 127.5, a: 1 });
    expect(contrast(half, colour("#fff"))).toBeCloseTo(contrast(colour("rgb(127.5 127.5 127.5)"), colour("#fff")), 10);
  });
});

describe("rawColours", () => {
  it("finds hex, colour functions and named colours", () => {
    expect(rawColours(".a { color: #FFF; border: 1px solid rgb(0 0 0 / 20%); background: white; }")).toEqual([
      "#FFF",
      "rgb(",
      "white",
    ]);
  });

  it("finds the newer colour functions and every named colour", () => {
    const css = ".a { color: oklch(60% 0.15 50); fill: color(display-p3 1 0 0); stroke: silver; outline-color: Tomato }";
    expect(rawColours(css)).toEqual(["oklch(", "color(", "silver", "Tomato"]);
  });

  it("reads declarations, not selectors or quoted text", () => {
    const css = `
      #fade, #ace:hover, .tan > a:focus { font-family: "Gold Sans", 'Linen', system-ui; content: "red"; }
      @media (min-width: 800px) { .snow { animation: pulse 1s; transition: color 1s; } }
    `;
    expect(rawColours(css)).toEqual([]);
  });

  it("leaves tokens, keywords, properties and comments alone", () => {
    const css = `
      /* was #ff0000, then red */
      .a { color: var(--text); background: transparent; fill: currentColor; white-space: nowrap; }
      .b { border-color: var(--border-strong); }
      .blue-chip, #red { color: var(--blue); }
    `;
    expect(rawColours(css)).toEqual([]);
  });

  it("counts a mix of tokens apart from a literal", () => {
    const css = ".a { background: color-mix(in srgb, var(--bad) 10%, var(--surface)); }";
    expect(rawColours(css)).toEqual([]);
    expect(mixedColours(css)).toHaveLength(1);
    expect(mixedColours("/* color-mix( */ .a { color: var(--text); }")).toEqual([]);
  });
});
