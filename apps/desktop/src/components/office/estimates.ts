import { PAPERS_DROP, RECEPTION_CARD_HEIGHT, zoomBand, type Cards, type Reach, type ZoomBand } from "../../lib/officeLayout";
import type { Board, Desk, Reception, Slip } from "../../state/office";

/**
 * How tall the room's words stand, in screen pixels, estimated from the
 * model so the camera can leave them room. The words keep their size at
 * every zoom, so the room shrinks under them. Estimated rather than
 * measured: what a label shows changes with the zoom band, and a camera
 * fitted to a measured label could move between bands for ever.
 *
 * The numbers follow `styles/office.css`; a change to a label's lines,
 * padding or offset there is a change here.
 */

/** One line of caption text (`--leading-caption`). */
const LINE = 18;
/** Clear space kept between the words and the view's edge. */
const GAP = 8;

/**
 * File names on the board. The card hangs above the wall at a fixed size, so
 * every line it gains is a line of the room's top it covers; the run's files
 * are listed in the summary above the room.
 */
export const BOARD_FILES = 2;

/**
 * The board card's height, from what it will show. The files count only at
 * the near band, where the card shows them.
 */
export function boardCardHeight(board: Board, band: ZoomBand = "mid"): number {
  const CHARS = 24;
  const wrap = (text: string, most: number) => Math.min(most, Math.max(1, Math.ceil(text.length / CHARS)));
  const parts = [
    1.2,
    wrap(board.goal ?? "Waiting for the run to start", 2),
    board.claim === null ? 0 : 1 + wrap(board.claim.text, 3),
    band !== "near" || board.documents.length === 0 ? 0 : Math.min(board.documents.length, BOARD_FILES) + (board.documents.length > BOARD_FILES ? 1 : 0),
    band !== "near" || board.memoryPath === null ? 0 : 2,
    board.unrecognised.length * 2,
  ].filter((lines) => lines > 0);
  return Math.ceil(16 + parts.reduce((total, lines) => total + lines * LINE, 0) + (parts.length - 1) * 2);
}

/** The reception's card: who started the run, and a line for questions waiting. */
export function receptionCardHeight(reception: Reception): number {
  return RECEPTION_CARD_HEIGHT + (reception.waiting > 0 ? LINE + 4 : 0);
}

/**
 * Both cards and the lead desk's plate, which hang outside the room's frame,
 * at a zoom band. Only the lead's plate, not its papers: room for those
 * would shrink the whole room for a slip, and the floor in front of the lead
 * holds most of them. Following a busy lead keeps them in view.
 */
export function cardsOf(board: Board, reception: Reception, lead: Desk | null, band: ZoomBand = "mid"): Cards {
  return {
    board: boardCardHeight(board, band),
    reception: receptionCardHeight(reception),
    lead: lead === null ? 0 : plateHeight(lead, band),
  };
}

/** The slips a desk shows: handing work on is shown by the folder, not by a slip of paper. */
export function slipsOnDesk(desk: Desk): readonly Slip[] {
  return desk.slips.filter((entry) => entry.family !== "delegation");
}

/** Room pixels from a desk's floor spot to the bottom of its plate (`.office-desk__button`). */
export const PLATE_RISE = 98;
/** Screen pixels from the plate's bottom to the bubble's (`.office-bubble`, 4.4rem). */
const BUBBLE_RISE = 70.4;
/** Characters a line of the bubble holds: 14rem of italic caption. */
const BUBBLE_CHARS_PER_LINE = 30;
/** Characters a line of a desk's papers holds: 11rem of caption. */
const PAPER_CHARS_PER_LINE = 26;
/** How much of an error a desk shows (`TROUBLE_CHARS` in the scene). */
export const TROUBLE_CHARS = 110;

/** The plate: a quiet desk's is its name alone, and the model goes first as the camera draws back. */
function plateHeight(desk: Desk, band: ZoomBand): number {
  const lines = band === "far" || desk.quiet ? 1 : band === "near" && desk.model !== null ? 3 : 2;
  // The lead's name is a headline, a line taller.
  return 10 + lines * LINE + (desk.lead ? 2 : 0);
}

function bubbleHeight(desk: Desk, band: ZoomBand): number {
  if (desk.bubble === null || band === "far") return 0;
  return 8 + Math.max(1, Math.ceil(Math.max(1, desk.bubble.text.length) / BUBBLE_CHARS_PER_LINE)) * LINE;
}

/** The papers under a desk: its trouble, the call in hand, and a line for the calls before it. */
function papersHeight(desk: Desk, band: ZoomBand): number {
  if (band === "far" || desk.quiet) return 0;
  const slips = slipsOnDesk(desk);
  const parts = [
    desk.trouble === null ? 0 : 8 + Math.min(5, Math.ceil(Math.min(desk.trouble.message.length, TROUBLE_CHARS) / PAPER_CHARS_PER_LINE)) * LINE,
    slips.length === 0 ? 0 : 8 + 2 * LINE,
    slips.length > 1 ? LINE : 0,
  ].filter((height) => height > 0);
  return parts.reduce((total, height) => total + height, 0) + Math.max(0, parts.length - 1) * 2;
}

/** The lead desk's words in front of it: its plate, then its papers. */
function leadWordsBelow(desk: Desk, band: ZoomBand): number {
  const papers = papersHeight(desk, band);
  return plateHeight(desk, band) + (papers === 0 ? 0 : 2 + papers);
}

/**
 * How far a desk's words reach over and under the point `rise` room pixels
 * above its floor spot, at a scale. A worker's plate and bubble stand over
 * its head and its papers lie in front of its desk. The lead desk has the
 * front of the room to itself, so its plate and papers hang in front of it
 * and only its bubble stands over its head.
 */
export function deskReach(desk: Desk, scale: number, rise: number): Reach {
  const band = zoomBand(scale);
  const over = (PLATE_RISE - rise) * scale;
  const under = (rise + PAPERS_DROP) * scale;
  const bubble = bubbleHeight(desk, band);
  if (desk.lead) {
    return {
      above: bubble === 0 ? 0 : Math.ceil(over + bubble + GAP),
      below: Math.ceil(under + leadWordsBelow(desk, band) + GAP),
    };
  }
  const papers = papersHeight(desk, band);
  return {
    above: Math.ceil(over + Math.max(plateHeight(desk, band), bubble === 0 ? 0 : BUBBLE_RISE + bubble) + GAP),
    below: papers === 0 ? 0 : Math.ceil(under + papers + GAP),
  };
}
