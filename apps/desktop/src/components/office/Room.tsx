import { createElement, memo, type CSSProperties, type ReactNode } from "react";

import { silhouetteOf } from "../../lib/character";
import { project, WALL_HEIGHT, type OfficeLayout, type Point, type Spot } from "../../lib/officeLayout";
import type { Desk, Face, Folder, OfficeModel } from "../../state/office";
import { ICONS } from "../icons/paths";

import { FAMILY_ICON } from "./glyphs";

/**
 * The room, its furniture and the characters, as one inline SVG (Phase 20,
 * decision D2). It is decoration for the eye and hidden from a screen
 * reader: every fact drawn here is also a word in the layer of real elements
 * over it. Nothing in it reads a clock or keeps state; it is drawn from the
 * model and the layout alone.
 */

const points = (list: readonly Point[]): string => list.map((point) => `${String(point.x)},${String(point.y)}`).join(" ");

/** A box standing on the floor: its top and its two visible sides. */
function Box({
  across,
  depth,
  width,
  length,
  height,
  lift = 0,
  className,
}: {
  across: number;
  depth: number;
  /** Extent along the front of the room, and from front to back, in floor units. */
  width: number;
  length: number;
  /** In pixels. */
  height: number;
  lift?: number;
  className: string;
}) {
  const a0 = across - width / 2;
  const a1 = across + width / 2;
  const d0 = depth - length / 2;
  const d1 = depth + length / 2;
  const top = (a: number, d: number) => project(a, d, lift + height);
  const base = (a: number, d: number) => project(a, d, lift);
  return (
    <g className={className}>
      {/* The side facing the front of the room, then the side facing its open end. */}
      <polygon className="office-box__left" points={points([top(a0, d0), top(a1, d0), base(a1, d0), base(a0, d0)])} />
      <polygon className="office-box__right" points={points([top(a1, d0), top(a1, d1), base(a1, d1), base(a1, d0)])} />
      <polygon className="office-box__top" points={points([top(a0, d0), top(a0, d1), top(a1, d1), top(a1, d0)])} />
    </g>
  );
}

/** What the display on a character's head shows. */
function FaceGlyph({ face, desk }: { face: Face; desk: Desk }) {
  switch (face) {
    case "dot":
      return <circle className="office-face__ink" cx="0" cy="0" r="2.4" />;
    case "asking":
    case "thinking":
      return (
        <g className={`office-face__dots office-face__dots--${face}`}>
          <circle className="office-face__ink" cx="-6" cy="0" r="2" />
          <circle className="office-face__ink" cx="0" cy="0" r="2" />
          <circle className="office-face__ink" cx="6" cy="0" r="2" />
        </g>
      );
    case "question":
      return <path className="office-face__line" d="M-3 -3.5a3.2 3.2 0 1 1 4.6 2.9c-1 .6-1.6 1.2-1.6 2.3M0 5.4v.2" />;
    case "tick":
      return <path className="office-face__line" d="M-5 0.5 -1.5 4 5.5 -3.5" />;
    case "knot":
      return <path className="office-face__line" d="M-6 0c2-4 4-4 6 0s4 4 6 0" />;
    case "alert":
      return <path className="office-face__line" d="M0 -5v5.5M0 4.6v.2" />;
    case "tool": {
      const icon = FAMILY_ICON[desk.family ?? "unknown"];
      return (
        <g className="office-face__tool" transform="translate(-6 -6) scale(0.5)">
          {ICONS[icon].map(([shape, attributes], index) => createElement(shape, { key: index, ...attributes }))}
        </g>
      );
    }
  }
}

/**
 * An arm: the upper arm from the shoulder and the forearm from the elbow,
 * drawn hanging. The pose is two rotations in `styles/office.css`, keyed on
 * the character's activity, about the shoulder and the elbow: a transform,
 * so stage 20.5 can move from pose to pose with a transition alone.
 */
function Arm({ side, children }: { side: "left" | "right"; children?: ReactNode }) {
  const x = side === "left" ? -1 : 1;
  return (
    <g className={`office-character__arm office-character__arm--${side}`}>
      <path className="office-character__part" d={`M${String(11 * x)} -17L${String(13 * x)} -8`} />
      <g className="office-character__forearm">
        <path className="office-character__part" d={`M${String(13 * x)} -8V1`} />
        {children}
      </g>
    </g>
  );
}

/** The risk of the question a desk is raising its card for. */
function askingRisk(desk: Desk): string {
  return desk.slips.findLast((slip) => slip.state === "waiting")?.risk ?? "medium";
}

