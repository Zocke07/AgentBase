import type { ReactNode } from "react";

import { restDesk } from "../state/floorPlan";
import type { Desk } from "../state/office";

import { DeskFigure } from "./office/Room";
import { VIGNETTE_SPOT, vignetteView } from "./office/vignette";

/**
 * An empty state (Phase 20, brief 6.7 and 7.13): a small vignette in the
 * office's own materials, one sentence and one action. Runs shows the room
 * at rest, Knowledge the library, Automations the calendar. The vignette is
 * decoration and is hidden from screen readers; the sentence says it all.
 */

export type EmptyScene = "room" | "library" | "calendar";

export interface EmptyStateProps {
  scene: EmptyScene;
  /** One sentence: what is not here yet, and what would put it here. */
  children: ReactNode;
  action?: { label: string; onClick: () => void } | undefined;
  testId?: string | undefined;
}

const VIEW = vignetteView(132, 116, 92);

/** A desk at rest, its figure ready, or empty with the library's books on it. */
function deskAtRest(withFigure: boolean): Desk {
  return restDesk("empty", { ghost: !withFigure });
}

function Calendar() {
  // A wall calendar: a sheet, its binding, and a month of days with one marked.
  const days = Array.from({ length: 15 }, (_, index) => ({ column: index % 5, row: Math.floor(index / 5) }));
  return (
    <svg className="empty-state__scene" viewBox="0 0 132 116" aria-hidden="true" focusable="false">
      <rect className="empty-state__shadow" x="26" y="22" width="84" height="80" rx="8" />
      <rect className="empty-state__sheet" x="22" y="16" width="84" height="80" rx="8" />
      <path className="empty-state__band" d="M22 24a8 8 0 0 1 8-8h68a8 8 0 0 1 8 8v8H22z" />
      <rect className="empty-state__ring" x="42" y="10" width="6" height="12" rx="3" />
      <rect className="empty-state__ring" x="80" y="10" width="6" height="12" rx="3" />
      {days.map(({ column, row }) => (
        <rect
          key={`${String(column)}-${String(row)}`}
          className={column === 2 && row === 1 ? "empty-state__day empty-state__day--marked" : "empty-state__day"}
          x={32 + column * 13}
          y={42 + row * 15}
          width="9"
          height="9"
          rx="2"
        />
      ))}
    </svg>
  );
}

/** The vignette alone, for a welcome that has more to say than a sentence. */
export function EmptyVignette({ scene }: { scene: EmptyScene }) {
  return scene === "calendar" ? (
    <Calendar />
  ) : (
    <svg className="empty-state__scene" viewBox={VIEW} aria-hidden="true" focusable="false">
      <DeskFigure desk={deskAtRest(scene === "room")} spot={VIGNETTE_SPOT} books={scene === "library" ? 3 : 0} />
    </svg>
  );
}

/**
 * The start screen's desk (brief 7.13): its three stages fill it in turn.
 * The figure sits down when the engine answers, the library's books land
 * when the settings are read, and the lamp lights when the spaces arrive.
 * The stages are still named in words beside it; this only shows them.
 */
export function StartupDesk({ engine, settings, spaces }: { engine: boolean; settings: boolean; spaces: boolean }) {
  const desk = { ...deskAtRest(engine), activity: spaces ? ("spawned" as const) : ("completed" as const) };
  return (
    <svg
      className={`empty-state__scene startup__scene${engine ? "" : " startup__scene--waiting"}`}
      viewBox={VIEW}
      aria-hidden="true"
      focusable="false"
    >
      <DeskFigure desk={desk} spot={VIGNETTE_SPOT} books={settings ? 2 : 0} />
    </svg>
  );
}

export function EmptyState({ scene, children, action, testId }: EmptyStateProps) {
  return (
    <div className="empty-state" data-testid={testId}>
      <EmptyVignette scene={scene} />
      <p className="empty-state__sentence">{children}</p>
      {action !== undefined && (
        <button type="button" className="button button--primary" onClick={action.onClick}>
          {action.label}
        </button>
      )}
    </div>
  );
}
