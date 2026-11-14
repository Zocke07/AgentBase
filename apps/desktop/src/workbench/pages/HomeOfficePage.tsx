import type { Run, ScheduleResponse } from "@agentbase/schemas";

import { NowOffice, RestingOffice } from "../../components/HomeOffice";

/**
 * Home's office (brief 7.13): a desk over each going run, one waiting on a
 * question; and the room at rest with the next automation on the calendar.
 */

const run = (id: string, title: string | null, goal: string, status: Run["status"]): Run => ({
  id,
  space_id: "space-handbook",
  goal,
  title,
  status,
  origin: "ui",
  origin_ref: null,
  created_at: "2026-11-14T08:00:00Z",
  finished_at: null,
});

const RUNS: readonly Run[] = [
  run("run-1", "Weekly summary", "Summarise the week's chapter reviews.", "running"),
  run("run-2", null, "Check chapter two against the style guide.", "running"),
  run("run-3", "Build check", "Run the handbook's build.", "pending"),
];

const SCHEDULES: readonly ScheduleResponse[] = [
  {
    id: "s-1",
    space_id: "space-handbook",
    name: "Morning digest",
    goal: "Summarise the night.",
    cadence: { kind: "daily", at: "07:00" },
    enabled: true,
    next_run_at: "2026-11-16T07:00:00Z",
    created_at: "2026-11-01T00:00:00Z",
    updated_at: "2026-11-01T00:00:00Z",
    summary: "Daily at 07:00",
  },
];

const NOTHING = () => undefined;

export function HomeOfficePage() {
  return (
    <div className="wb-controls">
      <section>
        <h2 className="wb-group__title">Runs going now, one waiting for you</h2>
        <NowOffice runs={RUNS} statusOf={(row) => row.status} waitingOn={new Set(["run-2"])} onOpenRun={NOTHING} />
      </section>
      <section>
        <h2 className="wb-group__title">Nothing going</h2>
        <RestingOffice schedules={SCHEDULES} known readAt={Date.parse("2026-11-15T00:00:00Z")} />
      </section>
    </div>
  );
}
