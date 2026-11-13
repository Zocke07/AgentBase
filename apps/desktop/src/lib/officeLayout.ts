/**
 * Where everything in the office stands (Phase 20, brief 7.3 and 7.9):
 * arithmetic only, like `graphLayout.ts`. Sizes are declared, never
 * measured, so live and replay lay the room out the same.
 *
 * The floor is a grid in floor units, seen from above at an isometric angle.
 * `across` runs along the front of the room and `depth` from the front to
 * the back wall. The reception is at the front, the lead desk behind it,
 * then rows of up to four worker desks. A desk's place depends only on its
 * own index, so a placed desk never moves when another arrives: the room
 * grows at the back.
 */

export interface Point {
  readonly x: number;
  readonly y: number;
}

export interface Size {
  readonly width: number;
  readonly height: number;
}

/** A place on the floor, and where that is on screen. */
export interface Spot extends Point {
  readonly across: number;
  readonly depth: number;
}

/** Screen pixels per floor unit, along the screen's x and y. */
export const TILE_HALF_WIDTH = 46;
export const TILE_HALF_HEIGHT = 20;
/** How tall the two back walls stand, in pixels. */
export const WALL_HEIGHT = 92;

export const DESKS_PER_ROW = 4;
/** Floor units between desks in a row, and between rows. */
const DESK_PITCH = 3;
const ROW_PITCH = 3.2;
/** Floor units from the side wall to the first desk's centre. */
const SIDE_MARGIN = 1.5;
export const ROOM_ACROSS = SIDE_MARGIN * 2 + DESK_PITCH * (DESKS_PER_ROW - 1);

const RECEPTION_DEPTH = 1.1;
const LEAD_DEPTH = 3.6;
const FIRST_ROW_DEPTH = 7.4;
/** Floor between the last row and the back wall. */
const BACK_MARGIN = 2.2;

/**
 * The order a row's four places fill in: the middle two first, so a small
 * team sits together in the middle of the room and not against a wall.
 */
const FILL_ORDER = [1, 2, 0, 3] as const;

/** A point on the floor (or `height` pixels above it) on screen. */
export function project(across: number, depth: number, height = 0): Point {
  return {
    x: (across + depth) * TILE_HALF_WIDTH,
    y: (across - depth) * TILE_HALF_HEIGHT - height,
  };
}

const spot = (across: number, depth: number): Spot => ({ across, depth, ...project(across, depth) });

/** Where the worker desk with this index stands. It never depends on how many there are. */
export function deskSpot(index: number): Spot {
  const row = Math.floor(index / DESKS_PER_ROW);
  const place = FILL_ORDER[index % DESKS_PER_ROW] ?? 0;
  return spot(SIDE_MARGIN + place * DESK_PITCH, FIRST_ROW_DEPTH + row * ROW_PITCH);
}

export interface OfficeLayout {
  /** The floor's size in floor units. Depth grows with the rows of desks. */
  readonly across: number;
  readonly depth: number;
  readonly rows: number;
  /** The floor's four corners on screen: front-left, back-left, back-right, front-right. */
  readonly corners: readonly [Point, Point, Point, Point];
  readonly reception: Spot;
  readonly lead: Spot;
  /** One spot per worker desk, in desk order. */
  readonly desks: readonly Spot[];
  /** On the back wall, at standing height: the board, the clock, the meter. */
  readonly board: Point;
  readonly clock: Point;
  readonly meter: Point;
  /** On the side wall: the library's shelf. */
  readonly library: Point;
  /** The box that holds the whole room, walls included, with a margin. */
  readonly bounds: { readonly x: number; readonly y: number; readonly width: number; readonly height: number };
}

/** Space kept around the room inside its bounds, for labels that overhang. */
const MARGIN = 48;