/** A desk companion: a rounded body and a head whose face is a display. */
function Character({ desk, at }: { desk: Desk; at: Point }) {
  const shape = silhouetteOf(desk.name);
  const head = shape.head === "wide" ? { w: 34, h: 22, r: 8 } : shape.head === "square" ? { w: 28, h: 24, r: 6 } : { w: 28, h: 26, r: 13 };
  return (
    <g className={`office-character office-character--${desk.activity}`} transform={`translate(${String(at.x)} ${String(at.y)}) scale(1.25)`}>
      <g className="office-character__pose">
        <Arm side="left" />
        <rect className="office-character__body" x="-13" y="-22" width="26" height="24" rx="9" />
        {shape.antenna >= 1 && <path className="office-character__part" d={`M${shape.antenna === 2 ? "-5" : "0"} ${String(-24 - head.h)}v-7`} />}
        {shape.antenna === 2 && <path className="office-character__part" d={`M5 ${String(-24 - head.h)}v-7`} />}
        {shape.ears && (
          <>
            <rect className="office-character__shade" x={-head.w / 2 - 4} y={-24 - head.h / 2 - 5} width="5" height="10" rx="2" />
            <rect className="office-character__shade" x={head.w / 2 - 1} y={-24 - head.h / 2 - 5} width="5" height="10" rx="2" />
          </>
        )}
        <rect className="office-character__head" x={-head.w / 2} y={-24 - head.h} width={head.w} height={head.h} rx={head.r} />
        <rect className="office-character__display" x={-head.w / 2 + 3} y={-24 - head.h + 4} width={head.w - 6} height={head.h - 8} rx={Math.max(3, head.r - 4)} />
        {shape.visor && <path className="office-character__shade-line" d={`M${String(-head.w / 2 + 3)} ${String(-24 - head.h + 4)}h${String(head.w - 6)}`} />}
        <g transform={`translate(0 ${String(-24 - head.h / 2)})`}>
          <FaceGlyph face={desk.face} desk={desk} />
        </g>
        {/* In front of the body, so a raised card or a hand at the head shows. */}
        <Arm side="right">
          {desk.activity === "waiting" && (
            <rect className={`office-character__card office-character__card--${askingRisk(desk)}`} x="9" y="1" width="9" height="12" rx="1.5" />
          )}
        </Arm>
      </g>
    </g>
  );
}

/**
 * The desk lamp, at the desk's back left corner: on while the agent is at
 * work, low once it has finished. Its light is a pool on the desk top.
 */
function Lamp({ spot, lit }: { spot: Spot; lit: boolean }) {
  const base = project(spot.across - 0.38, spot.depth + 0.16, DESK.height);
  const pool = project(spot.across - 0.15, spot.depth + 0.02, DESK.height);
  return (
    <g className={`office-lamp${lit ? " office-lamp--on" : ""}`}>
      {lit && <ellipse className="office-lamp__light" cx={pool.x} cy={pool.y} rx="22" ry="9" />}
      <ellipse className="office-lamp__base" cx={base.x} cy={base.y} rx="5" ry="2.2" />
      <path className="office-lamp__stem" d={`M${String(base.x)} ${String(base.y)}v-16l7 -5`} />
      <path className="office-lamp__shade" d={`M${String(base.x + 3)} ${String(base.y - 24)}l9 2 -1 6 -10 -2z`} />
    </g>
  );
}

/**
 * A folder of delegated work, lying where the model says it is. A folder on
 * its way also knows where it came from, as an offset in room pixels; the
 * stylesheet moves it from there when it appears (brief 7.8). The offset is
 * the layout's, so it is the same live and on replay.
 */
function FolderShape({ at, phase, from }: { at: Point; phase: Folder["phase"]; from?: Point | undefined }) {
  const travel = from === undefined ? undefined : ({ "--from-x": `${String(from.x - at.x)}px`, "--from-y": `${String(from.y - at.y)}px` } as CSSProperties);
  return (
    <g className={`office-folder office-folder--${phase}`} transform={`translate(${String(at.x)} ${String(at.y)})`}>
      <g className="office-folder__body" style={travel}>
        <path className="office-folder__back" d="M-9 -7h6l2 2h10v10h-18z" />
        <path className="office-folder__front" d="M-9 -2h18v7h-18z" />
      </g>
    </g>
  );
}

const DESK = { width: 1.05, length: 0.55, height: 24 } as const;

interface DeskArtProps {
  desk: Desk;
  spot: Spot;
  /** Books the library handed this desk: the lead's, one per excerpt the run was given. */
  books?: number;
  children?: ReactNode;
}

