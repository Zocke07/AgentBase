import { project, type Spot } from "../../lib/officeLayout";

/**
 * Where a desk drawn alone stands (the floor plan's cards, Home's office,
 * the empty states), and the part of the drawing a vignette shows.
 */
export const VIGNETTE_SPOT: Spot = { across: 1, depth: 1, ...project(1, 1) };

/** A viewBox around the vignette's desk: `width` wide, its top `above` the desk's spot. */
export function vignetteView(width: number, height: number, above: number): string {
  return `${String(VIGNETTE_SPOT.x - width / 2)} ${String(VIGNETTE_SPOT.y - above)} ${String(width)} ${String(height)}`;
}
