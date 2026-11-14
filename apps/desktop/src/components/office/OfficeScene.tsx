import {
  memo,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
  type PointerEvent,
  type WheelEvent,
} from "react";

import { sameData } from "../../lib/equal";
import { ellipsise, formatDuration, moneyShort } from "../../lib/format";
import {
  fitCamera,
  followCamera,
  labelDensity,
  placeOffice,
  project,
  zoomCamera,
  type Camera,
  type Point,
  type Size,
  type Spot,
  zoomBand,
} from "../../lib/officeLayout";
import { currentPlatform } from "../../lib/platform";
import { matchesKeys, shortcut, withShortcut } from "../../lib/shortcuts";
import { splitPath } from "../../state/files";
import { stampReason, type Desk, type OfficeModel, type Slip } from "../../state/office";
import type { MotionMode } from "../../state/timeline";
import { Icon } from "../icons/Icon";
import { useContextMenu } from "../ui/ContextMenu";
import { Status } from "../ui/Status";
import { IconButton } from "../ui/controls";

import { Room } from "./Room";
import { BOARD_FILES, cardsOf, deskReach, labelGeometry, slipsOnDesk, TROUBLE_CHARS } from "./estimates";
import { FACE_ICON, FAMILY_ICON, SLIP_TONE, STAMP_ICON } from "./glyphs";

/**
 * A run as an office (Phase 20, brief section 7): each agent at its own desk,
 * the calls in hand as slips with their stamps, delegated work as folders,
 * and the goal, the outcome, the clock and the meter on the walls.
 *
 * Everything inside the stage is drawn from `model`, a pure projection of
 * the log, so the room is the same live and on replay. The drawing is an
 * SVG hidden from screen readers; over it lies a layer of real elements, so
 * every desk is a button with a name and every state is a word.
 *
 * The camera is transport, like the scrubber: it follows the viewport and
 * the viewer, not the log. It lives on the stage's wrapper, which carries
 * `data-transport` so the identity test can leave it out.
 */

export interface OfficeSceneProps {
  model: OfficeModel;
  /** One sentence about the run at this cursor, read out as the room's description. */
  description: string;
  selectedAgent: string | null;
  onSelectAgent: (name: string | null) => void;
  /** Open a file the run wrote. Without it the board lists them as text. */
  onOpenFile?: ((path: string) => void) | undefined;
  /**
   * Whether the latest cursor move is a step to animate or a move to settle
   * at once (decision D1). Transport: it goes on the stage beside the camera.
   */
  motion?: MotionMode | undefined;
  /** The room fills the window. Without `onToggleExpand` no button offers it. */
  expanded?: boolean | undefined;
  onToggleExpand?: (() => void) | undefined;
}

const clockLabel = (seconds: number): string => formatDuration(seconds * 1000);

/** How far above a desk's floor spot the camera aims, in room pixels. */
const FOCUS_LIFT = 64;

/**
 * Where a label hangs, as a point of the room. The stylesheet multiplies it
 * by the camera's zoom, so a label follows its desk while keeping its own
 * size, and nothing about the camera is written into the label itself.
 */
const at = (point: Point): CSSProperties => ({ "--x": point.x, "--y": point.y }) as CSSProperties;

function SlipCard({ slip }: { slip: Slip }) {
  const reason = slip.stamp === null ? null : stampReason(slip.stamp, slip);
  return (
    <span className={`office-slip office-slip--${SLIP_TONE[slip.state]}`} data-state={slip.state}>
      <Icon name={FAMILY_ICON[slip.family]} size={16} />
      <span className="office-slip__action">{slip.action}</span>
      <span className="office-slip__label">
        {slip.stamp !== null && <Icon name={STAMP_ICON[slip.stamp.kind]} size={16} />}
        {slip.label}
        {reason !== null && <span className="office-slip__reason">: {reason}</span>}
      </span>
    </span>
  );
}

interface DeskWordsProps {
  desk: Desk;
  spot: Spot;
  dense: boolean;
  selected: boolean;
  tabbable: boolean;
  onSelect: (name: string | null) => void;
}

