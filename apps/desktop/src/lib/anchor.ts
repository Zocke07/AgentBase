/**
 * Where a floating panel goes beside the control that opened it: arithmetic
 * only, so the rule can be tested without a layout engine. The panel opens
 * on its preferred side, flips to the other when it would not fit there and
 * would fit better opposite, and is then slid back inside the window.
 */

export interface Box {
  readonly top: number;
  readonly left: number;
  readonly width: number;
  readonly height: number;
}

export interface Size {
  readonly width: number;
  readonly height: number;
}

/** The side of the anchor the panel opens on. */
export type Side = "bottom" | "top";
/** Which edge of the anchor the panel lines up with. */
export type Align = "start" | "center" | "end";

export interface Placement {
  readonly side: Side;
  readonly align: Align;
}

export interface Placed {
  readonly top: number;
  readonly left: number;
  /** The side the panel ended on, after any flip. */
  readonly side: Side;
  /** Room left for the panel's height on that side, for a scrolling panel. */
  readonly maxHeight: number;
}

/** Space kept between the panel and its anchor. */
export const ANCHOR_GAP = 6;
/** Space kept between the panel and the window's edge. */
export const WINDOW_MARGIN = 8;

const clamp = (value: number, low: number, high: number): number => Math.min(Math.max(value, low), Math.max(low, high));

export function placePanel(anchor: Box, panel: Size, viewport: Size, wanted: Placement): Placed {
  const below = viewport.height - (anchor.top + anchor.height) - ANCHOR_GAP - WINDOW_MARGIN;
  const above = anchor.top - ANCHOR_GAP - WINDOW_MARGIN;
  const room = (side: Side) => (side === "bottom" ? below : above);
  const other: Side = wanted.side === "bottom" ? "top" : "bottom";
  // Flip only when the panel does not fit and the other side has more room.
  const side = panel.height > room(wanted.side) && room(other) > room(wanted.side) ? other : wanted.side;

  const rawTop = side === "bottom" ? anchor.top + anchor.height + ANCHOR_GAP : anchor.top - ANCHOR_GAP - panel.height;
  const rawLeft =
    wanted.align === "start"
      ? anchor.left
      : wanted.align === "end"
        ? anchor.left + anchor.width - panel.width
        : anchor.left + (anchor.width - panel.width) / 2;

  return {
    top: Math.round(clamp(rawTop, WINDOW_MARGIN, viewport.height - WINDOW_MARGIN - panel.height)),
    left: Math.round(clamp(rawLeft, WINDOW_MARGIN, viewport.width - WINDOW_MARGIN - panel.width)),
    side,
    maxHeight: Math.max(0, Math.floor(room(side))),
  };
}
