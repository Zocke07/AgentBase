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
        <h3 className="wb-group__title">
          Text contrast, {theme}: {String(CONTRAST_PAIRS.length)} pairs
        </h3>
        {/* A grid of small samples, not a table: there are a few hundred. */}
        <ul className="wb-pairs">
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
            const on = pair.tint === undefined ? pair.surface : `${pair.tint} over ${pair.surface}`;
            return (
              <li
                key={name}
                className="wb-pair"
                data-short={ratio !== null && ratio < pair.min ? "true" : undefined}
                title={`${pair.text} on ${on}, against ${String(pair.min)}:1`}
              >
                <span className="wb-contrast__sample" style={{ color: `var(${pair.text})`, background: ground }}>
                  {pair.text.slice(2)}
                </span>
                <span className="wb-pair__on">{on.replaceAll("--", "")}</span>
                <span className="wb-pair__ratio">
                  {ratio === null ? "not measured" : `${ratio.toFixed(2)}:1, ${verdict(pair, ratio, theme)}`}
                </span>
              </li>
            );
          })}
        </ul>
      </section>
    </div>
  );
}