function DeskWords({ desk, spot, dense, selected, tabbable, onSelect }: DeskWordsProps) {
  const slips = slipsOnDesk(desk);
  const slip = slips.at(-1);
  const earlier = slips.length - 1;
  const glyph = desk.face === "tool" ? FAMILY_ICON[desk.family ?? "unknown"] : FACE_ICON[desk.face];
  const plate = (
    <button
      type="button"
      className="office-desk__button"
      data-desk={desk.name}
      data-testid={`office-desk-${desk.name}`}
      aria-label={desk.accessibleName}
      aria-pressed={selected}
      title={desk.ghost ? desk.accessibleName : `${desk.role ?? desk.name}. ${desk.activityLabel}.`}
      tabIndex={tabbable ? 0 : -1}
      disabled={desk.ghost}
      onClick={() => {
        // A pressed desk is unpressed by pressing it again, which closes its inspector.
        onSelect(selected ? null : desk.name);
      }}
    >
      {/* The spaces between the parts are for anything that reads the plate
          as one line of text; the grid does not draw them. */}
      <span className="office-desk__name">{desk.name}</span>
      {!dense && " "}
      {!dense && (
        <span className={`office-desk__state office-desk__state--${desk.face}`}>
          <Icon name={glyph} size={16} />
          {desk.stateLabel}
        </span>
      )}
      {!dense && desk.model !== null && " "}
      {!dense && desk.model !== null && <span className="office-desk__model">{desk.model}</span>}
    </button>
  );
  // The papers on the desk, one under the other however long each runs.
  const papers = !dense && (desk.trouble !== null || slip !== undefined) && (
    <div className="office-desk__papers">
      {desk.trouble !== null && (
        <p className={`office-trouble office-trouble--${desk.trouble.kind}`} title={desk.trouble.message}>
          <Icon name={desk.trouble.kind === "alarm" ? "triangle-alert" : "info"} size={16} />
          <span>{ellipsise(desk.trouble.message, TROUBLE_CHARS)}</span>
        </p>
      )}
      {slip !== undefined && <SlipCard slip={slip} />}
      {earlier > 0 && <span className="office-desk__more">and {earlier} more this step</span>}
    </div>
  );
  return (
    <div
      className={`office-desk${desk.lead ? " office-desk--lead" : ""}${desk.ghost ? " office-desk--ghost" : ""}`}
      style={at(spot)}
      data-activity={desk.activity}
      data-face={desk.face}
      data-quiet={desk.quiet ? "true" : "false"}
    >
      {desk.bubble !== null && (
        <p className={`office-bubble office-bubble--${desk.bubble.kind}`}>
          <span className="sr-only">{desk.bubble.kind === "thought" ? `${desk.name} is saying: ` : `${desk.name} said: `}</span>
          {desk.bubble.text === "" ? "…" : desk.bubble.text}
        </p>
      )}
      {/* A worker's plate stands over its head and its papers lie in front of
          its desk. The lead desk has the first row behind it and nothing in
          front, so its plate and papers hang in front of it, one under the
          other: over its head the plate would lie under the papers of the
          desk behind. */}
      {desk.lead ? (
        <div className="office-desk__front">
          {plate}
          {papers}
        </div>
      ) : (
        <>
          {plate}
          {papers}
        </>
      )}
    </div>
  );
}

/**
 * The model builds every desk again on every event, so a desk's words are
 * drawn again only when something they show changed: in a room of twenty,
 * an event usually changes one desk. The desk is compared as data, so a
 * field added to it can never be left out of the comparison.
 */
const DeskButton = memo(
  DeskWords,
  (before, after) =>
    before.spot === after.spot &&
    before.dense === after.dense &&
    before.selected === after.selected &&
    before.tabbable === after.tabbable &&
    before.onSelect === after.onSelect &&
    sameData(before.desk, after.desk),
);

