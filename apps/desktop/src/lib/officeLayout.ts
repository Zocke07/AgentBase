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
  readonly bounds: Box;
  /**
   * The box a camera frames: the room's full width, from the top of its
   * walls down to the frontmost seat and its label. The floor's empty
   * front corner is left out, so the room is shown larger and the floor runs off the
   * bottom of the view, as it would in a photograph.
   */
  readonly frame: Box;
}

export interface Box {
  readonly x: number;
  readonly y: number;
  readonly width: number;
  readonly height: number;
}

/** Space kept around the room inside its bounds, for labels that overhang. */
const MARGIN = 48;
/** What stands on the floor in front of the frontmost seat, with its label. */
const SEAT_FRONT = 72;

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

  // To one side of the lead desk, so the two never stand in a line.
  const reception = spot(SIDE_MARGIN, RECEPTION_DEPTH);
  const lead = spot(across / 2, LEAD_DEPTH);
  const desks = Array.from({ length: deskCount }, (_, index) => deskSpot(index));
  // Every seat of the first row counts, taken or not: the frame must not
  // move when the second desk arrives.
  const seats = [reception, lead, ...Array.from({ length: DESKS_PER_ROW }, (_, index) => deskSpot(index)), ...desks];
  const frameBottom = Math.min(bottom, Math.max(...seats.map((seat) => seat.y)) + SEAT_FRONT);

  return {
    across,
    depth,
    rows,
    corners,
    reception,
    lead,
    desks,
    // Along the back wall, left to right as the wall runs on screen.
    board: project(across * 0.3, depth, WALL_HEIGHT * 0.62),
    clock: project(across * 0.7, depth, wall + 8),
    meter: project(across * 0.9, depth, wall - 10),
    // On the side wall, between the lead desk and the first row.
    library: project(0, Math.min(depth - 0.8, (LEAD_DEPTH + FIRST_ROW_DEPTH) / 2), wall - 12),
    bounds: { x: left, y: top, width: right - left, height: bottom - top },
    // The sides keep the room's margin: the reception's card keeps its size
    // at every zoom and needs all of it.
    frame: { x: left, y: top, width: right - left, height: frameBottom - top },
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

/**
 * How far the board's card is lifted above its point on the wall, in room
 * pixels. The stylesheet reads it as `--office-board-lift`
 * (`components/office/estimates.ts`, `labelGeometry`), as it reads the two
 * offsets below.
 */
export const BOARD_LIFT = 34;
/** A card with a status and two lines of goal, in screen pixels. */
export const BOARD_CARD_HEIGHT = 72;
/** Clear space kept above the card. */
const CARD_GAP = 8;
/** How far the reception's card hangs below the reception's spot, in room pixels. */
export const RECEPTION_DROP = 44;
/** The reception's card with its two lines, in screen pixels. */
export const RECEPTION_CARD_HEIGHT = 46;
/**
 * How far below a desk's spot its papers start, in room pixels. The lead
 * desk hangs its plate there too: it has the front of the room to itself.
 */
export const PAPERS_DROP = 28;
/** The lead desk's plate with its name and state, in screen pixels. */
export const LEAD_PLATE_HEIGHT = 48;

/**
 * The heights, in screen pixels, of the words that hang outside the frame
 * and keep their size at every zoom, so the camera leaves them room: the
 * board's card above the back wall, and in front, the reception's card and
 * the lead desk's plate and papers. `components/office/estimates.ts`
 * estimates them from the model.
 */
export interface Cards {
  readonly board: number;
  readonly reception: number;
  readonly lead: number;
}

export const CARDS: Cards = { board: BOARD_CARD_HEIGHT, reception: RECEPTION_CARD_HEIGHT, lead: LEAD_PLATE_HEIGHT };

function fitBetween(frame: Box, viewport: Size, headroom: number, footroom: number): Camera {
  const height = viewport.height - headroom - footroom;
  const scale = clamp(Math.min(viewport.width / frame.width, height / frame.height), MIN_ZOOM, 1);
  return {
    scale,
    x: (viewport.width - frame.width * scale) / 2 - frame.x * scale,
    y: headroom + (height - frame.height * scale) / 2 - frame.y * scale,
  };
}

/**
 * The room in its frame, as large as fits without growing past its own
 * size, with the board's card in view above it and the words in front of
 * it below. The cards keep their size at every zoom and hang outside what
 * they belong to, so how much room they need past the frame depends on the
 * scale, and the scale on the room they need. Fit leaving each card's
 * whole height, then again leaving what that fit showed still sticks out,
 * until the scale settles. Each fit is larger than the one before and
 * needs no more room than it was given, so the cards stay clear of the
 * edges at every step. The board's card is given at most a quarter of the
 * view's height and the words in front a fifth: past that the room would
 * shrink until the words lost their own lines to the far zoom band.
 */
export function fitCamera(layout: OfficeLayout, viewport: Size, cards: Cards = CARDS): Camera {
  const { frame } = layout;
  if (viewport.width <= 0 || viewport.height <= 0) return { scale: 1, x: -frame.x, y: -frame.y };
  const most = viewport.height / 4;
  const mostBelow = viewport.height / 5;
  const bottom = frame.y + frame.height;
  // The part of each card that hangs past the frame at a scale: the board's
  // above its wall's margin, the ones in front below the floor in front of the seats.
  const headroom = (scale: number) => clamp(cards.board + CARD_GAP - Math.max(0, (layout.board.y - frame.y - BOARD_LIFT) * scale), CARD_GAP, most);
  const below = (scale: number, spot: Point, drop: number, height: number) => height + CARD_GAP - Math.max(0, (bottom - spot.y - drop) * scale);
  const footroom = (scale: number) =>
    clamp(Math.max(below(scale, layout.reception, RECEPTION_DROP, cards.reception), below(scale, layout.lead, PAPERS_DROP, cards.lead)), 0, mostBelow);
  let camera = fitBetween(frame, viewport, Math.min(most, cards.board + CARD_GAP), Math.min(mostBelow, Math.max(cards.reception, cards.lead) + CARD_GAP));
  for (let pass = 0; pass < 8; pass += 1) {
    const next = fitBetween(frame, viewport, headroom(camera.scale), footroom(camera.scale));
    const settled = next.scale - camera.scale < 0.001;
    camera = next;
    if (settled) break;
  }
  return camera;
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
 * One axis of a camera that never shows more empty margin than it must: a
 * room narrower than the viewport sits in its middle, and a wider one is
 * moved only as far as its own edge.
 */
function within(offset: number, start: number, length: number, room: number, scale: number): number {
  const size = length * scale;
  if (size <= room) return (room - size) / 2 - start * scale;
  return clamp(offset, room - (start + length) * scale, -start * scale);
}

/** Screen pixels of the followed desk kept in view under its focus point: the character and its desk. */
const FOCUS_BELOW = 48;
/** And over it: the character's head. */
const FOCUS_ABOVE = 24;

/** Screen pixels of a desk's words over and under its focus point, at a scale. */
export interface Reach {
  readonly above: number;
  readonly below: number;
}

/**
 * The camera for a room that is followed: the whole room while it fits at a
 * readable size, otherwise the desk at work, as near the middle as the
 * room's edges allow. A desk in a corner is shown with the room around it,
 * not with half the view on the floor outside.
 *
 * `reach(scale)` is how far the followed desk's words stand over and under
 * the focus at that scale: its plate, bubble and papers, which keep their
 * size. The view moves until they are in it, past the room's edge if a
 * desk at the back or the front needs it, as long as the desk itself stays
 * in view.
 */
export function followCamera(
  layout: OfficeLayout,
  viewport: Size,
  focus: Point | null,
  cards: Cards = CARDS,
  reach: (scale: number) => Reach = () => ({ above: 0, below: 0 }),
  /** `fitCamera` for these cards, when the caller has it already. */
  fitted?: Camera,
): Camera {
  const fit = fitted ?? fitCamera(layout, viewport, cards);
  /** Below this the desks are too close for their labels: come in on the work. */
  if (focus === null || fit.scale >= READABLE_ZOOM) return fit;
  // The whole room, not its frame: a desk at the front may be followed too.
  const { bounds } = layout;
  const centred = centreCamera(focus, viewport, FOLLOW_ZOOM);
  const { scale } = centred;
  const words = reach(scale);
  const y = within(centred.y, bounds.y, bounds.height, viewport.height, scale);
  const top = focus.y * scale + y;
  const lowest = Math.max(FOCUS_ABOVE, viewport.height - Math.max(FOCUS_BELOW, words.below));
  // Down for the words over the desk, or up for the words under it; where
  // the view cannot hold both, those over it give way.
  let target = top;
  if (top < words.above) target = Math.min(words.above, Math.max(top, lowest));
  else if (top > lowest && words.below > 0) target = lowest;
  return {
    scale,
    x: within(centred.x, bounds.x, bounds.width, viewport.width, scale),
    y: y + target - top,
  };
}
