import { useMemo } from "react";

import { parseColour } from "../../design/colour";
import {
  colourTokens,
  CONTRAST_PAIRS,
  KNOWN_SHORTFALLS,
  pairContrast,
  pairName,
  parseTokenBlocks,
  resolveToken,
  themeTokens,
  type ContrastPair,
  type Tokens,
} from "../../design/tokens";
import tokenCss from "../../styles/tokens.css?raw";

/**
 * Every colour token with the value the browser has for it now, and every
 * listed text and surface pair with its contrast ratio, measured from those
 * values. The rule test (`design/rules.test.ts`) holds the same pairs from
 * the token file's text; this page is where a person sees them.
 */

const BLOCKS = parseTokenBlocks(tokenCss);
const NAMES = colourTokens(BLOCKS);

/**
 * The tokens as the document has them. Where the browser reports nothing for
 * a name (no stylesheet, as in a unit test), the token file's own value for
 * the theme stands in.
 */
function liveTokens(theme: "light" | "dark"): Tokens {
  const written = themeTokens(BLOCKS, theme);
  const computed = getComputedStyle(document.documentElement);
  return new Map(
    [...written.keys()].map((name) => [name, computed.getPropertyValue(name).trim() || (resolveToken(written, name) ?? "")]),
  );
}

function verdict(pair: ContrastPair, ratio: number, theme: string): string {
  if (ratio >= pair.min) return "passes";
  return KNOWN_SHORTFALLS.has(pairName(pair, theme)) ? `below ${String(pair.min)}, known` : `below ${String(pair.min)}`;
}

export function TokensPage({ theme }: { theme: "light" | "dark" }) {
  // The workbench puts the theme on the root before it renders a page, so
  // what the browser made of each token can be read here.
  const tokens = useMemo(() => liveTokens(theme), [theme]);

  return (
    <div className="wb-tokens">
      <section>
        <h3 className="wb-group__title">Colour tokens, {theme}</h3>
        <ul className="wb-swatches">
          {NAMES.map((name) => {
            const value = tokens.get(name) ?? "";
            return (
              <li key={name} className="wb-swatch">
                {/* A shadow token holds colours but is not one: it gets no chip. */}
                <span
                  className="wb-swatch__chip"
                  style={parseColour(value) === null ? undefined : { background: `var(${name})` }}
                  aria-hidden="true"
                />
                <span className="wb-swatch__name">{name}</span>
                <span className="wb-swatch__value">{value === "" ? "no value" : value}</span>
              </li>
            );
          })}
        </ul>
      </section>

      <section>
        <h3 className="wb-group__title">Text contrast, {theme}</h3>
        <table className="wb-table">
          <thead>
            <tr>
              <th scope="col">Sample</th>
              <th scope="col">Text</th>
              <th scope="col">On</th>
              <th scope="col">Ratio</th>
              <th scope="col">Against {String(CONTRAST_PAIRS[0]?.min ?? 4.5)}:1</th>
            </tr>
          </thead>
          <tbody>
            {CONTRAST_PAIRS.map((pair) => {
              const name = pairName(pair, theme);
              let ratio: number | null;
              try {
                ratio = pairContrast(tokens, pair);
              } catch {
                ratio = null;
              }
              const ground =
                pair.tint === undefined
                  ? `var(${pair.surface})`
                  : `linear-gradient(var(${pair.tint}), var(${pair.tint})), var(${pair.surface})`;
              return (
                <tr key={name} data-short={ratio !== null && ratio < pair.min ? "true" : undefined}>
                  <td>
                    <span className="wb-contrast__sample" style={{ color: `var(${pair.text})`, background: ground }}>
                      Sample text
                    </span>
                  </td>
                  <td className="wb-table__mono">{pair.text}</td>
                  <td className="wb-table__mono">
                    {pair.tint === undefined ? pair.surface : `${pair.tint} over ${pair.surface}`}
                  </td>
                  <td className="wb-table__figure">{ratio === null ? "?" : `${ratio.toFixed(2)}:1`}</td>
                  <td>{ratio === null ? "not measured" : verdict(pair, ratio, theme)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </section>
    </div>
  );
}
