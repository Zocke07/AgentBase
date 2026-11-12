/**
 * Colour arithmetic for the design rules: reading a CSS colour, laying a
 * translucent one over a surface, and WCAG 2 contrast. The rule tests and the
 * workbench's token page share it, so the ratio a person sees in the workbench
 * is the ratio the test holds.
 */

/** Channels 0 to 255, alpha 0 to 1. */
export interface Rgba {
  readonly r: number;
  readonly g: number;
  readonly b: number;
  readonly a: number;
}

const HEX = /^#([0-9a-f]{3,8})$/i;
const RGB = /^rgba?\(\s*([\d.]+)[\s,]+([\d.]+)[\s,]+([\d.]+)(?:\s*[/,]\s*([\d.]+)(%?))?\s*\)$/i;

/**
 * Read the colour forms this stylesheet and a browser's computed style use:
 * hex with 3, 4, 6 or 8 digits, and `rgb()` or `rgba()` with spaces or
 * commas. Anything else is null rather than a guess.
 */
export function parseColour(value: string): Rgba | null {
  const text = value.trim();

  const hex = HEX.exec(text)?.[1];
  if (hex !== undefined) {
    if (hex.length === 5 || hex.length === 7) return null;
    const short = hex.length <= 4;
    const channel = (index: number): number => {
      const digits = short ? (hex[index] ?? "0").repeat(2) : hex.slice(index * 2, index * 2 + 2);
      return Number.parseInt(digits, 16);
    };
    const hasAlpha = hex.length === 4 || hex.length === 8;
    return { r: channel(0), g: channel(1), b: channel(2), a: hasAlpha ? channel(3) / 255 : 1 };
  }

  const rgb = RGB.exec(text);
  if (rgb !== null) {
    const [, r = "0", g = "0", b = "0", alpha, percent] = rgb;
    const a = alpha === undefined ? 1 : Number(alpha) / (percent === "%" ? 100 : 1);
    return { r: Number(r), g: Number(g), b: Number(b), a: Math.min(1, Math.max(0, a)) };
  }

  return null;
}

/** A translucent colour as it looks over an opaque surface. */
export function over(top: Rgba, surface: Rgba): Rgba {
  const mix = (above: number, below: number) => above * top.a + below * (1 - top.a);
  return { r: mix(top.r, surface.r), g: mix(top.g, surface.g), b: mix(top.b, surface.b), a: 1 };
}

/** WCAG 2 relative luminance of an opaque colour. */
export function luminance(colour: Rgba): number {
  const linear = (channel: number): number => {
    const unit = channel / 255;
    return unit <= 0.04045 ? unit / 12.92 : ((unit + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * linear(colour.r) + 0.7152 * linear(colour.g) + 0.0722 * linear(colour.b);
}

/** WCAG 2 contrast ratio, from 1 (the same colour) to 21 (black on white). */
export function contrast(text: Rgba, surface: Rgba): number {
  const base = surface.a < 1 ? { ...surface, a: 1 } : surface;
  const drawn = text.a < 1 ? over(text, base) : text;
  const [light, dark] = [luminance(drawn), luminance(base)].sort((left, right) => right - left) as [number, number];
  return (light + 0.05) / (dark + 0.05);
}

/** Hex, or a function that states a colour. `color-mix()` is counted apart. */
const LITERAL = /#[0-9a-f]{3,8}\b|\b(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch|color)\(/gi;

/** Every CSS named colour. `transparent` and `currentColor` are keywords, not colours. */
const NAMED_COLOURS: ReadonlySet<string> = new Set(
  (
    "aliceblue antiquewhite aqua aquamarine azure beige bisque black blanchedalmond blue blueviolet brown burlywood " +
    "cadetblue chartreuse chocolate coral cornflowerblue cornsilk crimson cyan darkblue darkcyan darkgoldenrod darkgray " +
    "darkgreen darkgrey darkkhaki darkmagenta darkolivegreen darkorange darkorchid darkred darksalmon darkseagreen " +
    "darkslateblue darkslategray darkslategrey darkturquoise darkviolet deeppink deepskyblue dimgray dimgrey dodgerblue " +
    "firebrick floralwhite forestgreen fuchsia gainsboro ghostwhite gold goldenrod gray green greenyellow grey honeydew " +
    "hotpink indianred indigo ivory khaki lavender lavenderblush lawngreen lemonchiffon lightblue lightcoral lightcyan " +
    "lightgoldenrodyellow lightgray lightgreen lightgrey lightpink lightsalmon lightseagreen lightskyblue lightslategray " +
    "lightslategrey lightsteelblue lightyellow lime limegreen linen magenta maroon mediumaquamarine mediumblue " +
    "mediumorchid mediumpurple mediumseagreen mediumslateblue mediumspringgreen mediumturquoise mediumvioletred " +
    "midnightblue mintcream mistyrose moccasin navajowhite navy oldlace olive olivedrab orange orangered orchid " +
    "palegoldenrod palegreen paleturquoise palevioletred papayawhip peachpuff peru pink plum powderblue purple " +
    "rebeccapurple red rosybrown royalblue saddlebrown salmon sandybrown seagreen seashell sienna silver skyblue " +
    "slateblue slategray slategrey snow springgreen steelblue tan teal thistle tomato turquoise violet wheat white " +
    "whitesmoke yellow yellowgreen"
  ).split(" "),
);

/** A bare word: not part of a longer name, a token, a class, an id or a function call. */
const WORD = /(?<![-\w.#])[a-z]+(?![-\w(])/gi;

/** CSS with its comments blanked, so prose about a colour is not a colour. */
export function withoutComments(css: string): string {
  return css.replace(/\/\*[\s\S]*?\*\//g, (comment) => comment.replace(/[^\n]/g, " "));
}

/**
 * Every colour one declaration's value states itself: hex, a colour
 * function, or a named colour. `transparent`, `currentColor` and
 * `var(--token)` state none. Quoted text, such as a font's name, is not read.
 */
export function coloursIn(value: string): string[] {
  const text = value.replace(/"[^"]*"|'[^']*'/g, '""');
  const named = (text.match(WORD) ?? []).filter((word) => NAMED_COLOURS.has(word.toLowerCase()));
  return [...(text.match(LITERAL) ?? []), ...named];
}

/**
 * Every raw colour a stylesheet names, read from its declarations' values,
 * so a selector such as `#fade` or `.red` is not mistaken for one.
 */
export function rawColours(css: string): string[] {
  const text = withoutComments(css).replace(/"[^"]*"|'[^']*'/g, '""');
  return [...text.matchAll(/:\s*([^;{}]+)(?=[;}])/g)].flatMap(([, value = ""]) => coloursIn(value));
}

/**
 * Colours mixed where they are used: `color-mix()` of tokens. Not a literal,
 * but a colour with no name and no dark value of its own, so the rules count
 * it apart from the literals.
 */
export function mixedColours(css: string): string[] {
  return withoutComments(css).match(/\bcolor-mix\(/gi) ?? [];
}
