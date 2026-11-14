import type { ReactNode } from "react";

import { SCENARIOS } from "../test/scenarios";

import { ScenarioPlayer } from "./ScenarioPlayer";
import { CharactersPage } from "./pages/CharactersPage";
import { ControlsPage } from "./pages/ControlsPage";
import { IconsPage } from "./pages/IconsPage";
import { PrimitivesPage } from "./pages/PrimitivesPage";
import { RailPage } from "./pages/RailPage";
import { ShapePage } from "./pages/ShapePage";
import { TokensPage } from "./pages/TokensPage";
import { TypePage } from "./pages/TypePage";

/**
 * The workbench's pages. Each renders one part of the interface from
 * fixtures alone, so it can be looked at, screenshotted and checked for
 * accessibility without a sidecar. A later stage adds its pages here (the
 * shell, the office), and the browser tests pick them up from this list.
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
  readonly group: "Foundations" | "Components" | "Office";
  /**
   * `flow` pages are as tall as their content; `fill` pages take the height
   * they are given, as the run view takes its window's.
   */
  readonly layout: "flow" | "fill";
  readonly about: string;
  readonly render: (context: PageContext) => ReactNode;
}

export const PAGE_GROUPS: readonly WorkbenchPage["group"][] = ["Foundations", "Components", "Office"];

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
    about: "The type scale, with what the browser computed for each style.",
    render: () => <TypePage />,
  },
  {
    id: "icons",
    title: "Icons",
    group: "Foundations",
    layout: "flow",
    about: "Every vendored icon at 16, 20 and 24 px, and filled.",
    render: () => <IconsPage />,
  },
  {
    id: "shape",
    title: "Shape, depth and motion",
    group: "Foundations",
    layout: "flow",
    about: "Space, radii, elevation, planes and fills, the floating material and the springs.",
    render: () => <ShapePage />,
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
    id: "primitives",
    title: "Primitives",
    group: "Components",
    layout: "flow",
    about: "Icon buttons, the switch, the segmented choice, and the menu, popover and sheet, live and at rest.",
    render: () => <PrimitivesPage />,
  },
  {
    id: "rail",
    title: "Rail",
    group: "Components",
    layout: "flow",
    about: "The left rail, open and folded.",
    render: () => <RailPage />,
  },
  {
    id: "office-characters",
    title: "Characters",
    group: "Office",
    layout: "flow",
    about: "Every pose a desk's figure takes, alone and large: the arms, the lamp, a raised card in each risk, the tray and the books.",
    render: () => <CharactersPage />,
  },
  // Each made-up run, drawn as the office from its own log.
  ...SCENARIOS.map(
    (scenario): WorkbenchPage => ({
      id: `office-${scenario.id}`,
      title: scenario.title,
      group: "Office",
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
