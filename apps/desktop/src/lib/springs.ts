/**
 * Springs as CSS `linear()` easings (Phase 20, brief section 5.1).
 *
 * CSS has no spring timing function, so a spring is sampled into a
 * `linear()` curve and a duration: the time the spring takes to settle. The
 * curves are committed as tokens in `styles/tokens.css`, and
 * `springs.test.ts` holds each token to what this module generates, so the
 * numbers in the stylesheet always have a source.
 *
 * A spring is described the way a person tunes one: how long it seems to
 * take, and how much it bounces. Mass is 1, so stiffness is `(2π / duration)²`
 * and damping is `(1 - bounce) · 4π / duration`; bounce 0 is critically
 * damped and never passes its target.
 */

export interface Spring {
  /** Perceived length in seconds. The spring settles some time after it. */
  readonly duration: number;
  /** 0 never overshoots; toward 1 it overshoots and rings more. */
  readonly bounce: number;
}

/** How close to rest counts as settled: a tenth of a percent of the travel. */
const TOLERANCE = 0.001;

/** Samples in a generated curve, ends included. Enough that no kink shows. */
const POINTS = 24;

/** The spring's position at `seconds`, travelling from 0 toward 1. */
export function springValue(spring: Spring, seconds: number): number {
  if (seconds <= 0) return 0;
  const omega = (2 * Math.PI) / spring.duration;
  const zeta = 1 - spring.bounce;
  if (zeta >= 1) {
    // Critically damped: the fastest approach with no overshoot.
    return 1 - (1 + omega * seconds) * Math.exp(-omega * seconds);
  }
  const damped = omega * Math.sqrt(1 - zeta * zeta);
  const decay = Math.exp(-zeta * omega * seconds);
  return 1 - decay * (Math.cos(damped * seconds) + ((zeta * omega) / damped) * Math.sin(damped * seconds));
}

/**
 * When the spring has come to rest: the first moment after which it stays
 * within the tolerance of its target. Found by walking back from well past
 * the end, so a late ring of a bouncy spring is not missed.
 */
export function settleTime(spring: Spring): number {
  const step = 0.001;
  const horizon = spring.duration * 6;
  for (let seconds = horizon; seconds > 0; seconds -= step) {
    if (Math.abs(springValue(spring, seconds) - 1) > TOLERANCE) return seconds + step;
  }
  return step;
}

export interface SpringEasing {
  /** A CSS `linear()` easing that starts at 0 and ends at 1. */
  readonly easing: string;
  /** The duration the easing is drawn for, in whole milliseconds. */
  readonly durationMs: number;
}

/** At most three decimals, without a trailing zero. */
const number = (value: number): string => String(Number(value.toFixed(3)));

/** Sample a spring into a `linear()` easing over the time it takes to settle. */
export function springEasing(spring: Spring): SpringEasing {
  // Rounded to 10 ms: a token reads better, and nobody sees the difference.
  const durationMs = Math.round((settleTime(spring) * 1000) / 10) * 10;
  const stops = Array.from({ length: POINTS }, (_, index) => {
    if (index === 0) return "0";
    if (index === POINTS - 1) return "1";
    return number(springValue(spring, ((durationMs / 1000) * index) / (POINTS - 1)));
  });
  return { easing: `linear(${stops.join(", ")})`, durationMs };
}

/**
 * The three springs the interface uses.
 *
 * - snappy: controls and menus, about 0.3 s, no overshoot;
 * - smooth: panels, sheets and the camera, about 0.45 s, no overshoot;
 * - bouncy: arrivals, about 0.5 s, passing its target by 3 to 5%.
 */
export const SPRINGS = {
  snappy: { duration: 0.2, bounce: 0 },
  smooth: { duration: 0.3, bounce: 0 },
  bouncy: { duration: 0.32, bounce: 0.28 },
} as const satisfies Record<string, Spring>;

export type SpringName = keyof typeof SPRINGS;

/** How far past its target a spring travels at most, as a fraction. */
export function overshoot(spring: Spring): number {
  const { durationMs } = springEasing(spring);
  let peak = 1;
  for (let ms = 0; ms <= durationMs; ms += 1) peak = Math.max(peak, springValue(spring, ms / 1000));
  return peak - 1;
}

/** The tokens the stylesheet commits: an easing and a duration per spring. */
export function springTokens(): Record<string, string> {
  const tokens: Record<string, string> = {};
  for (const [name, spring] of Object.entries(SPRINGS)) {
    const { easing, durationMs } = springEasing(spring);
    tokens[`--spring-${name}`] = easing;
    tokens[`--spring-${name}-duration`] = `${String(durationMs)}ms`;
  }
  return tokens;
}
