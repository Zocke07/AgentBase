import type { ReactNode } from "react";

import { SCENARIOS } from "../test/scenarios";

import { ScenarioPlayer } from "./ScenarioPlayer";
import { ControlsPage } from "./pages/ControlsPage";
import { RailPage } from "./pages/RailPage";
import { TokensPage } from "./pages/TokensPage";
import { TypePage } from "./pages/TypePage";

/**
 * The workbench's pages. Each renders one part of the interface from
 * fixtures alone, so it can be looked at, screenshotted and checked for
 * accessibility without a sidecar. A later stage adds its pages here (the
 * icons, the primitives, the shell, the office), and the browser tests pick
 * them up from this list.
 */

export interface PageContext {
  /** The theme the page is drawn in, with "system" already resolved. */
  readonly theme: "light" | "dark";
  /** Where a run page's cursor starts; the end of its log when absent. */
  readonly cursor?: number;
  /** A run page says where its cursor stands, so the link can hold it. */
  readonly onCursor?: (cursor: number) => void;
}

export interface WorkbenchPage {
  /** Stable, used in URLs and screenshot names. */
  readonly id: string;
  readonly title: string;
  readonly group: "Foundations" | "Components" | "Runs";
  /**
   * `flow` pages are as tall as their content; `fill` pages take the height
   * they are given, as the run view takes its window's.
   */
  readonly layout: "flow" | "fill";
  readonly about: string;
  readonly render: (context: PageContext) => ReactNode;
}

export const PAGE_GROUPS: readonly WorkbenchPage["group"][] = ["Foundations", "Components", "Runs"];

export const PAGES: readonly WorkbenchPage[] = [
  {
    id: "tokens",
    title: "Colour tokens",
    group: "Foundations",
    layout: "flow",
    about: "Every colour token in this theme, and the contrast of each listed text and surface pair.",
    render: ({ theme }) => <TokensPage theme={theme} />,
  },
  {
    id: "type",
    title: "Type",
    group: "Foundations",
    layout: "flow",
    about: "The type each kind of text has today, as the browser computed it.",
    render: () => <TypePage />,
  },
  {
    id: "controls",
    title: "Controls",
    group: "Components",
    layout: "flow",
    about: "Buttons, badges, cards, fields and loading placeholders in their states.",
    render: () => <ControlsPage />,
  },
  {
    id: "rail",
    title: "Rail",
    group: "Components",
    layout: "flow",
    about: "The left rail, open and folded.",
    render: () => <RailPage />,
  },
  ...SCENARIOS.map(
    (scenario): WorkbenchPage => ({
      id: `run-${scenario.id}`,
      title: scenario.title,
      group: "Runs",
      layout: "fill",
      about: scenario.about,
      render: ({ cursor, onCursor }) => (
        <ScenarioPlayer
          key={scenario.id}
          scenario={scenario}
          {...(cursor === undefined ? {} : { cursor })}
          {...(onCursor === undefined ? {} : { onCursor })}
        />
      ),
    }),
  ),
];

export function pageById(id: string | null): WorkbenchPage {
  const first = PAGES[0];
  if (first === undefined) throw new Error("The workbench has no pages.");
  return PAGES.find((page) => page.id === id) ?? first;
}