/** At most this many sheets or books are stacked on a desk; the words say how many. */
const STACK = 4;

/**
 * What the drawing of a desk depends on. The model makes new desk objects
 * on every event, but a streamed token changes nothing drawn here, so a
 * desk is redrawn only when one of these does.
 */
function sameDeskArt(before: DeskArtProps, after: DeskArtProps): boolean {
  const a = before.desk;
  const b = after.desk;
  return (
    before.spot === after.spot &&
    before.books === after.books &&
    a.name === b.name &&
    a.face === b.face &&
    a.family === b.family &&
    a.activity === b.activity &&
    (a.activity !== "waiting" || askingRisk(a) === askingRisk(b)) &&
    a.ghost === b.ghost &&
    a.trouble?.kind === b.trouble?.kind &&
    Math.min(a.documents.length, STACK) === Math.min(b.documents.length, STACK) &&
    a.inbox.length === b.inbox.length &&
    a.inbox.every((folder, index) => folder.seq === b.inbox[index]?.seq)
  );
}

function DeskArt({ desk, spot, books = 0, children }: DeskArtProps) {
  const shadow = project(spot.across + 0.05, spot.depth - 0.05);
  const seat = project(spot.across, spot.depth + 0.5, 8);
  const top = project(spot.across - 0.28, spot.depth, DESK.height);
  return (
    <g className={`office-desk-art${desk.ghost ? " office-desk-art--ghost" : ""}${desk.trouble?.kind === "alarm" ? " office-desk-art--alarm" : ""}`}>
      <ellipse className="office-shadow" cx={shadow.x} cy={shadow.y + 3} rx="52" ry="20" />
      {/* The chair, then whoever sits on it, then the desk in front of both. */}
      <Box across={spot.across} depth={spot.depth + 0.5} width={0.4} length={0.22} height={30} className="office-box office-box--chair" />
      {!desk.ghost && <Character desk={desk} at={seat} />}
      <Box across={spot.across} depth={spot.depth} width={DESK.width} length={DESK.length} height={DESK.height} className="office-box office-box--desk" />
      {!desk.ghost && <Lamp spot={spot} lit={desk.activity !== "completed"} />}
      {/* The tray: one sheet per file the desk wrote, the newest on top. */}
      {Array.from({ length: Math.min(desk.documents.length, STACK) }, (_, index) => (
        <Box
          key={`sheet-${String(index)}`}
          across={spot.across + 0.2 - index * 0.02}
          depth={spot.depth + 0.08}
          width={0.3}
          length={0.22}
          height={1.5}
          lift={DESK.height + index * 2.5}
          className="office-box office-box--paper"
        />
      ))}
      {/* The library's books, handed to the lead desk at the start. */}
      {Array.from({ length: Math.min(books, STACK) }, (_, index) => (
        <Box
          key={`book-${String(index)}`}
          across={spot.across - 0.3}
          depth={spot.depth - 0.08}
          width={0.28}
          length={0.2}
          height={4}
          lift={DESK.height + index * 4.5}
          className="office-box office-box--book"
        />
      ))}
      {desk.inbox.map((folder, index) => (
        <FolderShape key={folder.seq} at={{ x: top.x - index * 5, y: top.y - index * 3 }} phase={folder.phase} />
      ))}
      {children}
    </g>
  );
}

const DeskGroup = memo(DeskArt, sameDeskArt);

/** One desk drawn alone, for the workbench's page of poses. */
export function DeskFigure({ desk, spot, books = 0 }: { desk: Desk; spot: Spot; books?: number }) {
  return <DeskGroup desk={desk} spot={spot} books={books} />;
}

export interface RoomProps {
  model: OfficeModel;
  layout: OfficeLayout;
}

/** Painter's order: what is further back is drawn first. */
const frontness = (spot: Spot): number => spot.across - spot.depth;