export function OfficeScene({
  model,
  description,
  selectedAgent,
  onSelectAgent,
  onOpenFile,
  motion = "settle",
  expanded = false,
  onToggleExpand,
}: OfficeSceneProps) {
  const layout = useMemo(() => placeOffice(model.desks.length), [model.desks.length]);
  const dense = labelDensity(model.desks.length + (model.lead === null ? 0 : 1)) === "names";

  // --- transport: the camera ---------------------------------------------
  const frame = useRef<HTMLDivElement>(null);
  const [viewport, setViewport] = useState<Size>({ width: 0, height: 0 });
  /** Null follows the work; a camera is where the viewer left it. */
  const [held, setHeld] = useState<Camera | null>(null);
  /**
   * The room at which the viewer last pressed a view button or key: the
   * camera eases to where that sends it, until the next event. A drag or
   * the wheel moves it at once, as a hand does.
   */
  const [pressedAt, setPressedAt] = useState<OfficeModel | null>(null);
  const move = (next: Camera | null) => {
    setHeld(next);
    setPressedAt(model);
  };
  useLayoutEffect(() => {
    const element = frame.current;
    if (element === null) return undefined;
    const observer = new ResizeObserver(([entry]) => {
      const box = entry?.contentRect;
      if (box !== undefined) setViewport({ width: box.width, height: box.height });
    });
    observer.observe(element);
    return () => {
      observer.disconnect();
    };
  }, []);

  const spots = useMemo(() => {
    const found = new Map<string, Spot>();
    model.desks.forEach((desk, index) => {
      const spot = layout.desks[index];
      if (spot !== undefined) found.set(desk.name, spot);
    });
    if (model.lead !== null) found.set(model.lead.name, layout.lead);
    return found;
  }, [model.desks, model.lead, layout]);

  // The middle of what belongs to a desk is above its floor spot: the
  // character and the name plate over its head.
  const focusSpot = model.focus === null ? undefined : spots.get(model.focus);
  const focus: Point | null = focusSpot === undefined ? null : { x: focusSpot.x, y: focusSpot.y - FOCUS_LIFT };
  const focusDesk = model.focus === null ? undefined : model.lead?.name === model.focus ? model.lead : model.desks.find((desk) => desk.name === model.focus);
  // The cards' words follow the band the camera draws them at, and the
  // camera follows the cards: estimate at mid, then again at the band that
  // fit gave.
  // Fitted again only when a card's height, the room or the view changes:
  // most events change none of them.
  const rough = cardsOf(model.board, model.reception, model.lead);
  const band = useMemo(
    () => zoomBand(fitCamera(layout, viewport, { board: rough.board, reception: rough.reception, lead: rough.lead }).scale),
    [layout, viewport, rough.board, rough.reception, rough.lead],
  );
  const cards = cardsOf(model.board, model.reception, model.lead, band);
  const fit = useMemo(
    () => fitCamera(layout, viewport, { board: cards.board, reception: cards.reception, lead: cards.lead }),
    [layout, viewport, cards.board, cards.reception, cards.lead],
  );
  const camera =
    held ??
    followCamera(
      layout,
      viewport,
      focus,
      cards,
      (scale) => (focusDesk === undefined ? { above: 0, below: 0 } : deskReach(focusDesk, scale, FOCUS_LIFT)),
      fit,
    );
  const centre: Point = { x: viewport.width / 2, y: viewport.height / 2 };

  const drag = useRef<{ x: number; y: number; camera: Camera } | null>(null);
  const onPointerDown = (event: PointerEvent<HTMLDivElement>) => {
    // A press on a desk or a link is that control's, not the start of a pan.
    if (event.button !== 0 || (event.target as Element).closest("button, a") !== null) return;
    drag.current = { x: event.clientX, y: event.clientY, camera };
    event.currentTarget.setPointerCapture(event.pointerId);
  };
  const onPointerMove = (event: PointerEvent<HTMLDivElement>) => {
    const start = drag.current;
    if (start === null) return;
    setHeld({ ...start.camera, x: start.camera.x + event.clientX - start.x, y: start.camera.y + event.clientY - start.y });
    setPressedAt(null);
  };
  const onPointerUp = () => {
    drag.current = null;
  };
  const onWheel = (event: WheelEvent<HTMLDivElement>) => {
    // Chromium reports a trackpad pinch as a wheel with Ctrl held; a plain
    // wheel zooms too, as on a map. The page behind does not scroll.
    const box = event.currentTarget.getBoundingClientRect();
    const factor = Math.exp(-event.deltaY * (event.ctrlKey ? 0.01 : 0.002));
    setHeld(zoomCamera(camera, factor, { x: event.clientX - box.left, y: event.clientY - box.top }));
    setPressedAt(null);
  };

  // --- the keyboard ---------------------------------------------------------
  const order = useMemo(() => [...(model.lead === null ? [] : [model.lead]), ...model.desks].filter((desk) => !desk.ghost), [model.lead, model.desks]);
  const tabStop = order.find((desk) => desk.name === selectedAgent)?.name ?? order.find((desk) => desk.name === model.focus)?.name ?? order[0]?.name ?? null;
  // A desk's own actions, from a right-click or the keyboard's menu key. The
  // menu renders into the document's body, outside the projection.
  const deskMenu = useContextMenu(
    "Desk",
    (element) => {
      const name = element.dataset.desk;
      if (name === undefined || element.hasAttribute("disabled")) return [];
      const open = selectedAgent === name;
      return [
        {
          id: "inspect",
          label: open ? "Close the inspector" : "Inspect",
          onSelect: () => {
            onSelectAgent(open ? null : name);
          },
        },
      ];
    },
    "[data-desk]",
  );

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    deskMenu.trigger.onKeyDown(event);
    if (event.defaultPrevented || event.ctrlKey || event.metaKey || event.altKey) return;
    const buttons = [...event.currentTarget.querySelectorAll<HTMLButtonElement>("[data-desk]:not(:disabled)")];
    const current = buttons.findIndex((button) => button === document.activeElement);
    const go = (index: number) => {
      event.preventDefault();
      buttons[(index + buttons.length) % buttons.length]?.focus();
    };
    switch (event.key) {
      case "ArrowRight":
      case "ArrowDown":
        if (current >= 0) go(current + 1);
        return;
      case "ArrowLeft":
      case "ArrowUp":
        if (current >= 0) go(current - 1);
        return;
      case "Home":
        if (current >= 0) go(0);
        return;
      case "End":
        if (current >= 0) go(buttons.length - 1);
        return;
      case "Escape":
        // Closing the inspector is this Escape's whole job: a full-screen
        // room stays full screen until the next one.
        if (selectedAgent !== null) {
          event.stopPropagation();
          onSelectAgent(null);
        }
        return;
      default:
    }
    // The camera's keys, from the keyboard map.
    if (matchesKeys(event, shortcut("office-follow").keys)) move(null);
    else if (matchesKeys(event, shortcut("office-fit").keys)) move(fit);
    else if (matchesKeys(event, shortcut("office-zoom-in").keys) || event.key === "=") move(zoomCamera(camera, 1.25, centre));
    else if (matchesKeys(event, shortcut("office-zoom-out").keys)) move(zoomCamera(camera, 0.8, centre));
  };

  const { board, reception, clock, meter } = model;
  const platform = currentPlatform();
  const receptionLabel = project(layout.reception.across, layout.reception.depth, 34);

  return (
    <div className="office" data-testid="office" role="region" aria-label="The office">
      <p className="sr-only" data-testid="office-description">
        {description}
      </p>
      {/* Completions, the run's end and budget warnings, said once each. Questions
          are announced by the approval panel, and are not repeated here. */}
      <p className="sr-only" aria-live="polite" data-testid="office-announcement">
        {model.announcement?.text ?? ""}
      </p>
      {/* Apart from the above, so that a desk finishing never talks over it. */}
      <p className="sr-only" aria-live="polite" data-testid="office-budget-announcement">
        {meter.announcement ?? ""}
      </p>

      <div
        ref={frame}
        className="office__frame"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        onWheel={onWheel}
        onKeyDown={onKeyDown}
        onContextMenu={deskMenu.trigger.onContextMenu}
      >
        <div
          className="office__stage"
          data-transport="camera"
          data-follow={held === null ? "true" : "false"}
          data-motion={motion}
          data-camera={pressedAt === model || (held === null && motion === "step") ? "ease" : "still"}
          data-zoom={zoomBand(camera.scale)}
          style={
            {
              ...labelGeometry(),
              "--office-zoom": camera.scale,
              "--office-x": `${String(Math.round(camera.x))}px`,
              "--office-y": `${String(Math.round(camera.y))}px`,
            } as CSSProperties
          }
        >
          <div className="office__art">
            <Room model={model} layout={layout} />
          </div>

          <div className="office__layer">
            <div className="office-board-card" style={at(layout.board)}>
              <p className="office-board-card__status">
                <Status kind={board.status}>{board.statusLabel}</Status>
              </p>
              <p className="office-board-card__goal" title={board.goal ?? undefined}>
                {board.goal ?? "Waiting for the run to start"}
              </p>
              {board.claim !== null && (
                <p className="office-board-card__claim">
                  <span className="office-board-card__said">{board.claim.kind === "summary" ? "The supervisor said" : "Why it stopped"}</span>
                  {board.claim.text}
                </p>
              )}
              {board.documents.length > 0 && (
                <ul className="office-board-card__files" aria-label="Files this run wrote">
                  {board.documents.slice(0, BOARD_FILES).map((file) => (
                    <li key={file.path}>
                      {onOpenFile === undefined ? (
                        <span title={file.path}>{splitPath(file.path).name}</span>
                      ) : (
                        <button
                          type="button"
                          className="link"
                          title={file.path}
                          onClick={() => {
                            onOpenFile(file.path);
                          }}
                        >
                          {splitPath(file.path).name}
                        </button>
                      )}
                    </li>
                  ))}
                  {board.documents.length > BOARD_FILES && <li>and {board.documents.length - BOARD_FILES} more</li>}
                </ul>
              )}
              {board.memoryPath !== null && <p className="office-board-card__note">A note of this run was saved for later.</p>}
              {board.unrecognised.map((type) => (
                <p key={type} className="office-board-card__warning">
                  This version does not know the event {type}.
                </p>
              ))}
            </div>

            <p className="office-wall-label" style={at(layout.clock)}>
              <Icon name="clock" size={16} />
              <span className="num">
                {clock.elapsedSeconds === null ? "Not started" : clockLabel(clock.elapsedSeconds)}
                {clock.limitSeconds !== null && ` of ${clockLabel(clock.limitSeconds)}`}
              </span>
            </p>
            <p className={`office-wall-label office-wall-label--meter office-wall-label--${meter.level}`} style={at(layout.meter)}>
              <Icon name="circle-dollar-sign" size={16} />
              <span className="num">{moneyShort(meter.costMicros)}</span>
              {meter.level !== "ok" && <span>{meter.level === "over" ? "Monthly limit reached" : "Close to the monthly limit"}</span>}
            </p>
            {model.library.length > 0 && (
              <p className="office-wall-label" style={at(layout.library)}>
                <Icon name="library" size={16} />
                {model.library.length} from your notes
              </p>
            )}

            <p className="office-reception" style={at(receptionLabel)}>
              <span className="office-reception__you">You</span>
              <span className="office-reception__origin">
                {reception.origin}
                {reception.sender !== null && `, ${reception.sender}`}
              </span>
              {reception.waiting > 0 && (
                <span className={`office-reception__waiting risk risk--${reception.waitingRisk ?? "medium"}`}>
                  <Icon name="bell" size={16} />
                  {reception.waiting} question{reception.waiting === 1 ? "" : "s"} waiting: answer above
                </span>
              )}
            </p>

            {model.lead !== null && (
              <DeskButton
                desk={model.lead}
                spot={layout.lead}
                dense={dense}
                selected={selectedAgent === model.lead.name}
                tabbable={tabStop === model.lead.name}
                onSelect={onSelectAgent}
              />
            )}
            {model.desks.map((desk, index) => {
              const spot = layout.desks[index];
              return spot === undefined ? null : (
                <DeskButton
                  key={desk.name}
                  desk={desk}
                  spot={spot}
                  dense={dense}
                  selected={selectedAgent === desk.name}
                  tabbable={tabStop === desk.name}
                  onSelect={onSelectAgent}
                />
              );
            })}
          </div>
        </div>
      </div>

      <div className="office__controls" data-transport="controls" role="group" aria-label="View of the office">
        <IconButton
          icon="locate-fixed"
          label="Follow the work"
          title={withShortcut("Follow the work", "office-follow", platform)}
          pressed={held === null}
          onClick={() => {
            move(null);
          }}
        />
        <IconButton
          icon="scan"
          label="Show the whole room"
          title={withShortcut("Show the whole room", "office-fit", platform)}
          onClick={() => {
            move(fit);
          }}
        />
        <IconButton
          icon="zoom-in"
          label="Zoom in"
          title={withShortcut("Zoom in", "office-zoom-in", platform)}
          onClick={() => {
            move(zoomCamera(camera, 1.25, centre));
          }}
        />
        <IconButton
          icon="zoom-out"
          label="Zoom out"
          title={withShortcut("Zoom out", "office-zoom-out", platform)}
          onClick={() => {
            move(zoomCamera(camera, 0.8, centre));
          }}
        />
        {onToggleExpand !== undefined && (
          <IconButton
            icon={expanded ? "minimize-2" : "maximize-2"}
            label={expanded ? "Leave full screen" : "Full screen"}
            title={expanded ? "Leave full screen (Esc)" : "Full screen"}
            pressed={expanded}
            onClick={onToggleExpand}
          />
        )}
      </div>
      {/* Portals into the document's body: nothing of it is in the room. */}
      {deskMenu.menu}
    </div>
  );
}
