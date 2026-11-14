import { render } from "@testing-library/react";
import axe from "axe-core";
import { describe, expect, it } from "vitest";
import { page } from "vitest/browser";

import { applyEnvironment, DEFAULT_ENVIRONMENT } from "./environment";
import { PAGES, type WorkbenchPage } from "./pages";

/**
 * Every workbench page in each engine: compared with its committed
 * screenshot and checked by axe. A page added to `PAGES` is covered without
 * touching this file.
 */

type Theme = "light" | "dark";

/** The window every page is drawn in; a tall page grows the height. */
const WIDTH = 1100;
const HEIGHT = 720;

/**
 * Pages also compared in the dark theme. Every page is compared in light;
 * dark differs from light only through the tokens, so a few pages that
 * between them use every token family show a dark regression without
 * doubling the baselines kept in the repository. Axe checks every page in
 * both themes, which costs no file.
 */
const DARK_TOO: ReadonlySet<string> = new Set([
  // Not the token page: it is the largest baseline by far, the rule test
  // holds every value on it, and the shape page shows the dark planes.
  "type",
  "shape",
  "controls",
  "primitives",
  "rail",
  "shell",
  "floor",
  "usage",
  "empty",
  "office-two-agents",
  "office-shell-question",
  "office-stuck-worker",
  // Every pose, the lamp and the risk colours of a raised card.
  "office-characters",
]);

/**
 * A page as the comparison sees it. A `fill` page takes the window's height,
 * as the run view does in the app. A `flow` page is as tall as its content,
 * so the screenshot holds all of it and nothing hides below a fold.
 */
async function show(entry: WorkbenchPage, theme: Theme) {
  applyEnvironment({ ...DEFAULT_ENVIRONMENT, theme });
  await page.viewport(WIDTH, HEIGHT);
  const frame = entry.layout === "fill" ? { height: "100vh" } : { overflow: "visible" };
  const rendered = render(
    <main className="wb__page" data-testid="specimen" tabIndex={0} style={frame}>
      {entry.render({ theme })}
    </main>,
  );
  if (entry.layout === "flow") {
    // The test's frame clips what it does not show, so it grows to the page.
    const specimen = rendered.getByTestId("specimen");
    await page.viewport(WIDTH, Math.max(HEIGHT, Math.ceil(specimen.getBoundingClientRect().height)));
  }
  return rendered;
}

const cases = (theme: Theme) =>
  PAGES.filter((entry) => theme === "light" || DARK_TOO.has(entry.id)).map((entry) => [entry.id, entry] as const);

describe.each(["light", "dark"] as const)("workbench pages, %s", (theme) => {
  it.each(cases(theme))("%s matches its screenshot", async (id, entry) => {
    await show(entry, theme);
    await expect.element(page.getByTestId("specimen")).toMatchScreenshot(`${id}-${theme}`);
  });
});

/**
 * Serious findings allowed to stand, by page and theme. Stage 20.1 listed
 * three in the interface it found (the dark Allow button, the error count
 * badge, the space switcher's name); stage 20.2 fixed them and emptied the
 * list. It stays as the place a finding would have to be confessed: one
 * listed here that no longer occurs fails the test.
 */
const KNOWN_FINDINGS: Readonly<Record<string, readonly string[]>> = {};

/** The element a finding is about, without the path axe took to reach it. */
function where(target: readonly unknown[]): string {
  const selector = target.at(-1);
  const last = (typeof selector === "string" ? selector : "").split(" > ").at(-1) ?? "";
  return last.replace(/\[[^\]]*\]/g, "").replace(/:nth-child\(\d+\)/g, "");
}

describe.each(["light", "dark"] as const)("workbench pages, %s, accessibility", (theme) => {
  it.each(PAGES.map((entry) => [entry.id, entry] as const))("%s has no new serious finding", async (id, entry) => {
    const { container } = await show(entry, theme);
    const results = await axe.run(
      {
        include: [container],
        // The token page's samples are drawn in the pairs they measure, short
        // ones included; the page says each ratio in words beside them.
        exclude: [".wb-contrast__sample"],
      },
      { resultTypes: ["violations"] },
    );
    const serious = results.violations
      .filter((violation) => violation.impact === "serious" || violation.impact === "critical")
      .flatMap((violation) => violation.nodes.map((node) => `${violation.id}: ${where(node.target)}`));
    expect([...new Set(serious)].sort()).toEqual([...(KNOWN_FINDINGS[`${id}/${theme}`] ?? [])].sort());
  });
});
