import type { Run, ScheduleResponse } from "@agentbase/schemas";

import { whenLabel } from "../lib/format";
import { nextAutomation, runDesk } from "../state/floorPlan";

import { EmptyVignette } from "./EmptyState";
import { RunCard } from "./RunCard";
import { DeskFigure } from "./office/Room";
import { VIGNETTE_SPOT, vignetteView } from "./office/vignette";

/**
 * Home's office (Phase 20, brief 7.13). While runs are going, a desk lights
 * for each, over the run's own card: its title, its status and any question
 * waiting. Otherwise the room is at rest and the wall calendar says when
 * the space next runs on its own. It projects the runs list, not a log, so
 * it is not under replay identity (decision D9), and it opens no stream.
 */

const VIEW = vignetteView(124, 116, 96);

export interface NowOfficeProps {
  runs: readonly Run[];
  statusOf: (run: Run) => Run["status"];
  waitingOn: ReadonlySet<string>;
  onOpenRun: (id: string) => void;
}

export function NowOffice({ runs, statusOf, waitingOn, onOpenRun }: NowOfficeProps) {
  return (
    <ul className="now-office" aria-label="Runs going now">
      {runs.map((run) => {
        const waiting = waitingOn.has(run.id);
        return (
          <li key={run.id} className={`now-office__desk${waiting ? " now-office__desk--waiting" : ""}`}>
            <svg className="now-office__figure" viewBox={VIEW} aria-hidden="true" focusable="false">
              <DeskFigure desk={runDesk(run, statusOf(run), waiting)} spot={VIGNETTE_SPOT} />
            </svg>
            <RunCard run={run} liveStatus={statusOf(run)} needsApproval={waiting} onOpen={onOpenRun} />
          </li>
        );
      })}
    </ul>
  );
}

export interface RestingOfficeProps {
  schedules: readonly ScheduleResponse[];
  /** The schedules were read. Until then, or if they could not be, nothing is said of them. */
  known: boolean;
  /** When the schedules were read: a time before it is not "next". */
  readAt: number;
}

export function RestingOffice({ schedules, known, readAt }: RestingOfficeProps) {
  const next = known ? nextAutomation(schedules, readAt) : null;
  return (
    <div className="now-office__rest" data-testid="home-at-rest">
      <EmptyVignette scene="room" />
      <EmptyVignette scene="calendar" />
      <p className="now-office__sentence">
        Nothing is running.
        {known && " "}
        {known && (next === null ? "Nothing in this space is scheduled to run on its own." : `Next on its own: ${next.name}, ${whenLabel(next.at)}.`)}
      </p>
    </div>
  );
}