export function placeOffice(deskCount: number): OfficeLayout {
  const rows = Math.max(1, Math.ceil(deskCount / DESKS_PER_ROW));
  const depth = FIRST_ROW_DEPTH + (rows - 1) * ROW_PITCH + BACK_MARGIN;
  const across = ROOM_ACROSS;
  const corners = [project(0, 0), project(0, depth), project(across, depth), project(across, 0)] as const;
  const wall = WALL_HEIGHT * 0.55;

  const xs = corners.map((corner) => corner.x);
  const ys = corners.map((corner) => corner.y);
  const left = Math.min(...xs) - MARGIN;
  const top = Math.min(...ys) - WALL_HEIGHT - MARGIN;
  const right = Math.max(...xs) + MARGIN;
  const bottom = Math.max(...ys) + MARGIN;

  return {
    across,
    depth,
    rows,
    corners,
    // To one side of the lead desk, so the two never stand in a line.
    reception: spot(SIDE_MARGIN, RECEPTION_DEPTH),
    lead: spot(across / 2, LEAD_DEPTH),
    desks: Array.from({ length: deskCount }, (_, index) => deskSpot(index)),
    // Along the back wall, left to right as the wall runs on screen.
    board: project(across * 0.3, depth, WALL_HEIGHT * 0.62),
    clock: project(across * 0.7, depth, wall + 8),
    meter: project(across * 0.9, depth, wall - 10),
    // On the side wall, between the lead desk and the first row.
    library: project(0, Math.min(depth - 0.8, (LEAD_DEPTH + FIRST_ROW_DEPTH) / 2), wall - 12),
    bounds: { x: left, y: top, width: right - left, height: bottom - top },
  };
}

/** How much a desk shows: past twenty desks, labels shorten to names. */
export function labelDensity(deskCount: number): "full" | "names" {
  return deskCount > 20 ? "names" : "full";
}

/**
 * How much a desk shows at a zoom. Labels keep their size while the room
 * scales, as on a map, so the further out the camera is the less each desk
 * can say without covering its neighbour: everything, the name and state,
 * or the name alone. The full text stays in the accessible name and tooltip.
 */
export type ZoomBand = "near" | "mid" | "far";

export function zoomBand(scale: number): ZoomBand {
  if (scale >= 0.85) return "near";
  return scale >= 0.55 ? "mid" : "far";
}

// --- camera -------------------------------------------------------------------

/** The room's transform in its viewport: scale about the origin, then move. */
export interface Camera {
  readonly scale: number;
  readonly x: number;
  readonly y: number;
}

export const MIN_ZOOM = 0.3;
export const MAX_ZOOM = 2;
/** The whole room is shown while it fits at this scale or more. */
export const READABLE_ZOOM = 0.7;
/** The scale a followed desk is shown at when the room does not fit. */
export const FOLLOW_ZOOM = 0.9;

const clamp = (value: number, low: number, high: number): number => Math.min(Math.max(value, low), high);

/** The whole room, centred, as large as fits without growing past its own size. */
export function fitCamera(layout: OfficeLayout, viewport: Size): Camera {
  const { bounds } = layout;
  if (viewport.width <= 0 || viewport.height <= 0) return { scale: 1, x: -bounds.x, y: -bounds.y };
  const scale = clamp(Math.min(viewport.width / bounds.width, viewport.height / bounds.height), MIN_ZOOM, 1);
  return {
    scale,
    x: (viewport.width - bounds.width * scale) / 2 - bounds.x * scale,
    y: (viewport.height - bounds.height * scale) / 2 - bounds.y * scale,
  };
}

/** A point of the room in the middle of the viewport, at a zoom. */
export function centreCamera(point: Point, viewport: Size, zoom: number): Camera {
  const scale = clamp(zoom, MIN_ZOOM, MAX_ZOOM);
  return { scale, x: viewport.width / 2 - point.x * scale, y: viewport.height / 2 - point.y * scale };
}

/**
 * Zoom by a factor, keeping the point under the pointer where it is.
 * `anchor` is in viewport pixels.
 */
export function zoomCamera(camera: Camera, factor: number, anchor: Point): Camera {
  const scale = clamp(camera.scale * factor, MIN_ZOOM, MAX_ZOOM);
  const ratio = scale / camera.scale;
  return { scale, x: anchor.x - (anchor.x - camera.x) * ratio, y: anchor.y - (anchor.y - camera.y) * ratio };
}

/**
 * The camera for a room that is followed: the whole room while it fits at a
 * readable size, otherwise the desk at work in the middle.
 */
export function followCamera(layout: OfficeLayout, viewport: Size, focus: Point | null): Camera {
  const fit = fitCamera(layout, viewport);
  /** Below this the desks are too close for their labels: come in on the work. */
  if (focus === null || fit.scale >= READABLE_ZOOM) return fit;
  return centreCamera(focus, viewport, FOLLOW_ZOOM);
}