function RoomArt({ model, layout }: RoomProps) {
  const [frontLeft, backLeft, backRight, frontRight] = layout.corners;
  const up = (point: Point): Point => ({ x: point.x, y: point.y - WALL_HEIGHT });
  const { bounds } = layout;

  const seated: { desk: Desk; spot: Spot }[] = model.desks.flatMap((desk, index) => {
    const spot = layout.desks[index];
    return spot === undefined ? [] : [{ desk, spot }];
  });
  if (model.lead !== null) seated.push({ desk: model.lead, spot: layout.lead });
  seated.sort((left, right) => frontness(left.spot) - frontness(right.spot));

  const spotOf = (name: string): Spot | null => seated.find((entry) => entry.desk.name === name)?.spot ?? null;
  const books = Math.min(model.library.length, 8);
  const shelf = layout.library;

  return (
    <svg
      className={`office-room${model.lit ? "" : " office-room--unlit"}${model.dimmed ? " office-room--dimmed" : ""}`}
      viewBox={`${String(bounds.x)} ${String(bounds.y)} ${String(bounds.width)} ${String(bounds.height)}`}
      width={bounds.width}
      height={bounds.height}
      style={{ left: bounds.x, top: bounds.y }}
      aria-hidden="true"
      focusable="false"
    >
      <polygon className="office-wall office-wall--side" points={points([frontLeft, backLeft, up(backLeft), up(frontLeft)])} />
      <polygon className="office-wall office-wall--back" points={points([backLeft, backRight, up(backRight), up(backLeft)])} />
      <polygon className="office-floor" points={points([frontLeft, backLeft, backRight, frontRight])} />
      {/* Floor lines along the rows, so depth reads at a glance. */}
      {Array.from({ length: Math.floor(layout.depth) }, (_, index) => {
        const from = project(0, index + 1);
        const to = project(layout.across, index + 1);
        return <line key={index} className="office-floor__line" x1={from.x} y1={from.y} x2={to.x} y2={to.y} />;
      })}

      {/* On the side wall: the library, one book per excerpt the run was given. */}
      <g className="office-shelf" transform={`translate(${String(shelf.x)} ${String(shelf.y)})`}>
        <path className="office-shelf__board" d="M-30 6 30 -24v5L-30 11z" />
        {Array.from({ length: books }, (_, index) => (
          <path key={index} className="office-shelf__book" d={`M${String(-24 + index * 7)} ${String(3 - index * 3.5)}v-16l5 -2.5v16z`} />
        ))}
      </g>

      {/* On the back wall: the board, the clock and the meter. Their words are in the layer above. */}
      <g className={`office-board office-board--${model.status}`} transform={`translate(${String(layout.board.x)} ${String(layout.board.y)})`}>
        <path className="office-board__panel" d="M-60 -44 60 8v30L-60 -14z" />
      </g>
      <g className="office-clock" transform={`translate(${String(layout.clock.x)} ${String(layout.clock.y)})`}>
        <ellipse className="office-clock__face" cx="0" cy="0" rx="11" ry="13" />
        <path className="office-clock__hands" d="M0 -7V0l4 4" />
      </g>
      <g className={`office-meter office-meter--${model.meter.level}`} transform={`translate(${String(layout.meter.x)} ${String(layout.meter.y)})`}>
        <path className="office-meter__case" d="M-7 -14 7 -7v24L-7 10z" />
        <path className="office-meter__level" d="M-4 3 4 7v6L-4 9z" />
      </g>

      {/* The reception, at the front: where the goal came from and questions wait. */}
      <ellipse className="office-shadow" cx={layout.reception.x} cy={layout.reception.y + 6} rx="60" ry="22" />
      <Box across={layout.reception.across} depth={layout.reception.depth} width={1.5} length={0.45} height={30} className="office-box office-box--reception" />
      {model.reception.waiting > 0 && (
        <g className="office-bell" transform={`translate(${String(project(layout.reception.across + 0.45, layout.reception.depth, 30).x)} ${String(project(layout.reception.across + 0.45, layout.reception.depth, 30).y)})`}>
          <path className="office-bell__dome" d="M-7 0a7 7 0 0 1 14 0z" />
          <path className="office-bell__base" d="M-9 0h18v2.5h-18z" />
        </g>
      )}

      {seated.map(({ desk, spot }) => (
        <DeskGroup key={desk.name} desk={desk} spot={spot} books={desk.lead ? model.library.length : 0} />
      ))}

      {/* Folders on their way lie at the edge of the desk they are going to. */}
      {model.folders.map((folder) => {
        const target = spotOf(folder.phase === "arriving" ? folder.to : folder.from);
        if (target === null) return null;
        const at = project(target.across + 0.42, target.depth - 0.1, DESK.height);
        // It travels from the other desk: the sender's, or on its way back the receiver's.
        const source = spotOf(folder.phase === "arriving" ? folder.from : folder.to);
        const from = source === null ? undefined : project(source.across + 0.42, source.depth - 0.1, DESK.height);
        return <FolderShape key={`${String(folder.seq)}-${folder.phase}`} at={at} phase={folder.phase} from={from} />;
      })}
    </svg>
  );
}

/**
 * Memoized on the model and the layout: the fold replaces the model only
 * when an event arrives, and a camera move changes neither.
 */
export const Room = memo(RoomArt);
