import { describe, expect, it } from "vitest";

import { parseTokenBlocks } from "../design/tokens";
import { styleFiles } from "../test/stylesheet";

import { overshoot, settleTime, springEasing, SPRINGS, springTokens, springValue } from "./springs";

const stops = (easing: string): number[] =>
  easing
    .replace(/^linear\(|\)$/g, "")
    .split(",")
    .map((stop) => Number(stop.trim()));

describe("a spring", () => {
  it("starts at rest and ends on its target", () => {
    for (const spring of Object.values(SPRINGS)) {
      expect(springValue(spring, 0)).toBe(0);
      expect(springValue(spring, -1)).toBe(0);
      expect(Math.abs(springValue(spring, settleTime(spring)) - 1)).toBeLessThanOrEqual(0.001);
    }
  });

  it("never passes its target when it has no bounce", () => {
    for (const spring of [SPRINGS.snappy, SPRINGS.smooth]) {
      expect(overshoot(spring)).toBe(0);
      const values = stops(springEasing(spring).easing);
      expect(values).toEqual([...values].sort((left, right) => left - right));
    }
  });

  it("stays settled after its settle time", () => {
    for (const spring of Object.values(SPRINGS)) {
      const from = settleTime(spring);
      for (let seconds = from; seconds < from + 1; seconds += 0.01) {
        expect(Math.abs(springValue(spring, seconds) - 1)).toBeLessThanOrEqual(0.001);
      }
    }
  });

  it("bounces more as its bounce grows", () => {
    expect(overshoot({ duration: 0.3, bounce: 0.4 })).toBeGreaterThan(overshoot({ duration: 0.3, bounce: 0.2 }));
  });
});

describe("the interface's springs", () => {
  it("last about as long as the brief asks", () => {
    expect(springEasing(SPRINGS.snappy).durationMs).toBeGreaterThanOrEqual(250);
    expect(springEasing(SPRINGS.snappy).durationMs).toBeLessThanOrEqual(350);
    expect(springEasing(SPRINGS.smooth).durationMs).toBeGreaterThanOrEqual(400);
    expect(springEasing(SPRINGS.smooth).durationMs).toBeLessThanOrEqual(500);
    expect(springEasing(SPRINGS.bouncy).durationMs).toBeGreaterThanOrEqual(450);
    expect(springEasing(SPRINGS.bouncy).durationMs).toBeLessThanOrEqual(550);
  });

  it("let only the bouncy one overshoot, by 3 to 5%", () => {
    expect(overshoot(SPRINGS.bouncy)).toBeGreaterThanOrEqual(0.03);
    expect(overshoot(SPRINGS.bouncy)).toBeLessThanOrEqual(0.05);
  });

  it("are easings a browser can read: linear(), from 0 to 1", () => {
    for (const spring of Object.values(SPRINGS)) {
      const { easing } = springEasing(spring);
      expect(easing).toMatch(/^linear\((?:-?\d+(?:\.\d+)?)(?:, -?\d+(?:\.\d+)?)+\)$/);
      const values = stops(easing);
      expect(values[0]).toBe(0);
      expect(values.at(-1)).toBe(1);
    }
  });

  it("are the tokens the stylesheet commits", () => {
    // Two lists that must agree: what this module generates, and tokens.css.
    const css = styleFiles().find((file) => file.path === "styles/tokens.css")?.css ?? "";
    const committed = parseTokenBlocks(css).light;
    for (const [name, value] of Object.entries(springTokens())) {
      expect(committed.get(name), name).toBe(value);
    }
  });

  it("have a fallback where linear() is missing", () => {
    const css = styleFiles().find((file) => file.path === "styles/tokens.css")?.css ?? "";
    const fallback = /@supports not \(transition-timing-function: linear\(0, 1\)\)\s*\{([\s\S]*?)\n\}/.exec(css)?.[1] ?? "";
    for (const name of Object.keys(SPRINGS)) {
      expect(fallback).toMatch(new RegExp(`--spring-${name}: cubic-bezier\\(`));
    }
  });
});
