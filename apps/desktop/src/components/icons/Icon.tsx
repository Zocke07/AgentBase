import { createElement } from "react";

import { ICONS, type IconName } from "./paths";

/**
 * The one icon component (Phase 20, brief 4.4): Lucide's shapes in one style.
 * Strokes are 1.5 px at every size, with round caps and joins, in the text's
 * colour. An icon is decoration beside a word unless it is given a `label`,
 * in which case it is an image with that name.
 */

export type { IconName } from "./paths";

/** The sizes icons are drawn at, in CSS pixels. */
export type IconSize = 16 | 20 | 24;

export interface IconProps {
  name: IconName;
  size?: IconSize | undefined;
  /** A soft fill behind the strokes: the selected row of the rail. */
  filled?: boolean | undefined;
  /** Names the icon for a screen reader. Without it the icon is hidden. */
  label?: string | undefined;
  className?: string | undefined;
}

/** Lucide draws on a 24 px grid. */
const GRID = 24;
/** The stroke every icon has on screen, whatever size it is drawn at. */
const STROKE_PX = 1.5;

export function Icon({ name, size = 20, filled = false, label, className }: IconProps) {
  const classes = ["icon", filled ? "icon--filled" : "", className ?? ""].filter((part) => part !== "").join(" ");
  return (
    <svg
      className={classes}
      data-icon={name}
      viewBox={`0 0 ${String(GRID)} ${String(GRID)}`}
      width={size}
      height={size}
      // In grid units, so the stroke stays 1.5 px when the icon is scaled.
      strokeWidth={(STROKE_PX * GRID) / size}
      {...(label === undefined ? { "aria-hidden": true } : { role: "img", "aria-label": label })}
    >
      {ICONS[name].map(([shape, attributes], index) => createElement(shape, { key: index, ...attributes }))}
    </svg>
  );
}
